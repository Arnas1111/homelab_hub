"""Authenticated route checks using a disposable appdata directory."""
import importlib
import os
from pathlib import Path
from re import findall
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

    def test_first_run_setup_and_password_change_revoke_old_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            identity = self.main.Identity(Path(directory))
            with patch.object(self.main, 'identity', identity), patch.object(self.main, 'ADMIN_PASSWORD', ''):
                page = self.client.get('/login')
                self.assertIn('Create administrator', page.text)
                self.assertEqual(self.client.post('/setup', data={'password':'short','confirm_password':'short'}, follow_redirects=False).status_code, 303)
                self.assertFalse(identity.configured(''))
                self.client.post('/setup', data={'password':'initial password','confirm_password':'initial password'}, follow_redirects=False)
                self.assertEqual(self.client.get('/api/settings').status_code, 200)
                self.assertEqual(self.client.post('/setup', data={'password':'other password','confirm_password':'other password'}).status_code, 409)
                old_token = self.client.cookies.get('hub_session')
                result = self.client.put('/api/account/password', json={'current_password':'initial password','new_password':'changed password'})
                self.assertEqual(result.status_code, 200)
                self.client.cookies.set('hub_session', old_token)
                self.assertEqual(self.client.get('/api/settings').status_code, 401)
                self.client.cookies.clear()
                self.client.post('/login', data={'password':'changed password'}, follow_redirects=False)
                self.assertEqual(self.client.get('/api/settings').status_code, 200)

    def test_board_and_unraid_require_authentication(self):
        self.assertEqual(self.client.put('/api/board', json={'favorites': []}).status_code, 401)
        self.assertEqual(self.client.get('/api/unraid').status_code, 401)
        self.assertEqual(self.client.get('/api/logs').status_code, 401)

    def test_section_links_and_login_return_path(self):
        for page in self.main.PAGES:
            result = self.client.get('/' + page, follow_redirects=False)
            self.assertEqual(result.status_code, 303)
            self.assertIn('next=', result.headers['location'])
        result = self.client.post('/login', data={'password':'test-only-password', 'next':'/automations'}, follow_redirects=False)
        self.assertEqual(result.headers['location'], '/automations')
        for page in self.main.PAGES:
            self.assertEqual(self.client.get('/' + page).status_code, 200)
        html = self.client.get('/home')
        self.assertEqual(html.headers['cache-control'], 'no-cache')
        assets = findall(r'(?:src|href)="(/static/[^\"]+)"', html.text)
        self.assertTrue(assets)
        for asset in assets:
            self.assertTrue(asset.endswith('?v=' + self.main.ASSET_VERSION), asset)
            self.assertEqual(self.client.get(asset).status_code, 200)
        result = self.client.post('/login', data={'password':'test-only-password', 'next':'//evil.invalid'}, follow_redirects=False)
        self.assertEqual(result.headers['location'], '/')
        self.assertEqual(self.client.get('/unknown-page').status_code, 404)

    def test_v1_object_routes_use_existing_login(self):
        for path in ['/api/v1/modules', '/api/v1/objects', '/api/v1/objects/zigbee.unknown']:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post('/api/v1/objects/zigbee.unknown/actions',
                                         json={'action': 'set_power', 'value': True}).status_code, 401)
        self.login()
        self.assertEqual(self.client.get('/api/v1/modules').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/objects').status_code, 200)

    def test_log_filters_are_validated_and_collection_is_cached(self):
        self.login()
        self.assertEqual(self.client.get('/api/logs?minutes=999999').status_code, 422)
        self.assertEqual(self.client.get('/api/logs?level=invalid').status_code, 422)
        with patch.object(self.main.logs_cache, 'read', return_value={'data': None, 'loading': True, 'error': None}):
            response = self.client.get('/api/logs')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['loading'])
            self.assertEqual(response.json()['entries'], [])

    def test_home_overview_uses_cached_inventory_without_resource_sampling(self):
        self.login()
        self.client.put('/api/board', json={'favorites': ['container:cinema', 'container:cinema']})
        snapshot = {'data': {'server': {'cpus': 4}, 'containers': []}, 'loading': False, 'error': None, 'updated_at': '2026-09-18T12:00:00Z'}
        with patch.object(self.main.inventory_cache, 'read', return_value=snapshot), patch.object(self.main.resource_cache, 'read') as stats:
            response = self.client.get('/api/overview?include_metrics=false')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['board']['favorites'], ['container:cinema'])
            self.assertEqual(response.json()['server']['cpus'], 4)
            stats.assert_not_called()

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
