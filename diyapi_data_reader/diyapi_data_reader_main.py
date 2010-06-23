# -*- coding: utf-8 -*-
"""
diyapi_data_reader_main.py

Receives block read requests.
Looks up pointers to data by querying the database server
Looks for files in both the hashfanout area 
Responds with content or "not available"
"""
from collections import namedtuple
import logging
import os.path
import sys
import time

import Statgrabber

from diyapi_tools import amqp_connection
from diyapi_tools.standard_logging import format_timestamp
from diyapi_tools.low_traffic_thread import LowTrafficThread, \
    low_traffic_routing_tag
from diyapi_tools import message_driven_process as process
from diyapi_tools.persistent_state import load_state, save_state
from diyapi_tools import repository

from messages.process_status import ProcessStatus

from messages.retrieve_key_start import RetrieveKeyStart
from messages.retrieve_key_start_reply import RetrieveKeyStartReply
from messages.retrieve_key_next import RetrieveKeyNext
from messages.retrieve_key_next_reply import RetrieveKeyNextReply
from messages.retrieve_key_final import RetrieveKeyFinal
from messages.retrieve_key_final_reply import RetrieveKeyFinalReply
from messages.database_key_lookup import DatabaseKeyLookup
from messages.database_key_lookup_reply import DatabaseKeyLookupReply

_log_path = u"/var/log/pandora/diyapi_data_reader_%s.log" % (
    os.environ["SPIDEROAK_MULTI_NODE_NAME"],
)
_queue_name = "data-reader-%s" % (os.environ["SPIDEROAK_MULTI_NODE_NAME"], )
_routing_header = "data_reader"
_routing_key_binding = ".".join([_routing_header, "*"])
_key_lookup_reply_routing_key = ".".join([
    _routing_header,
    DatabaseKeyLookupReply.routing_tag,
])
_low_traffic_routing_key = ".".join([
    _routing_header, 
    low_traffic_routing_tag,
])
_key_lookup_timeout = 60.0
_retrieve_timeout = 30 * 60.0


_retrieve_state_tuple = namedtuple("RetrieveState", [ 
    "timeout",
    "timeout_function",
    "avatar_id",
    "key",
    "version_number",
    "segment_number",
    "reply_exchange",
    "reply_routing_header",
    "segment_size",
    "sequence",
    "file_name",
])

def _handle_key_lookup_timeout(request_id, state):
    """called when we wait too long for a reply to a KeyLookup message"""
    log = logging.getLogger("_handle_key_lookup_timeout")

    try:
        retrieve_state = state.pop(request_id)
    except KeyError:
        log.error("can't find %s in state" % (request_id, ))
        return []

    log.error("timeout: %s %s %s" % (
        retrieve_state.avatar_id,
        retrieve_state.key,
        request_id,
    ))

    # tell the caller that we're not working
    reply_exchange = retrieve_state.reply_exchange
    reply_routing_key = "".join(
        [retrieve_state.reply_routing_header, 
         ".", 
         RetrieveKeyStartReply.routing_tag]
    )
    reply = RetrieveKeyStartReply(
        request_id,
        RetrieveKeyStartReply.error_timeout_waiting_key_insert,
        error_message="timeout waiting for database_server"
    )
    return [(reply_exchange, reply_routing_key, reply, )] 

def _handle_retrieve_timeout(request_id, state):
    """called when we wait too long for a RetrieveKeyNext or RetrieveKeyFinal"""
    log = logging.getLogger("_handle_retrieve_timeout")

    try:
        retrieve_state = state.pop(request_id)
    except KeyError:
        log.error("can't find %s in state" % (request_id, ))
        return []

    log.error("timeout: %s %s %s" % (
        retrieve_state.avatar_id,
        retrieve_state.key,
        request_id,
    ))


