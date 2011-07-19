# -*- coding: utf-8 -*-
"""
stat_requestor.py

request stat on a file
"""
import os.path
import logging

from sample_code.diy_client.http_util import compute_uri
from sample_code.diy_client.http_connection import HTTPConnection, \
        HTTPRequestError

def request_stat(config, message, _body, send_queue):
    """
    request stat
    """
    log = logging.getLogger("request_stat")

    status_message = {
        "message-type"  : message["client-topic"],
        "status"        : None,
        "error-message" : None,
        "stat-result"   : None,
        "completed"     : True,        
    }

    connection = HTTPConnection(
        config["BaseAddress"],
        config["Username"], 
        config["AuthKey"],
        config["AuthKeyId"]
    )

    method = "GET"
    uri = compute_uri(message["key"], action="stat")

    try:
        response = connection.request(method, uri)
    except HTTPRequestError, instance:
        status_message["status"] = "error"
        status_message["error-message"] = str(instance)
        connection.close()
        send_queue.put((status_message, None, ))
        return
    else:
        data = response.read()
    finally:
        connection.close()

    status_message["status"] = "OK"
    status_message["stat-result"] = data
    log.info("space usage successful %s" % (data, ))
    send_queue.put((status_message, None, ))
        
