# -*- coding: utf-8 -*-
"""
amqp_handler.py

Handles AMQP messages.
"""
import errno
import logging
from weakref import WeakValueDictionary
from socket import error as socket_error

import gevent
from gevent.queue import Queue

import amqplib.client_0_8 as amqp

from tools import amqp_connection
from tools.message_driven_process import _create_bindings

from messages.archive_key_final_reply import ArchiveKeyFinalReply


_queue_name = 'web_server'
_routing_key_binding = 'web_server.*'
_key_header = 'web_server.'

MESSAGE_TYPES = {
    _key_header + ArchiveKeyFinalReply.routing_tag: ArchiveKeyFinalReply,
}


class AMQPHandler(object):
    def __init__(self):
        self._chan_wait = None
        self.log = logging.getLogger('AMQPHandler')

        self.queue_name = _queue_name
        self.exchange = amqp_connection.local_exchange_name
        self.routing_key_binding = _routing_key_binding
        self.reply_queues = WeakValueDictionary()

    def send_message(self, message):
        try:
            assert message.request_id not in self.reply_queues
            reply_queue = self.reply_queues[message.request_id] = Queue()
        except AttributeError:
            reply_queue = None

        self.channel.basic_publish(
            amqp.Message(message.marshall()),
            exchange=self.exchange,
            routing_key=message.routing_key,
            mandatory=True
        )

        return reply_queue

    def _callback(self, amqp_message):
        routing_key = amqp_message.delivery_info['routing_key']
        try:
            message_type = MESSAGE_TYPES[routing_key]
        except KeyError:
            self.log.debug('skipping unknown routing key %r' % (routing_key,))
            return
        message = message_type.unmarshall(amqp_message.body)
        try:
            self.reply_queues[message.request_id].put(message)
        except AttributeError:
            pass
        except KeyError:
            self.log.debug('got a reply for %r '
                           'but no one cares' % (message.request_id,))

    def _run(self):
        self.log.debug('start AMQP loop')
        try:
            while True:
                try:
                    self.channel.wait()
                except (KeyboardInterrupt, SystemExit):
                    self.log.info('KeyboardInterrupt or SystemExit')
                    return
                except socket_error, instance:
                    if instance.errno == errno.EINTR:
                        self.log.warn(
                            'Interrupted system call: '
                            'assuming SIGTERM %s' % (instance,))
                        return
                    else:
                        raise
        except gevent.GreenletExit:
            self.log.info('GreenletExit')
        self.log.debug('end AMQP loop')

        self.channel.basic_cancel(self.amqp_tag)
        self.channel.close()
        self.connection.close()

    def start(self):
        self.connection = amqp_connection.open_connection()
        self.channel = self.connection.channel()
        amqp_connection.create_exchange(self.channel)
        _create_bindings(self.channel, self.queue_name,
                         self.routing_key_binding)

        # Let AMQP know to send us messages
        self.amqp_tag = self.channel.basic_consume(
            queue=self.queue_name,
            no_ack=True,
            callback=self._callback
        )

        self._chan_wait = gevent.spawn(self._run)

    def stop(self):
        if self._chan_wait:
            chan_wait = self._chan_wait
            self._chan_wait = None
            chan_wait.kill(block=True)