def _handle_retrieve_key_start(state, message_body):
    log = logging.getLogger("_handle_retrieve_key_start")
    message = RetrieveKeyStart.unmarshall(message_body)
    log.info("avatar_id = %s, key = %s" % (message.avatar_id, message.key, ))

    reply_routing_key = "".join(
        [message.reply_routing_header, ".", RetrieveKeyStartReply.routing_tag]
    )

    # if we already have a state entry for this request_id, something is wrong
    if message.request_id in state:
        error_string = "invalid duplicate request_id in RetrieveKeyStart"
        log.error(error_string)
        reply = RetrieveKeyStartReply(
            message.request_id,
            RetrieveKeyStartReply.error_invalid_duplicate,
            error_message=error_string
        )
        return [(message.reply_exchange, reply_routing_key, reply, )] 

    # save stuff we need to recall in state
    state[message.request_id] = _retrieve_state_tuple(
        timeout=time.time()+_key_lookup_timeout,
        timeout_function=_handle_key_lookup_timeout,
        avatar_id = message.avatar_id,
        key = message.key,
        version_number=message.version_number,
        segment_number=message.segment_number,
        reply_exchange = message.reply_exchange,
        reply_routing_header = message.reply_routing_header,
        segment_size = None,
        sequence = None,
        file_name = None
    )

    # send a lookup request to the database, with the reply
    # coming back to us
    local_exchange = amqp_connection.local_exchange_name
    database_request = DatabaseKeyLookup(
        message.request_id,
        message.avatar_id,
        local_exchange,
        _routing_header,
        message.key,
        message.version_number,
        message.segment_number
    )
    return [(local_exchange, database_request.routing_key, database_request, )]

def _handle_retrieve_key_next(state, message_body):
    log = logging.getLogger("_handle_retrieve_key_next")
    message = RetrieveKeyNext.unmarshall(message_body)

    try:
        retrieve_state = state.pop(message.request_id)
    except KeyError:
        # if we don't have any state for this message body, there's nobody we 
        # can complain too
        log.error("No state for %r" % (message.request_id, ))
        return []

    log.info("avatar_id = %s, key = %s sequence = %s" % (
        retrieve_state.avatar_id, retrieve_state.key, message.sequence
    ))

    reply_exchange = retrieve_state.reply_exchange
    reply_routing_key = "".join(
        [retrieve_state.reply_routing_header, 
         ".", 
         RetrieveKeyNextReply.routing_tag]
    )

    if message.sequence != retrieve_state.sequence+1:
        error_string = "%s %s out of sequence %s %s" % (
            retrieve_state.avatar_id, 
            retrieve_state.key,
            message.sequence,
            retrieve_state.sequence+1
        )
        log.error(error_string)
        reply = RetrieveKeyNextReply(
            message.request_id,
            message.sequence,
            RetrieveKeyNextReply.error_out_of_sequence,
            error_message=error_string
        )
        return [(reply_exchange, reply_routing_key, reply, )] 

    content_path = repository.content_path(
        retrieve_state.avatar_id, 
        retrieve_state.file_name
    ) 

    offset = message.sequence * retrieve_state.segment_size

    try:
        with open(content_path, "r") as input_file:
            input_file.seek(offset)
            data_content = input_file.read(retrieve_state.segment_size)
    except Exception, instance:
        log.exception("%s %s" % (
            retrieve_state.avatar_id,
            retrieve_state.key,
        ))
        reply = RetrieveKeyNextReply(
            message.request_id,
            message.sequence,
            RetrieveKeyNextReply.error_exception,
            error_message = str(instance)
        )
        return [(reply_exchange, reply_routing_key, reply, )]      

    state[message.request_id] = retrieve_state._replace(
        timeout=time.time()+_retrieve_timeout,
        sequence=message.sequence
    )

    Statgrabber.accumulate('diy_read_requests', 1)
    Statgrabber.accumulate('diy_read_bytes', len(data_content))

    reply = RetrieveKeyNextReply(
        message.request_id,
        message.sequence,
        RetrieveKeyNextReply.successful,
        data_content = data_content
    )

    return [(reply_exchange, reply_routing_key, reply, )]      

