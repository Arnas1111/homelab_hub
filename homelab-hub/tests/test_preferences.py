import base64
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1]))
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from app.core.preferences import Preferences
from app.core.identity import Identity
from app.core.branding import branding_router
from app.modules.zigbee.connector import ZigbeeModule
from app.modules.zigbee.settings import ZigbeeConfiguration, ZigbeeSettings, settings_router


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.factory = lambda: sqlite3.connect(self.root / 'hub.db')
        conn = self.factory()
        conn.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        conn.close()
        self.store = Preferences(self.factory)
        self.module = ZigbeeModule({'HUB_MQTT_HOST': 'old-broker', 'HUB_MQTT_PASSWORD':'secret-env'})
        self.module.start = Mock()
        self.config = ZigbeeConfiguration(self.store, self.module)

    def tearDown(self):
        self.temp.cleanup()

    def test_password_preserve_replace_clear_and_restart_precedence(self):
        self.assertTrue(self.config.public()['password_set'])
        self.assertNotIn('secret-env', str(self.config.public()))
        self.module.devices['old'] = {}
        self.config.save(ZigbeeSettings(enabled=True, host='new-broker'))
        self.assertEqual(self.module.host, 'new-broker')
        self.assertEqual(self.module.password, 'secret-env')
        self.assertEqual(self.module.devices, {})
        self.module.start.assert_called_once()
        self.config.save(ZigbeeSettings(enabled=True, host='new-broker', password='replacement'))
        other = ZigbeeConfiguration(self.store, ZigbeeModule({'HUB_MQTT_HOST':'ignored'}))
        self.assertEqual(other.config().password, 'replacement')
        self.config.save(ZigbeeSettings(clear_password=True))
        self.assertFalse(self.config.public()['password_set'])
        self.assertEqual(self.module.host, '')

    def test_bad_environment_does_not_block_settings(self):
        bad = ZigbeeConfiguration(self.store, ZigbeeModule({'HUB_MQTT_HOST':'mqtt://bad', 'HUB_MQTT_PORT':'invalid'}))
        self.assertFalse(bad.public()['enabled'])
        bad.module.start = Mock()
        bad.save(ZigbeeSettings(host='fixed', enabled=True))
        self.assertEqual(bad.module.host, 'fixed')

    def test_identity_persistence_password_and_session_revision(self):
        identity = Identity(self.root)
        self.assertEqual(Identity(self.root).secret, identity.secret)
        self.assertFalse(identity.configured(''))
        identity.save('long password 123')
        version = identity.version()
        self.assertTrue(identity.verify('long password 123', 'env'))
        self.assertFalse(identity.verify('env', 'env'))
        self.assertNotIn('long password', identity.path.read_text())
        identity.save('another password 123')
        self.assertNotEqual(version, identity.version())

    def test_routes_auth_validation_and_branding(self):
        def auth(request: Request):
            if request.cookies.get('test') != 'yes':
                raise HTTPException(401)
        app = FastAPI()
        app.include_router(settings_router(self.config, auth))
        app.include_router(branding_router(self.store, auth, Path(__file__).parents[1] / 'app/static'))
        with TestClient(app) as client:
            for endpoint in ['/api/zigbee/settings', '/api/branding']:
                self.assertEqual(client.get(endpoint).status_code, 401)
            self.assertEqual(client.put('/api/zigbee/settings', json={}).status_code, 401)
            self.assertEqual(client.post('/api/zigbee/reconnect').status_code, 401)
            self.assertEqual(client.put('/api/branding/logo', content=b'bad').status_code, 401)
            self.assertEqual(client.delete('/api/branding/logo').status_code, 401)
            client.cookies.set('test', 'yes')
            self.assertEqual(client.put('/api/zigbee/settings', json={'enabled':True}).status_code, 422)
            self.assertEqual(client.put('/api/zigbee/settings', json={'host':'mqtt://broker'}).status_code, 422)
            self.assertEqual(client.put('/api/zigbee/settings', json={'base_topic':'bad/#'}).status_code, 422)
            response = client.put('/api/zigbee/settings', json={'enabled':True,'host':'broker','password':'PRIVATE'})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('PRIVATE', response.text)
            self.assertEqual(client.post('/api/zigbee/reconnect').status_code, 200)
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=')
            self.assertEqual(client.put('/api/branding/logo', content=png).status_code, 200)
            self.assertEqual(client.get('/branding/logo').content, png)
            self.assertEqual(client.get('/branding/favicon').headers['content-type'], 'image/svg+xml')
            self.assertEqual(client.put('/api/branding/logo', content=b'<svg/>').status_code, 422)
            self.assertEqual(client.put('/api/branding/logo', content=b'x' * 524289).status_code, 413)
            client.delete('/api/branding/logo')
            self.assertEqual(client.get('/branding/logo').headers['content-type'], 'image/svg+xml')
