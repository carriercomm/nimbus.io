# -*- coding: utf-8 -*-
"""
test_application.py

test diyapi_web_server/application.py
"""
import unittest
from webtest import TestApp

from unit_tests.util import random_string, generate_key
from unit_tests.web_server.test_amqp_archiver import (MockChannel,
                                                      FakeAMQPHandler)

from messages.archive_key_final_reply import ArchiveKeyFinalReply
from messages.database_listmatch_reply import DatabaseListMatchReply

from diyapi_web_server.application import Application


class TestApplication(unittest.TestCase):
    """test diyapi_web_server/application.py"""
    def setUp(self):
        self.channel = MockChannel()
        self.handler = FakeAMQPHandler()
        self.handler.channel = self.channel
        self.app = TestApp(Application(self.handler))
        self._key_generator = generate_key()

    def test_archive(self):
        self.handler._reply_to_send = ArchiveKeyFinalReply(
            'request_id (replaced by FakeAMQPHandler)',
            ArchiveKeyFinalReply.successful,
            0)
        content = random_string(64 * 1024)
        key = self._key_generator.next()
        resp = self.app.post('/archive/' + key, content)
        self.assertEqual(resp.body, 'OK')

    def test_listmatch(self):
        prefix = 'a_prefix'
        key_list = ['%s-%d' % (prefix, i) for i in xrange(10)]
        self.handler._reply_to_send = DatabaseListMatchReply(
            'request_id (replaced by FakeAMQPHandler)',
            DatabaseListMatchReply.successful,
            key_list=key_list)
        resp = self.app.get('/listmatch', dict(prefix=prefix))
        self.assertEqual(resp.body, repr(key_list))


if __name__ == "__main__":
    unittest.main()