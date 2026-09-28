from datetime import datetime, timezone
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1]))
from app.modules.logs.collector import classify, redact, parse_lines, collect_logs, query_logs, MAX_BYTES


class LogTests(unittest.TestCase):
    def test_structured_levels_override_error_words(self):
        self.assertEqual(classify('{"level":"info","msg":"error handler initialized"}'), ('info', 'structured'))
        self.assertEqual(classify('level=warn msg="retrying"'), ('warning', 'explicit'))
        self.assertEqual(classify('[ERROR] connection lost'), ('error', 'explicit'))
        self.assertEqual(classify('connection failed'), ('error', 'inferred'))
        self.assertEqual(classify('request timed out'), ('warning', 'inferred'))
        self.assertEqual(classify('0 errors, no warnings'), ('unknown', 'unknown'))
        self.assertEqual(classify('no error found'), ('unknown', 'unknown'))

    def test_redaction_and_traceback_context(self):
        raw = b'2026-09-18T12:00:00.123456789Z ERROR password=PRIVATE\n2026-09-18T12:00:01Z   at module.run()\nuntimestamped text'
        rows = parse_lines(raw, 'abc', 'service')
        self.assertEqual(rows[0]['level'], 'error')
        self.assertNotIn('PRIVATE', str(rows))
        self.assertEqual(rows[1]['detection'], 'continuation')
        self.assertEqual(rows[1]['level'], 'error')
        self.assertIsNone(rows[2]['timestamp'])
        for message in ['Authorization: Bearer PRIVATE', 'api_key=PRIVATE', '{"token":"PRIVATE"}', 'secret=PRIVATE']:
            self.assertNotIn('PRIVATE', redact(message))

    def test_filters_counts_limits_and_time(self):
        now = datetime.now(timezone.utc).isoformat()
        entries = parse_lines(f'{now} ERROR failed\n{now} INFO connected\n{now} WARN slow'.encode(), 'abc', 'service')
        entries += parse_lines(b'2020-01-01T00:00:00Z ERROR old', 'abc', 'service')
        snapshot = {'data': {'entries': entries, 'services': []}, 'loading': False, 'error': None}
        result = query_logs(snapshot, limit=1)
        self.assertEqual(result['matched'], 2)
        self.assertTrue(result['limited'])
        self.assertEqual(result['counts']['info'], 1)
        self.assertEqual(len(query_logs(snapshot, level='all')['entries']), 3)
        self.assertEqual(query_logs(snapshot, query='CONNECTED', level='all')['matched'], 1)
        self.assertEqual(query_logs(snapshot, service='other')['matched'], 0)

    def test_collection_isolates_unreadable_sources_and_closes_streams(self):
        client = Mock()
        client.api.containers.return_value = [{'Id': 'a', 'Names': ['/good']}, {'Id': 'b', 'Names': ['/bad']}]
        stamp = datetime.now(timezone.utc).isoformat()
        def logs(cid, **kwargs):
            self.assertFalse(kwargs['follow'])
            self.assertEqual(kwargs['tail'], 500)
            if cid == 'b':
                raise RuntimeError('SECRET upstream failure')
            return iter([f'{stamp} ERROR failed'.encode()])
        client.api.logs.side_effect = logs
        result = collect_logs(lambda: client)
        self.assertEqual(len(result['entries']), 1)
        self.assertEqual(sum(bool(s['error']) for s in result['services']), 1)
        self.assertNotIn('SECRET', str(result))
        client.close.assert_called_once()

    def test_byte_bound_discards_partial_line_and_stops_stream(self):
        client = Mock()
        client.api.containers.return_value = [{'Id': 'a', 'Names': ['/large']}]
        closed = []
        def stream():
            try:
                yield b'2026-09-18T12:00:00Z ERROR first\n' + b'x' * MAX_BYTES
                raise AssertionError('Read beyond byte bound')
            finally:
                closed.append(True)
        client.api.logs.return_value = stream()
        result = collect_logs(lambda: client)
        self.assertTrue(result['services'][0]['limited'])
        self.assertEqual(len(result['entries']), 1)
        self.assertTrue(closed)
