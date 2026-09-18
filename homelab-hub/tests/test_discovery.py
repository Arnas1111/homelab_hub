import io
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).parents[1]))
from app.core.snapshot import Snapshot
from app.modules.docker.discovery import metadata, service_url, load_inventory, safe_url
from app.modules.unraid.connector import read_unraid, NoRedirect


class SnapshotTests(unittest.TestCase):
    def settle(self, cache):
        deadline = time.monotonic() + 2
        while cache.loading and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(cache.loading)

    def test_slow_collector_does_not_block_requests_or_duplicate_work(self):
        release = threading.Event()
        loader = Mock(side_effect=lambda: (release.wait(2), {'value': 10})[1])
        cache = Snapshot(loader)
        try:
            start = time.monotonic()
            for _ in range(20):
                self.assertTrue(cache.read()['loading'])
            self.assertLess(time.monotonic() - start, .5)
        finally:
            release.set()
        self.settle(cache)
        loader.assert_called_once()
        first = cache.read()
        first['data']['value'] = 99
        self.assertEqual(cache.read()['data']['value'], 10)

    def test_failure_keeps_previous_result_and_redacts_exception(self):
        cache = Snapshot(Mock(side_effect=[{'value': 5}, RuntimeError('SECRET')]))
        cache.read()
        self.settle(cache)
        cache.invalidate()
        cache.read()
        self.settle(cache)
        result = cache.read()
        self.assertEqual(result['data'], {'value': 5})
        self.assertTrue(result['updated_at'])
        self.assertNotIn('SECRET', str(result))
        self.assertTrue(result['error'])

    def test_invalidated_inflight_result_cannot_restore_old_configuration(self):
        release = threading.Event()
        cache = Snapshot(lambda: (release.wait(2), 'old')[1])
        cache.read()
        cache.invalidate()
        release.set()
        self.settle(cache)
        self.assertIsNone(cache.data)
        cache.loader = lambda: 'new'
        cache.read()
        self.settle(cache)
        self.assertEqual(cache.read()['data'], 'new')


class DiscoveryTests(unittest.TestCase):
    def row(self):
        return {'Id': 'a' * 64, 'Names': ['/jellyfin'], 'Image': 'jellyfin/jellyfin',
                'State': 'running', 'Status': 'Up 1 hour (unhealthy)',
                'Ports': [{'PrivatePort': 8096, 'PublicPort': 18096, 'Type': 'tcp'}],
                'Labels': {'homepage.name': 'Cinema', 'homepage.group': 'Living room',
                           'net.unraid.docker.webui': 'http://[IP]:[PORT:8096]/',
                           'homepage.widget.key': 'SECRET'}}

    def test_labels_recognition_health_and_secret_allowlist(self):
        result = metadata(self.row())
        self.assertEqual(result['display_name'], 'Cinema')
        self.assertEqual(result['group_name'], 'Living room')
        self.assertEqual(result['integration'], 'jellyfin')
        self.assertEqual(result['health'], 'unhealthy')
        self.assertFalse(result['stats_available'])
        self.assertIsNone(result['cpu_percent'])
        self.assertNotIn('SECRET', str(result))

    def test_unraid_port_mapping_ipv6_and_unsafe_links(self):
        row = metadata(self.row())
        self.assertEqual(service_url(row['discovered_url'], row['ports'], 'tower'), 'http://tower:18096/')
        self.assertEqual(service_url(row['discovered_url'], row['ports'], '::1'), 'http://[::1]:18096/')
        self.assertEqual(service_url(row['discovered_url'], [], 'tower'), '')
        for url in ('javascript:alert(1)', 'https://user:secret@tower/', 'http://tower/\n', '//tower'):
            self.assertEqual(safe_url(url), '')

    def test_inventory_has_constant_api_call_count_and_closes_client(self):
        client = Mock()
        client.api.containers.return_value = [self.row()] * 100
        client.info.return_value = {'NCPU': 8, 'MemTotal': 1000}
        result = load_inventory(lambda: client)
        self.assertEqual(len(result['containers']), 100)
        client.api.containers.assert_called_once_with(all=True)
        client.info.assert_called_once()
        client.containers.list.assert_not_called()
        client.close.assert_called_once()


class UnraidTests(unittest.TestCase):
    def test_read_only_query_and_private_credentials(self):
        response = io.BytesIO(json.dumps({'data': {'info': {'cpu': {'brand': 'Test'}}, 'array': {'state': 'STARTED', 'capacity': {'kilobytes': {'free': '1024', 'used': '2048', 'total': '3072'}}}}}).encode())
        with patch('app.modules.unraid.connector.build_opener') as opener:
            opener.return_value.open.return_value = response
            result = read_unraid({'unraid_url': 'https://tower', 'unraid_api_key': 'SECRET'})
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://tower/graphql')
            self.assertEqual(request.get_header('X-api-key'), 'SECRET')
            self.assertNotIn('mutation', request.data.decode())
            self.assertEqual(result['array']['state'], 'STARTED')
            self.assertEqual(result['array']['capacity_bytes']['free'], 1048576)
            self.assertIn('kilobytes', request.data.decode())
            self.assertNotIn('SECRET', str(result))

    def test_redirects_cannot_forward_api_key(self):
        request = Request('https://tower/graphql', headers={'x-api-key': 'SECRET'})
        self.assertIsNone(NoRedirect().redirect_request(request, None, 302, '', {}, 'https://other.test'))

    def test_connection_error_is_redacted_and_unconfigured_does_not_connect(self):
        with patch('app.modules.unraid.connector.build_opener') as opener:
            self.assertFalse(read_unraid({})['configured'])
            opener.assert_not_called()
            opener.return_value.open.side_effect = RuntimeError('SECRET')
            self.assertNotIn('SECRET', str(read_unraid({'unraid_url': 'https://tower', 'unraid_api_key': 'SECRET'})))
