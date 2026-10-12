"""Authenticated appearance preferences persist without changing branding."""
import sys
import tempfile
import sqlite3
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from app.core.preferences import Preferences
from app.core.appearance import appearance_router, appearance_settings


class AppearanceTests(unittest.TestCase):
    def test_auth_validation_and_persistence_with_existing_images(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'preferences.sqlite'
            def db(): return sqlite3.connect(path)
            connection = db()
            connection.execute('CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT)')
            connection.commit(); connection.close()
            preferences = Preferences(db)
            preferences.write('branding_logo', {'revision':'saved-logo'})
            def auth(request: Request):
                if request.headers.get('x-test-auth') != 'yes': raise HTTPException(401)
            app = FastAPI(); app.include_router(appearance_router(preferences,auth))
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/appearance').status_code,401)
                self.assertEqual(client.put('/api/appearance',json={'theme':'paper'}).status_code,401)
                client.headers['x-test-auth'] = 'yes'
                self.assertEqual(client.get('/api/appearance').json(), {'theme':'dark'})
                self.assertEqual(client.put('/api/appearance',json={'theme':'unknown'}).status_code,422)
                self.assertEqual(client.put('/api/appearance',json={'theme':'paper'}).json(), {'theme':'paper'})
                self.assertEqual(appearance_settings(Preferences(db)), {'theme':'paper'})
                self.assertEqual(preferences.read('branding_logo')['revision'],'saved-logo')
                self.assertEqual(client.put('/api/appearance',json={'theme':'dark'}).json(), {'theme':'dark'})


if __name__ == '__main__': unittest.main()
