"""Private, persistent configuration for the independent control center."""
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'control.sqlite'
        self.lock = threading.RLock()
        self.sessions = {}
        with closing(self.connect()) as conn, conn:
            conn.execute('CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def read(self, key, default=None):
        with self.lock, closing(self.connect()) as conn:
            row = conn.execute('SELECT value FROM preferences WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def write(self, key, value):
        with self.lock, closing(self.connect()) as conn, conn:
            conn.execute('INSERT INTO preferences VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                         (key, json.dumps(value)))

    def password(self, value):
        salt = secrets.token_bytes(24)
        digest = hashlib.pbkdf2_hmac('sha256', value.encode(), salt, 600000)
        with self.lock:
            self.write('identity', {'salt':salt.hex(), 'digest':digest.hex()})
            self.sessions.clear()

    def verify(self, value):
        identity = self.read('identity')
        if not identity:
            return False
        digest = hashlib.pbkdf2_hmac('sha256', value.encode(), bytes.fromhex(identity['salt']), 600000)
        return hmac.compare_digest(digest.hex(), identity['digest'])

    def session(self):
        token = secrets.token_urlsafe(48)
        with self.lock:
            self.sessions = {k:v for k,v in self.sessions.items() if v > time.time()}
            self.sessions[hashlib.sha256(token.encode()).hexdigest()] = time.time() + 43200
        return token

    def authenticated(self, token):
        with self.lock:
            return self.sessions.get(hashlib.sha256(token.encode()).hexdigest(), 0) > time.time()

    def logout(self, token):
        with self.lock:
            self.sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)
