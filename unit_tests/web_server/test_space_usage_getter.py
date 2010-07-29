# -*- coding: utf-8 -*-
"""
test_space_usage_getter.py

test diyapi_web_server/space_usage_getter.py
"""
import os
import unittest
import uuid

from unit_tests.web_server import util

from diyapi_web_server.amqp_data_reader import AMQPDataReader

from messages.space_usage import SpaceUsage
from messages.space_usage_reply import SpaceUsageReply

from diyapi_web_server.exceptions import (
    ListmatchFailedError,
)

from diyapi_web_server.space_usage_getter import SpaceUsageGetter


EXCHANGES = os.environ['DIY_NODE_EXCHANGES'].split()
AGREEMENT_LEVEL = 8


class TestSpaceUsageGetter(unittest.TestCase):
    """test diyapi_web_server/space_usage_getter.py"""
    def setUp(self):
        self.amqp_handler = util.FakeAMQPHandler()
        self.data_readers = [AMQPDataReader(self.amqp_handler, exchange)
                             for exchange in EXCHANGES]
        self.getter = SpaceUsageGetter(self.data_readers, AGREEMENT_LEVEL)
        self._real_uuid1 = uuid.uuid1
        uuid.uuid1 = util.fake_uuid_gen().next

    def tearDown(self):
        uuid.uuid1 = self._real_uuid1

    def test_get_space_usage(self):
        avatar_id = 1001
        prefix = 'a_prefix'
        key_list = ['%s-%d' % (prefix, i) for i in xrange(10)]
        messages = []
        for i, data_reader in enumerate(self.data_readers):
            request_id = uuid.UUID(int=i).hex
            message = SpaceUsage(
                request_id,
                avatar_id,
                self.amqp_handler.exchange,
                self.amqp_handler.queue_name
            )
            reply = SpaceUsageReply(
                request_id,
                SpaceUsageReply.successful
            )
            self.amqp_handler.replies_to_send_by_exchange[(
                request_id, data_reader.exchange
            )].put(reply)
            messages.append((message, data_reader.exchange))

        result = self.getter.get_space_usage(avatar_id, 0)

        self.assertEqual(result, None)

        expected = [
            (message.marshall(), exchange)
            for message, exchange in messages
        ]
        actual = [
            (message.marshall(), exchange)
            for message, exchange in self.amqp_handler.messages
        ]
        self.assertEqual(
            actual, expected)


if __name__ == "__main__":
    from diyapi_tools.standard_logging import initialize_logging
    _log_path = "/var/log/pandora/test_web_server.log"
    initialize_logging(_log_path)
    unittest.main()
