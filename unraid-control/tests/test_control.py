import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('CONTROL_DATA', str(Path(tempfile.gettempdir()) / 'unraid-control-test-bootstrap'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from control.main import create_app
from control.unraid import ACTIONS, ApiError, Unraid


def reference(name, kind='SCALAR'):
    return {'name':name, 'kind':kind, 'ofType':None}


def field(name, target='String', kind='SCALAR', args=None):
    return {'name':name, 'type':reference(target,kind), 'args':args or []}


def schema():
    types = [
        {'name':'Query', 'fields':[field('array','UnraidArray','OBJECT'), field('docker','Docker','OBJECT')]},
        {'name':'UnraidArray', 'fields':[field('state'),field('disks','ArrayDisk','OBJECT')]},
        {'name':'ArrayDisk', 'fields':[field('id'),field('name'),field('size','BigInt')]},
        {'name':'Docker','fields':[field('containers','DockerContainer','OBJECT')]},
        {'name':'DockerContainer','fields':[field('id'),field('names'),field('state')]},
        {'name':'Mutation', 'fields':[field('docker','DockerMutations','OBJECT'),field('array','ArrayMutations','OBJECT')]},
        {'name':'DockerMutations','fields':[field('start','DockerContainer','OBJECT'), field('stop','DockerContainer','OBJECT')]},
        {'name':'ArrayMutations','fields':[field('setState','UnraidArray','OBJECT')]},
    ]
    return {'queryType':{'name':'Query'},'mutationType':{'name':'Mutation'},'types':types}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.adapter = Unraid(lambda:{'enabled':True,'url':'https://example.test','api_key':'private-token'})
        self.adapter.request = Mock(side_effect=lambda query, variables=None:{'__schema':schema()} if '__schema' in query else {'array':{'state':'STARTED','disks':[]}})

    def test_old_schema_omits_unsupported_fields_and_actions(self):
        reading = self.adapter.read('storage')
        self.assertIsNone(reading['error'])
        query = self.adapter.request.call_args.args[0]
        self.assertIn('state',query)
        self.assertNotIn('capacity',query)
        self.assertNotIn('fsSize',query)
        self.assertEqual(set(self.adapter.capabilities()), {'docker.start','docker.stop','array.start','array.stop'})

    def test_cache_single_flight_and_separate_failure(self):
        workers = [threading.Thread(target=lambda:self.adapter.read('storage')) for _ in range(8)]
        for worker in workers: worker.start()
        for worker in workers: worker.join()
        self.assertEqual(self.adapter.request.call_count,2)
        unsupported = self.adapter.read('vms')
        self.assertIsNotNone(unsupported['error'])
        self.assertIsNotNone(self.adapter.read('storage')['data'])

    def test_failure_retains_stale_reading_and_reset_drops_it(self):
        self.adapter.read('storage')
        self.adapter.request.side_effect = ApiError('Offline')
        failed = self.adapter.read('storage',fresh=True)
        self.assertTrue(failed['stale'])
        self.assertEqual(failed['data']['state'],'STARTED')
        self.adapter.reset()
        self.assertIsNone(self.adapter.read('storage')['data'])

    def test_connection_change_during_read_does_not_leak_old_reading(self):
        self.adapter.read('storage')
        def reset(query, variables=None):
            self.adapter.reset()
            raise ApiError('Connection changed')
        self.adapter.request.side_effect = reset
        result = self.adapter.read('storage',fresh=True)
        self.assertIsNone(result['data'])
        self.assertFalse(result['stale'])

    def test_mutation_contract_and_no_arbitrary_action(self):
        self.adapter.act('array.start')
        self.assertIn('desiredState: START}',self.adapter.request.call_args.args[0])
        self.adapter.act('docker.start','docker:target')
        self.assertEqual(self.adapter.request.call_args.args[1],{'id':'docker:target'})
        with self.assertRaises(ApiError): self.adapter.act('vm.reset','vm:target')
        with self.assertRaises(ApiError): self.adapter.act('docker.start')

    def test_http_errors_and_credentials_are_contained(self):
        import httpx
        config = {'enabled':True,'url':'https://example.test','api_key':'private-token'}
        adapter = Unraid(lambda:config)
        original = httpx.Client
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200,json={'errors':[{'message':'private-token raw server details'}]})
        with patch('control.unraid.httpx.Client', side_effect=lambda **kwargs:original(transport=httpx.MockTransport(respond),**kwargs)):
            with self.assertRaises(ApiError) as failure: adapter.request('query { test }')
        self.assertNotIn('private-token',str(failure.exception))
        self.assertEqual(calls[0].headers['x-api-key'],'private-token')


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = create_app(self.directory.name)
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.api = self.app.state.unraid

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def setup_admin(self):
        self.assertEqual(self.client.post('/api/setup',json={'password':'local-admin-pass'}).status_code,200)

    def test_initial_setup_and_session_authentication(self):
        self.assertTrue(self.client.get('/api/access').json()['setup'])
        self.assertEqual(self.client.get('/api/settings').status_code,401)
        self.setup_admin()
        self.assertEqual(self.client.post('/api/setup',json={'password':'replacement-pass'}).status_code,409)
        self.assertTrue(self.client.get('/api/access').json()['authenticated'])
        self.client.post('/api/logout')
        self.assertEqual(self.client.get('/api/settings').status_code,401)
        self.assertEqual(self.client.post('/api/login',json={'password':'wrong-pass'}).status_code,401)
        self.assertEqual(self.client.post('/api/login',json={'password':'local-admin-pass'}).status_code,200)

    def test_secret_preservation_clear_validation_and_local_login_toggle(self):
        self.setup_admin()
        config = {'url':'https://example.test','api_key':'secret-value'}
        response = self.client.put('/api/settings',json=config)
        self.assertEqual(response.status_code,200)
        self.assertNotIn('secret-value',response.text)
        self.client.put('/api/settings',json={'url':'https://example.test','api_key':''})
        self.assertEqual(self.store.read('connection')['api_key'],'secret-value')
        self.client.put('/api/settings',json={'clear_api_key':True})
        self.assertFalse(self.store.read('connection')['api_key'])
        for url in ['javascript:alert(1)','https://user:secret@example.test','https://example.test:invalid']:
            self.assertEqual(self.client.put('/api/settings',json={'url':url}).status_code,422)
        self.client.put('/api/settings',json={'login_required':False})
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/settings').status_code,200)
        self.client.put('/api/settings',json={'login_required':True})
        self.assertEqual(self.client.get('/api/settings').status_code,401)

    def test_cross_origin_setup_is_rejected(self):
        response = self.client.post('/api/setup',json={'password':'local-admin-pass'},headers={'Origin':'https://other.test'})
        self.assertEqual(response.status_code,403)
        self.assertIsNone(self.store.read('identity'))

    def test_confirmation_controls_replay_expiry_and_audit(self):
        self.setup_admin()
        self.api.capabilities = Mock(return_value=['docker.start'])
        self.api.act = Mock()
        action = {'operation':'docker.start','target':'docker:one'}
        self.assertEqual(self.client.post('/api/actions/prepare',json=action).status_code,403)
        self.store.write('connection',{'controls_enabled':True})
        ticket = self.client.post('/api/actions/prepare',json=action).json()
        body = {'token':ticket['token'],'confirmation':'docker.start'}
        self.assertEqual(self.client.post('/api/actions/execute',json=body).status_code,200)
        self.assertEqual(self.client.post('/api/actions/execute',json=body).status_code,409)
        self.api.act.assert_called_once_with('docker.start','docker:one')
        self.assertEqual(len(self.client.get('/api/audit').json()['events']),1)
        ticket = self.client.post('/api/actions/prepare',json=action).json()
        with patch('control.main.time.time',return_value=time.time()+61):
            self.assertEqual(self.client.post('/api/actions/execute',json={'token':ticket['token'],'confirmation':'docker.start'}).status_code,409)
        self.assertEqual(self.api.act.call_count,1)

    def test_pending_confirmation_invalidated_on_connection_change(self):
        self.setup_admin()
        self.api.capabilities = Mock(return_value=['docker.start'])
        self.store.write('connection',{'controls_enabled':True})
        ticket = self.client.post('/api/actions/prepare',json={'operation':'docker.start','target':'docker:one'}).json()
        self.client.put('/api/settings',json={'url':'https://new-server.test','controls_enabled':True})
        self.assertEqual(self.client.post('/api/actions/execute',json={'token':ticket['token'],'confirmation':'docker.start'}).status_code,409)

    def test_tiles_persist_escape_unsafe_urls_and_duplicate_ids(self):
        self.setup_admin()
        tile = {'id':'custom','name':'<Service>','url':'https://example.test/page?q=x#section','icon':'files','group':'Tools'}
        self.assertEqual(self.client.put('/api/tiles',json={'tiles':[tile]}).status_code,200)
        recovered = create_app(self.directory.name)
        self.assertEqual(recovered.state.store.read('tiles')[0]['name'],'<Service>')
        self.assertEqual(self.client.put('/api/tiles',json={'tiles':[tile,tile]}).status_code,422)
        self.assertEqual(self.client.put('/api/tiles',json={'tiles':[{**tile,'url':'javascript:alert(1)'}]}).status_code,422)

    def test_no_arbitrary_query_shell_or_file_routes(self):
        self.setup_admin()
        self.assertEqual(self.client.post('/api/graphql',json={'query':'mutation {}'}).status_code,404)
        self.assertEqual(self.client.post('/api/shell',json={'cmd':'anything'}).status_code,404)
        self.assertEqual(self.client.get('/api/sections/unknown').status_code,404)
        self.assertEqual(self.client.get('/storage').status_code,200)
        self.assertIn("frame-ancestors 'none'",self.client.get('/').headers['Content-Security-Policy'])


if __name__ == '__main__': unittest.main()