def _handle_retrieve_key_final(state, message_body):
    log = logging.getLogger("_handle_retrieve_key_final")
    message = RetrieveKeyNext.unmarshall(message_body)

    try:
        retrieve_state = state.pop(message.request_id)
    except KeyError:
        # if we don't have any state for this message body, there's nobody we 
        # can complain too
        log.error("No state for %r" % (message.request_id, ))
        return []

    log.info("avatar_id = %s, key = %s sequence = %s" % (
        retrieve_state.avatar_id, retrieve_state.key, message.sequence
    ))

    reply_exchange = retrieve_state.reply_exchange
    reply_routing_key = "".join(
        [retrieve_state.reply_routing_header, 
         ".", 
         RetrieveKeyFinalReply.routing_tag]
    )

    if message.sequence != retrieve_state.sequence+1:
        error_string = "%s %s out of sequence %s %s" % (
            retrieve_state.avatar_id, 
            retrieve_state.key,
            message.sequence,
            retrieve_state.sequence+1
        )
        log.error(error_string)
        reply = RetrieveKeyFinalReply(
            message.request_id,
            message.sequence,
            RetrieveKeyFinalReply.error_out_of_sequence,
            error_message=error_string
        )
        return [(reply_exchange, reply_routing_key, reply, )] 

    content_path = repository.content_path(
        retrieve_state.avatar_id, 
        retrieve_state.file_name
    ) 

    offset = message.sequence * retrieve_state.segment_size

    try:
        with open(content_path, "r") as input_file:
            input_file.seek(offset)
            data_content = input_file.read(retrieve_state.segment_size)
    except Exception, instance:
        log.exception("%s %s" % (
            retrieve_state.avatar_id,
            retrieve_state.key,
        ))
        reply = RetrieveKeyFinalReply(
            message.request_id,
            message.sequence,
            RetrieveKeyFinalReply.error_exception,
            error_message = str(instance)
        )
        return [(reply_exchange, reply_routing_key, reply, )] 

    # we don't save the state, because we are done

    Statgrabber.accumulate('diy_read_requests', 1)
    Statgrabber.accumulate('diy_read_bytes', len(data_content))

    reply = RetrieveKeyFinalReply(
        message.request_id,
        message.sequence,
        RetrieveKeyFinalReply.successful,
        data_content = data_content
    )

    return [(reply_exchange, reply_routing_key, reply, )]      

def _handle_process_status(_state, message_body):
    log = logging.getLogger("_handle_process_status")
    message = ProcessStatus.unmarshall(message_body)
    log.debug("%s %s %s %s" % (
        message.exchange,
        message.routing_header,
        message.status,
        format_timestamp(message.timestamp),
    ))
    return []

def _handle_key_lookup_reply(state, message_body):
    log = logging.getLogger("_handle_key_lookup_reply")
    message = DatabaseKeyLookupReply.unmarshall(message_body)

    try:
        retrieve_state = state.pop(message.request_id)
    except KeyError:
        # if we don't have any state for this message body, there's nobody we 
        # can complain too
        log.error("No state for %r" % (message.request_id, ))
        return []

    reply_exchange = retrieve_state.reply_exchange
    reply_routing_key = "".join(
        [retrieve_state.reply_routing_header, 
         ".", 
         RetrieveKeyStartReply.routing_tag]
    )

    # if we got a database error, pass it on 
    if message.error:
        log.error("%s %s database error: (%s) %s" % (
            retrieve_state.avatar_id,
            retrieve_state.key,
            message.result,
            message.error_message,
        ))
        reply = RetrieveKeyStartReply(
            message.request_id,
            RetrieveKeyStartReply.error_database,
            error_message = message.error_message
        )
        return [(reply_exchange, reply_routing_key, reply, )]      

    # if this key is a tombstone, treat as an error
    if message.database_content.is_tombstone:
        log.error("%s %s this record is a tombstone" % (
            retrieve_state.avatar_id,
            retrieve_state.key,
        ))
        reply = RetrieveKeyStartReply(
            message.request_id,
            RetrieveKeyStartReply.error_key_not_found,
            error_message = "is tombstone"
        )
        return [(reply_exchange, reply_routing_key, reply, )]      

    content_path = repository.content_path(
        retrieve_state.avatar_id, 
        message.database_content.file_name
    ) 
    segment_size = message.database_content.segment_size
    segment_count = message.database_content.segment_count

    try:
        with open(content_path, "r") as input_file:
            data_content = input_file.read(segment_size)
    except Exception, instance:
        log.exception("%s %s" % (
            retrieve_state.avatar_id,
            retrieve_state.key,
        ))
        reply = RetrieveKeyStartReply(
            message.request_id,
            RetrieveKeyStartReply.error_exception,
            error_message = str(instance)
        )
        return [(reply_exchange, reply_routing_key, reply, )]      

    # if we have more than one segment, we need to save the state
    # otherwise this request is done
    if segment_count > 1:
        state[message.request_id] = retrieve_state._replace(
            timeout=time.time()+_retrieve_timeout,
            sequence=0, 
            segment_size=segment_size,
            file_name=message.database_content.file_name
        )

    Statgrabber.accumulate('diy_read_requests', 1)
    Statgrabber.accumulate('diy_read_bytes', len(data_content))

    reply = RetrieveKeyStartReply(
        message.request_id,
        RetrieveKeyStartReply.successful,
        message.database_content.timestamp,
        message.database_content.is_tombstone,
        message.database_content.version_number,
        message.database_content.segment_number,
        message.database_content.segment_count,
        message.database_content.segment_size,
        message.database_content.total_size,
        message.database_content.file_adler32,
        message.database_content.file_md5,
        message.database_content.segment_adler32,
        message.database_content.segment_md5,
        data_content = data_content
    )

    return [(reply_exchange, reply_routing_key, reply, )]      

