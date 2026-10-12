"""Allowlisted Unraid API operations with server-schema capability detection."""
import threading
import time
import httpx

TYPE_REF = 'kind name ofType { kind name ofType { kind name ofType { kind name } } }'
SCHEMA_QUERY = 'query ControlSchema { __schema { queryType { name } mutationType { name } types { name kind fields { name type { ' + TYPE_REF + ' } args { name defaultValue type { ' + TYPE_REF + ' } } } } } }'
DISK = dict.fromkeys(['id', 'name', 'device', 'size', 'status', 'temp', 'fsSize', 'fsUsed', 'fsFree', 'fsType', 'numErrors', 'isSpinning'], True)
SELECTIONS = {
    'system': ('info', {'os':dict.fromkeys(['hostname', 'distro', 'release', 'uptime', 'kernel'], True),
                        'cpu':dict.fromkeys(['brand', 'cores', 'threads', 'speed'], True),
                        'versions':{'unraid':True}}),
    'metrics': ('metrics', {'cpu':{'percentTotal':True}, 'memory':dict.fromkeys(['total', 'used', 'free', 'available', 'percentTotal'], True)}),
    'storage': ('array', {'state':True, 'capacity':{'kilobytes':dict.fromkeys(['free', 'used', 'total'], True)},
                          'disks':DISK, 'caches':DISK, 'parities':DISK, 'boot':DISK,
                          'parityCheckStatus':dict.fromkeys(['status', 'progress', 'errors', 'speed', 'running', 'paused', 'correcting'], True)}),
    'shares': ('shares', dict.fromkeys(['id', 'name', 'comment', 'free', 'used', 'size', 'cache', 'include', 'exclude', 'allocator', 'splitLevel'], True)),
    'docker': ('docker', {'containers':dict.fromkeys(['id', 'names', 'image', 'state', 'status', 'autoStart', 'webUiUrl', 'iconUrl', 'isUpdateAvailable'], True)}),
    'vms': ('vms', {'domains':{'id':True, 'name':True, 'state':True}}),
    'network': ('networkInterfaces', dict.fromkeys(['id', 'name', 'speed', 'mtu', 'operstate', 'ipAddress', 'gateway', 'virtual', 'macAddress'], True)),
    'notifications': ('notifications', {'list(filter: {type: UNREAD, offset: 0, limit: 100})':dict.fromkeys(['id', 'title', 'subject', 'description', 'importance', 'timestamp'], True)}),
    'plugins': ('plugins', {'name':True, 'version':True, 'hasApiModule':True}),
}
# These are API contracts, not upstream implementation code. No arbitrary query endpoint is exposed.
ACTIONS = {
    **{f'docker.{a}':('docker', a, '($id: PrefixedID!)', '(id: $id)', '{ id state }') for a in ['start', 'stop', 'restart', 'pause', 'unpause']},
    **{f'vm.{a}':('vm', a, '($id: PrefixedID!)', '(id: $id)', '') for a in ['start', 'stop', 'pause', 'resume', 'reboot']},
    'array.start':('array', 'setState', '', '(input: {desiredState: START})', '{ state }'),
    'array.stop':('array', 'setState', '', '(input: {desiredState: STOP})', '{ state }'),
    'parity.start':('parityCheck', 'start', '', '(correct: false)', ''),
    **{f'parity.{a}':('parityCheck', a, '', '', '') for a in ['pause', 'resume', 'cancel']},
    'notification.archive':('', 'archiveNotification', '($id: PrefixedID!)', '(id: $id)', '{ id }'),
}


class ApiError(Exception):
    pass


def base_type(reference):
    while reference.get('ofType'):
        reference = reference['ofType']
    return reference.get('name')


