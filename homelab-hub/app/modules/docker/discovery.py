"""Docker list metadata only: no inspect-per-container or stats on the landing path."""
import re
from urllib.parse import urlsplit, urlunsplit

# Service recognition supplies presentation defaults, never authentication or API access.
CATALOG = [
    (('jellyfin',), 'jellyfin', 'Media', 'jellyfin'),
    (('plex',), 'plex', 'Media', None),
    (('sonarr',), 'sonarr', 'Media', None),
    (('radarr',), 'radarr', 'Media', None),
    (('prowlarr',), 'prowlarr', 'Media', None),
    (('jellyseerr', 'seerr'), 'jellyseerr', 'Media', None),
    (('tdarr',), 'docker', 'Media', None),
    (('qbittorrent',), 'qbittorrent', 'Downloads', None),
    (('sabnzbd',), 'sabnzbd', 'Downloads', None),
    (('transmission',), 'transmission', 'Downloads', None),
    (('home-assistant', 'homeassistant'), 'home-assistant', 'Automation', 'home_assistant'),
    (('node-red', 'nodered'), 'node-red', 'Automation', None),
    (('mosquitto', 'mqtt'), 'mqtt', 'Automation', None),
    (('immich',), 'immich', 'Files & photos', None),
    (('nextcloud',), 'nextcloud', 'Files & photos', None),
    (('filebrowser',), 'filebrowser', 'Files & photos', None),
    (('paperless',), 'paperless-ngx', 'Files & photos', None),
    (('grafana',), 'grafana', 'Infrastructure', None),
    (('uptime-kuma',), 'uptime-kuma', 'Infrastructure', None),
    (('postgres',), 'postgresql', 'Infrastructure', None),
    (('mariadb',), 'mariadb', 'Infrastructure', None),
    (('redis',), 'redis', 'Infrastructure', None),
    (('authentik',), 'authentik', 'Infrastructure', None),
    (('nginx-proxy-manager',), 'nginx-proxy-manager', 'Infrastructure', None),
]


def safe_url(value):
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            return ''
        if any(ord(c) < 32 for c in value) or '\\' in value:
            return ''
        return urlunsplit(parts)
    except ValueError:
        return ''


def metadata(row):
    labels = row.get('Labels') or {}
    name = (row.get('Names') or [row.get('Id', '')[:12]])[0].lstrip('/')
    identity = (name + ' ' + row.get('Image', '')).lower()
    detected = next((item for item in CATALOG if any(term in identity for term in item[0])), None)
    icon, group, integration = detected[1:] if detected else ('docker', 'Other services', None)
    icon_label = labels.get('homelab.icon') or labels.get('homepage.icon') or labels.get('net.unraid.docker.icon', '')
    slug = icon_label.rsplit('/', 1)[-1].split('?', 1)[0].removesuffix('.svg').removesuffix('.png').removeprefix('sh-')
    if re.fullmatch(r'[a-z0-9-]{1,90}', slug):
        icon = slug
    ports = []
    seen = set()
    for port in row.get('Ports', []):
        if not port.get('PublicPort'):
            continue
        internal = f"{port['PrivatePort']}/{port.get('Type', 'tcp')}"
        key = (internal, port['PublicPort'])
        if key in seen:
            continue
        seen.add(key)
        ports.append({'internal': internal, 'host_ip': port.get('IP', ''), 'host_port': str(port['PublicPort'])})
    raw = row.get('Status', '')
    health = 'unhealthy' if '(unhealthy)' in raw else 'healthy' if '(healthy)' in raw else 'starting' if '(health: starting)' in raw else None
    # Only allowlisted display metadata is returned, never all Docker labels.
    return {'id': row['Id'], 'short_id': row['Id'][:12], 'name': name, 'image': row.get('Image', ''),
            'status': row.get('State', 'unknown'), 'health': health, 'ports': ports,
            'project': labels.get('com.docker.compose.project'), 'service': labels.get('com.docker.compose.service'),
            'icon': icon, 'group_name': labels.get('homelab.group') or labels.get('homepage.group') or group,
            'display_name': (labels.get('homelab.name') or labels.get('homepage.name') or name)[:120],
            'description': (labels.get('homelab.description') or labels.get('homepage.description') or '')[:240],
            'discovered_url': labels.get('homelab.href') or labels.get('homepage.href') or labels.get('net.unraid.docker.webui', ''),
            'integration': integration, 'network_mode': (row.get('HostConfig') or {}).get('NetworkMode', ''),
            'stats_available': False, 'cpu_percent': None, 'memory_used': None, 'memory_limit': None, 'memory_percent': None}


def service_url(template, ports, hostname):
    # Unraid WebUI templates reference the internal port; map to its published host port.
    host = f'[{hostname}]' if ':' in hostname and not hostname.startswith('[') else hostname
    template = template.replace('[IP]', host)
    def port_value(match):
        internal = match.group(1)
        found = next((p['host_port'] for p in ports if p['internal'] == internal + '/tcp'), None)
        return found or match.group(0)
    template = re.sub(r'\[PORT:(\d+)\]', port_value, template)
    return '' if '[' in template.replace(f'[{hostname}]', '') else safe_url(template)


def load_inventory(client_factory):
    client = client_factory()
    try:
        rows = client.api.containers(all=True)
        info = client.info()
        containers = sorted((metadata(row) for row in rows), key=lambda c: c['name'].lower())
        return {'containers': containers, 'server': {
            'docker_version': info.get('ServerVersion'), 'os': info.get('OperatingSystem'),
            'kernel': info.get('KernelVersion'), 'cpus': info.get('NCPU'), 'memory_total': info.get('MemTotal'),
            'containers_total': len(containers), 'containers_running': sum(c['status'] == 'running' for c in containers),
            'containers_paused': sum(c['status'] == 'paused' for c in containers),
            'containers_stopped': sum(c['status'] not in ('running', 'paused') for c in containers)}}
    finally:
        client.close()