def _handle_low_traffic(_state, _message_body):
    log = logging.getLogger("_handle_low_traffic")
    log.debug("ignoring low traffic message")
    return None

_dispatch_table = {
    RetrieveKeyStart.routing_key    : _handle_retrieve_key_start,
    RetrieveKeyNext.routing_key     : _handle_retrieve_key_next,
    RetrieveKeyFinal.routing_key    : _handle_retrieve_key_final,
    ProcessStatus.routing_key       : _handle_process_status,
    _key_lookup_reply_routing_key   : _handle_key_lookup_reply,
    _low_traffic_routing_key        : _handle_low_traffic,
}

def _startup(halt_event, state):
    state["low_traffic_thread"] = LowTrafficThread(
        halt_event, _routing_header
    )
    state["low_traffic_thread"].start()

    message = ProcessStatus(
        time.time(),
        amqp_connection.local_exchange_name,
        _routing_header,
        ProcessStatus.status_startup
    )

    exchange = amqp_connection.broadcast_exchange_name
    routing_key = ProcessStatus.routing_key

    return [(exchange, routing_key, message, )]

def _is_retrieve_state((_, value, )):
    return value.__class__.__name__ == "RetrieveState"

def _check_message_timeout(state):
    """check request_ids who are waiting for a message"""
    log = logging.getLogger("_check_message_timeout")

    state["low_traffic_thread"].reset()

    # return a (possibly empty) list of messages to send
    return_list = list()

    current_time = time.time()
    for request_id, retrieve_state in filter(_is_retrieve_state, state.items()):
        if current_time > retrieve_state.timeout:
            log.warn(
                "%s timed out waiting message; running timeout function" % (
                    request_id
                )
            )
            return_list.extend(
                retrieve_state.timeout_function(request_id, state)
            )

    return return_list

def _shutdown(state):
    state["low_traffic_thread"].join()
    del state["low_traffic_thread"]

    pickleable_state = dict()
    for key, value in state:
        pickleable_state[key] = value._asdict()

    save_state(pickleable_state, _queue_name)

    message = ProcessStatus(
        time.time(),
        amqp_connection.local_exchange_name,
        _routing_header,
        ProcessStatus.status_shutdown
    )

    exchange = amqp_connection.broadcast_exchange_name
    routing_key = ProcessStatus.routing_key

    return [(exchange, routing_key, message, )]

if __name__ == "__main__":
    state = dict()
    pickleable_state = load_state(_queue_name)
    if pickleable_state is not None:
        for key, value in pickleable_state:
            state[key] = _retrieve_state_tuple(**value)

    sys.exit(
        process.main(
            _log_path, 
            _queue_name, 
            _routing_key_binding, 
            _dispatch_table, 
            state,
            pre_loop_function=_startup,
            in_loop_function=_check_message_timeout,
            post_loop_function=_shutdown
        )
    )

