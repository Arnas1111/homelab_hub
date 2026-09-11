"""Authenticated route checks using a disposable appdata directory."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class HistoryAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {'HUB_DATA_DIR': cls.temp.name, 'HUB_ADMIN_PASSWORD': 'test-only-password'})
        cls.env.start()
        if sys.platform == 'win32':
            sys.modules.setdefault('pwd', types.ModuleType('pwd'))
        sys.path.insert(0, str(Path(__file__).parents[1]))
        cls.main = importlib.import_module('app.main')
        cls.main.init_db()
        cls.main.metrics_history.initialize()
        cls.client = TestClient(cls.main.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.env.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.client.cookies.clear()

    def login(self):
        self.client.cookies.set('hub_session', self.main.signer.dumps({'authenticated': True}))

    def test_all_history_routes_require_authentication(self):
        for method, endpoint, kwargs in [('get', '/api/metrics/settings', {}), ('get', '/api/metrics/history', {}),
                                         ('put', '/api/metrics/settings', {'json': {}}), ('post', '/api/metrics/test', {'json': {}})]:
            self.assertEqual(getattr(self.client, method)(endpoint, **kwargs).status_code, 401)

    def test_invalid_password_not_echoed_and_query_validation(self):
        self.login()
        secret = 'PRIVATE' * 400
        result = self.client.put('/api/metrics/settings', json={'password': secret})
        self.assertEqual(result.status_code, 422)
        self.assertNotIn('PRIVATE', result.text)
        self.assertEqual(self.client.get('/api/metrics/history?metric=unknown').status_code, 422)
        self.assertEqual(self.client.get('/api/metrics/history?container_id=bad%27value').status_code, 422)

    def test_saved_password_not_returned_and_connection_error_redacted(self):
        self.login()
        result = self.client.put('/api/metrics/settings', json={'host': 'postgres', 'password': 'PRIVATE'})
        self.assertEqual(result.status_code, 200)
        self.assertNotIn('PRIVATE', result.text)
        self.assertNotIn('password', result.json())
        with patch.object(self.main.metrics_history, 'history', side_effect=RuntimeError('PRIVATE')):
            result = self.client.get('/api/metrics/history')
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('PRIVATE', result.text)
