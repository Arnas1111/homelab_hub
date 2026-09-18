"""Read-only adapter for the documented Unraid GraphQL API."""
import json
from urllib.error import HTTPError
from urllib.request import Request, HTTPRedirectHandler, build_opener
from app.modules.docker.discovery import safe_url

QUERY = """query HubOverview {
  info { os { distro release uptime } cpu { brand cores threads } }
  array { state capacity { kilobytes { free used total } } disks { name size status temp } }
}"""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_unraid(config):
    base = config.get('unraid_url', '').rstrip('/')
    token = config.get('unraid_api_key', '')
    if not base or not token:
        return {'configured': False, 'message': 'Connect the Unraid API for array state, disk temperatures and hardware details.'}
    if not safe_url(base):
        return {'configured': True, 'error': 'Use an http(s) Unraid URL without embedded credentials.'}
    url = base if base.endswith('/graphql') else base + '/graphql'
    request = Request(url, data=json.dumps({'query': QUERY}).encode(),
                      headers={'Content-Type': 'application/json', 'x-api-key': token}, method='POST')
    try:
        with build_opener(NoRedirect).open(request, timeout=5) as response:
            result = json.load(response)
        if result.get('errors'):
            return {'configured': True, 'error': 'Unraid rejected this query. Check Info/Array read permissions and API compatibility.'}
        data = result.get('data') or {}
        if not data.get('info') or not data.get('array'):
            return {'configured': True, 'error': 'Unraid returned no hardware or array data.'}
        # Return only requested measurements; never upstream diagnostics or credentials.
        array = data['array']
        capacity = (array.get('capacity') or {}).get('kilobytes') or {}
        # Unraid capacity.disks counts slots; kilobytes contains storage capacity.
        array['capacity_bytes'] = {key: int(capacity[key]) * 1024 if capacity.get(key) is not None else None
                                   for key in ('free', 'used', 'total')}
        return {'configured': True, 'info': data['info'], 'array': array}
    except HTTPError as exc:
        return {'configured': True, 'error': 'Unraid authentication failed. Check the API key.' if exc.code in (401, 403) else 'Unraid API request failed.'}
    except Exception:
        return {'configured': True, 'error': 'Cannot reach Unraid. Check its address, TLS certificate and network access.'}
