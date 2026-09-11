from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from app.modules.metrics.history import HistorySettings, HistoryStore, safe_error
from app.modules.metrics.sampler import HistorySampler
import psycopg
from pydantic import ValidationError


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'settings.db'
        self.store = HistoryStore(lambda: sqlite3.connect(self.path), Mock(return_value={'cpu_percent': 5}))
        self.store.initialize()

    def test_secret_preserve_replace_clear_and_public_redaction(self):
        self.store.save(HistorySettings(host='postgres', password='first-secret'))
        self.store.save(HistorySettings(host='postgres'))
        self.assertEqual(self.store.config()[0].password, 'first-secret')
        self.assertNotIn('password', self.store.public())
        self.assertTrue(self.store.public()['password_set'])
        self.assertNotIn('first-secret', str(self.store.public()))
        self.store.save(HistorySettings(host='postgres', password='replacement'))
        self.assertEqual(self.store.config()[0].password, 'replacement')
        self.store.save(HistorySettings(host='postgres', clear_password=True))
        self.assertFalse(self.store.public()['password_set'])

    def test_configuration_persists_source_identity(self):
        identity = self.store.config()[1]
        self.store.initialize()
        self.assertEqual(self.store.config()[1], identity)

    def test_connection_test_does_not_save_proposed_settings(self):
        before = self.store.config()
        self.store.connect = Mock(side_effect=psycopg.OperationalError('secret credentials'))
        with self.assertRaises(psycopg.OperationalError):
            self.store.test(HistorySettings(host='other-host', password='test-password'))
        self.assertEqual(self.store.config(), before)
        self.assertNotIn('secret', safe_error(psycopg.OperationalError('secret credentials')))

    def test_validation_bounds(self):
        for fields in ({'sample_seconds': 0}, {'retention_days': 366}, {'port': 65536}, {'host': 'a,b'}, {'enabled': True}):
            with self.assertRaises(ValidationError):
                HistorySettings(**fields)

    def test_disabled_collection_does_not_touch_postgres_or_collector(self):
        self.store.connect = Mock(side_effect=AssertionError())
        self.store.collect_once()
        self.store.connect.assert_not_called()
        self.store.collector.assert_not_called()

    def test_background_collection_without_browser_and_recovery(self):
        self.store.save(HistorySettings(enabled=True, host='postgres'))
        self.store.write = Mock(side_effect=[psycopg.OperationalError('secret'), None])
        self.store.start()
        self.addCleanup(self.store.stop)
        deadline = time.monotonic() + 3
        while not self.store.public()['status']['error'] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIsNotNone(self.store.public()['status']['error'])
        self.store.wake.set()
        while not self.store.public()['status']['last_saved'] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIsNotNone(self.store.public()['status']['last_saved'])
        self.assertIsNone(self.store.public()['status']['error'])
        self.store.stop()
        self.assertFalse(self.store.thread.is_alive())


class SamplerTests(unittest.TestCase):
    def test_independent_cpu_samples_and_missing_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sampler = HistorySampler(root, Mock(side_effect=RuntimeError('Docker down')), Mock(), root)
            (root / 'stat').write_text('cpu 100 0 0 100 0 0 0 0 50 0\ncpu0 100 0 0 100 0 0 0 0 50 0\n')
            self.assertIsNone(sampler.cpu()['cpu'])
            (root / 'stat').write_text('cpu 150 0 0 150 0 0 0 0 75 0\ncpu0 150 0 0 150 0 0 0 0 75 0\n')
            self.assertEqual(sampler.cpu()['cpu'], 50)
            data = sampler.sample(True)
            self.assertIsNone(data['memory_percent'])
            self.assertIsNone(data['rx_rate'])
            self.assertIsNone(data['container_cpu'])
            self.assertGreater(data['storage_total'], 0)


@unittest.skipUnless(os.getenv('HUB_TEST_PG_HOST'), 'PostgreSQL integration server not configured')
class PostgreSQLTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name) / 'config.db'
        self.store = HistoryStore(lambda: sqlite3.connect(path), Mock(return_value={'cpu_percent': 10}))
        self.store.initialize()
        self.cfg = HistorySettings(enabled=True, host=os.environ['HUB_TEST_PG_HOST'],
                                   port=int(os.getenv('HUB_TEST_PG_PORT', '5432')), database='homelab_test',
                                   username='homelab_test', password=os.getenv('HUB_TEST_PG_PASSWORD', ''), retention_days=1)
        self.store.save(self.cfg)
        self.source = self.store.config()[1]
        self.addCleanup(self.clean_samples)

    def clean_samples(self):
        with self.store.connect(self.cfg) as conn:
            conn.execute('DELETE FROM homelab_hub.samples WHERE source_id=%s', (self.source,))

    def test_postgresql18_migration_write_history_and_retention(self):
        self.assertEqual(self.store.test(self.cfg)['server_version'] // 10000, 18)
        now = datetime.now(timezone.utc)
        self.store.write(self.cfg, self.source, {'cpu_percent': 4}, now - timedelta(days=2))
        self.store.last_prune = 0
        self.store.write(self.cfg, self.source, {'cpu_percent': 20, 'memory_percent': 40, 'memory_used': 1000, 'memory_available': 1500,
                         'storage_percent': 60, 'storage_free': 10000, 'rx_rate': 40, 'tx_rate': 20,
                         'container_cpu': 200, 'container_memory': 1000,
                         'containers': [{'id': 'abc123', 'name': 'test', 'cpu_percent': 200, 'memory_used': 1000}]}, now)
        for metric in ('cpu', 'memory', 'storage', 'network', 'containers'):
            result = self.store.history(metric, '1h')
            self.assertTrue(result['points'])
            self.assertEqual(result['latest']['payload']['cpu_percent'], 20)
            self.assertLessEqual(len(result['points']), 361)
        chosen = self.store.history('containers', '1h', 'abc123')
        self.assertEqual(chosen['points'][0]['container_cpu'], 200)
        self.assertEqual(chosen['points'][0]['container_cpu_count'], 1)
        self.assertEqual(chosen['containers'][0]['name'], 'test')
        with self.store.connect(self.cfg) as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM homelab_hub.samples WHERE source_id=%s', (self.source,)).fetchone()['n'], 1)
        self.store.save(self.cfg.model_copy(update={'enabled': False}))
        self.assertFalse(self.store.history('cpu', '1h')['enabled'])
        self.assertTrue(self.store.history('cpu', '1h')['points'])

    def test_source_isolation_null_samples_and_averaging(self):
        now = datetime.now(timezone.utc)
        self.store.write(self.cfg, self.source, {'cpu_percent': None}, now - timedelta(seconds=2))
        self.store.write(self.cfg, self.source, {'cpu_percent': 10}, now - timedelta(seconds=1))
        self.store.write(self.cfg, self.source, {'cpu_percent': 30}, now)
        other = '00000000-0000-0000-0000-000000000001'
        self.store.write(self.cfg, other, {'cpu_percent': 100}, now)
        try:
            points = self.store.history('cpu', '1h')['points']
            count = sum(p['cpu_percent_count'] for p in points)
            average = sum((p['cpu_percent'] or 0) * p['cpu_percent_count'] for p in points) / count
            self.assertEqual(count, 2)
            self.assertEqual(average, 20)
        finally:
            with self.store.connect(self.cfg) as conn:
                conn.execute('DELETE FROM homelab_hub.samples WHERE source_id=%s', (other,))


if __name__ == '__main__':
    unittest.main()
