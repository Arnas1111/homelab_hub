"""Persistent module preferences. Environment variables seed unsaved modules only."""
import json
from contextlib import closing


class Preferences:
    def __init__(self, db):
        self.db = db

    def read(self, key, default=None):
        with closing(self.db()) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def write(self, key, value):
        with closing(self.db()) as conn, conn:
            conn.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, json.dumps(value)))