class Unraid:
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        self.schema_lock = threading.Lock()
        self.schema = None
        self.catalog = {}
        self.cache = {}
        self.section_locks = {section:threading.Lock() for section in SELECTIONS}
        self.generation = 0

    def reset(self):
        with self.lock:
            self.schema = None
            self.catalog = {}
            self.cache.clear()
            self.generation += 1

    def request(self, document, variables=None):
        config = self.config()
        if not config.get('enabled') or not config.get('url') or not config.get('api_key'):
            raise ApiError('Connect your Unraid API in Settings.')
        url = config['url'].rstrip('/')
        if not url.endswith('/graphql'):
            url += '/graphql'
        try:
            # Never follow a redirect carrying a server credential.
            with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
                response = client.post(url, headers={'x-api-key':config['api_key']}, json={'query':document, 'variables':variables or {}})
                if response.status_code in (401, 403):
                    raise ApiError('API access denied. Check the key and its permissions.')
                if response.status_code != 200:
                    raise ApiError('Unraid API request failed. Check the address and API service.')
                data = response.json()
        except (httpx.HTTPError, ValueError):
            raise ApiError('Unraid is unreachable. Check its address, TLS certificate, and network.') from None
        if not isinstance(data, dict):
            raise ApiError('Unraid returned no usable data.')
        if data.get('errors'):
            raise ApiError('Unraid rejected this operation. Check API compatibility and permissions.')
        if not isinstance(data.get('data'), dict):
            raise ApiError('Unraid returned no usable data.')
        return data['data']

    def discover(self):
        with self.schema_lock:
            with self.lock:
                if self.schema is not None:
                    return
                generation = self.generation
            schema = self.request(SCHEMA_QUERY).get('__schema')
            if not isinstance(schema, dict) or not isinstance(schema.get('types'), list) or not (schema.get('queryType') or {}).get('name'):
                raise ApiError('Schema discovery unavailable. Enable API introspection/developer access for this preview.')
            catalog = {item['name']:{f['name']:f for f in item.get('fields') or []} for item in schema['types']}
            with self.lock:
                if generation != self.generation:
                    raise ApiError('Connection changed. Refresh to use the new server.')
                self.schema, self.catalog = schema, catalog

    def selection(self, type_name, fields):
        selected = []
        for expression, children in fields.items():
            name = expression.split('(')[0]
            field = self.catalog.get(type_name, {}).get(name)
            if not field:
                continue
            # Required arguments without a default need an explicit contract.
            if '(' not in expression and any(a['type']['kind'] == 'NON_NULL' and a.get('defaultValue') is None for a in field.get('args', [])):
                continue
            target = base_type(field['type'])
            if isinstance(children, dict):
                sub = self.selection(target, children)
                if sub:
                    selected.append(expression + ' { ' + sub + ' }')
            elif not self.catalog.get(target):
                selected.append(expression)
        return ' '.join(selected)

    def read(self, section, fresh=False):
        if section not in SELECTIONS:
            raise ApiError('Unknown section.')
        with self.section_locks[section]:
            with self.lock:
                cached = self.cache.get(section)
                if cached and not fresh and time.time() - cached['sampled_at'] < 10:
                    return {**cached, 'stale':False, 'error':None}
                generation = self.generation
            try:
                self.discover()
                root, fields = SELECTIONS[section]
                with self.lock:
                    schema = self.schema
                if not schema:
                    raise ApiError('Connection changed. Refresh to use the new server.')
                query_type = schema['queryType']['name']
                root_field = self.catalog.get(query_type, {}).get(root)
                if not root_field:
                    raise ApiError('This section is not available in your installed Unraid API.')
                selected = self.selection(base_type(root_field['type']), fields)
                if not selected:
                    raise ApiError('No compatible fields are available for this section.')
                data = self.request('query ControlRead { ' + root + ' { ' + selected + ' } }').get(root)
                if data is None:
                    raise ApiError('Unraid returned no data for this section.')
                result = {'data':data, 'sampled_at':time.time(), 'stale':False, 'error':None}
                with self.lock:
                    if generation != self.generation:
                        raise ApiError('Connection changed. Refresh to use the new server.')
                    self.cache[section] = result
                return result
            except ApiError as error:
                with self.lock:
                    if generation != self.generation:
                        cached = None
                return {**(cached or {'data':None, 'sampled_at':None}), 'stale':bool(cached), 'error':str(error)}

    def capabilities(self):
        self.discover()
        with self.lock:
            schema, catalog = self.schema, self.catalog
        if not schema:
            raise ApiError('Connection changed. Refresh to use the new server.')
        mutation = (schema.get('mutationType') or {}).get('name')
        available = []
        for key, (root, action, *_rest) in ACTIONS.items():
            fields = catalog.get(mutation, {})
            if root:
                root_field = fields.get(root)
                fields = catalog.get(base_type(root_field['type']), {}) if root_field else {}
            if action in fields:
                available.append(key)
        return available

    def act(self, operation, object_id=None):
        if operation not in ACTIONS or operation not in self.capabilities():
            raise ApiError('This operation is not supported by your server API.')
        root, action, definition, arguments, selection = ACTIONS[operation]
        if '$id' in definition and not object_id:
            raise ApiError('Choose a target for this operation.')
        body = action + arguments + ' ' + selection
        if root:
            body = root + ' { ' + body + ' }'
        self.request('mutation ControlAction' + definition + ' { ' + body + ' }', {'id':object_id} if definition else {})
        with self.lock:
            self.cache.clear()
