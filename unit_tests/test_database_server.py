# -*- coding: utf-8 -*-
"""
test_database_server.py

test database_server
"""
import logging
import os
import os.path
import shutil
import time
import unittest
import uuid

from tools.standard_logging import initialize_logging
from diyapi_database_server import database_content
from messages.database_key_insert import DatabaseKeyInsert
from messages.database_key_insert_reply import DatabaseKeyInsertReply
from messages.database_key_lookup import DatabaseKeyLookup
from messages.database_key_lookup_reply import DatabaseKeyLookupReply

from unit_tests.util import generate_key, generate_database_content

_log_path = "/var/log/pandora/test_database_server.log"
_test_dir = os.path.join("/tmp", "test_database_server")
_repository_path = os.path.join(_test_dir, "repository")

os.environ["PANDORA_REPOSITORY_PATH"] = _repository_path
from diyapi_database_server.diyapi_database_server_main import \
        _database_cache, _handle_key_insert, _handle_key_lookup

class TestDatabaseServer(unittest.TestCase):
    """test message handling in database server"""

    def setUp(self):
        self.tearDown()
        os.makedirs(_repository_path)
        initialize_logging(_log_path)
        self._key_generator = generate_key()

    def tearDown(self):
        if os.path.exists(_test_dir):
            shutil.rmtree(_test_dir)

    def _insert_key(self, avatar_id, key, content):
        request_id = uuid.uuid1().hex
        exchange = "reply-exchange"
        routing_key = "reply.routing-key"
        message = DatabaseKeyInsert(
            request_id,
            avatar_id,
            exchange,
            routing_key,
            key, 
            content
        )
        marshalled_message = message.marshall()

        state = {_database_cache : dict()}
        replies = _handle_key_insert(state, marshalled_message)
        self.assertEqual(len(replies), 1)
        [(reply_exchange, reply_routing_key, reply, ), ] = replies
        self.assertEqual(reply_exchange, exchange)
        self.assertEqual(reply_routing_key, routing_key)
        self.assertEqual(reply.request_id, request_id)

        return reply

    def _lookup_key(self, avatar_id, key):
        request_id = uuid.uuid1().hex
        exchange = "reply-exchange"
        routing_key = "reply.routing-key"
        message = DatabaseKeyLookup(
            request_id,
            avatar_id,
            exchange,
            routing_key,
            key 
        )
        marshalled_message = message.marshall()

        state = {_database_cache : dict()}
        replies = _handle_key_lookup(state, marshalled_message)
        self.assertEqual(len(replies), 1)
        [(reply_exchange, reply_routing_key, reply, ), ] = replies
        self.assertEqual(reply_exchange, exchange)
        self.assertEqual(reply_routing_key, routing_key)
        self.assertEqual(reply.request_id, request_id)

        return reply

    def test_valid_key_insert(self):
        """test inserting data for a valid key"""
        avatar_id = 1001
        key  = self._key_generator.next()
        content = generate_database_content()

        reply = self._insert_key(avatar_id, key, content)

        self.assertEqual(reply.result, 0)
        self.assertEqual(reply.previous_size, 0)

    def test_key_insert_over_existing_key(self):
        """test inserting data for a valid key over some exsting data"""
        avatar_id = 1001
        key  = self._key_generator.next()
        content = generate_database_content()
        original_size = content.total_size

        reply = self._insert_key(avatar_id, key, content)

        self.assertEqual(reply.result, 0)
        self.assertEqual(reply.previous_size, 0)

        new_content = content._replace(total_size=content.total_size+42)

        reply = self._insert_key(avatar_id, key, new_content)

        self.assertEqual(reply.result, 0)
        self.assertEqual(reply.previous_size, original_size)

    def test_key_insert_over_newer_existing_key(self):
        """
        test error condition where data timestamp is older than existing data
        """
        avatar_id = 1001
        key  = self._key_generator.next()
        content = generate_database_content()

        reply = self._insert_key(avatar_id, key, content)

        self.assertEqual(reply.result, 0)
        self.assertEqual(reply.previous_size, 0)

        new_content = content._replace(timestamp=content.timestamp-1.0)

        reply = self._insert_key(avatar_id, key, new_content)

        self.assertEqual(
            reply.result, DatabaseKeyInsertReply.error_invalid_duplicate
        )

    def test_valid_key_lookup(self):
        """test retrieving data for a valid key"""
        avatar_id = 1001
        key  = self._key_generator.next()
        content = generate_database_content()

        reply = self._insert_key(avatar_id, key, content)

        self.assertEqual(reply.result, 0)
        self.assertEqual(reply.previous_size, 0)

        reply = self._lookup_key(avatar_id, key)

        self.assertEqual(reply.result, 0)
        self.assertTrue(reply.key_found)
        self.assertEqual(reply.database_content, content)

if __name__ == "__main__":
    unittest.main()
