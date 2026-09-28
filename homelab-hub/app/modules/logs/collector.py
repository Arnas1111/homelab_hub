"""Bounded recent Docker log snapshots, independent of overview collection."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import re
import time

TAIL = 500
MAX_BYTES = 256 * 1024
MAX_CONTAINERS = 200
LEVELS = {'fatal': 'critical', 'panic': 'critical', 'critical': 'critical', 'crit': 'critical',
          'error': 'error', 'err': 'error', 'warning': 'warning', 'warn': 'warning',
          'info': 'info', 'information': 'info', 'debug': 'debug', 'trace': 'debug'}
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
SECRET = re.compile(r'''(?i)((?:["']?(?:password|passwd|token|api[_-]?key|secret|authorization)["']?)\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''')


def redact(message):
    message = re.sub(r'(?i)\bBearer\s+[a-z0-9._~+/-]+=*', 'Bearer [redacted]', message)
    message = SECRET.sub(r'\1[redacted]', message)
    return message


def classify(message):
    """Explicit severity wins; keyword detection is only a fallback."""
    try:
        obj = json.loads(message)
        if isinstance(obj, dict):
            for key in ('level', 'severity', 'log_level', 'loglevel'):
                value = str(obj.get(key, '')).lower()
                if value in LEVELS:
                    return LEVELS[value], 'structured'
    except (ValueError, TypeError):
        pass
    match = re.search(r'(?i)\b(?:level|severity|log_level)\s*[=:]\s*["\']?(critical|fatal|panic|error|err|warning|warn|info|debug|trace)\b', message)
    if not match:
        match = re.search(r'(?:^|\s|\[)(CRITICAL|FATAL|PANIC|ERROR|ERR|WARNING|WARN|INFO|DEBUG|TRACE)(?:\]|:|\s|$)', message)
    if match:
        return LEVELS[match.group(1).lower()], 'explicit'
    # Avoid common success summaries such as "0 errors" or "no errors".
    clean = re.sub(r'(?i)\b(?:no|zero|0)\s+(?:errors?|failures?|warnings?)\b', '', message)
    if re.search(r'(?i)\b(?:panic|fatal)\b', clean):
        return 'critical', 'inferred'
    if re.search(r'(?i)\b(?:errors?|exception|failed|failure|traceback)\b', clean):
        return 'error', 'inferred'
    if re.search(r'(?i)\b(?:warning|warn|deprecated|retrying|timeout|timed out)\b', clean):
        return 'warning', 'inferred'
    return 'unknown', 'unknown'


def parse_lines(raw, container_id, name):
    entries = []
    for number, line in enumerate(raw.decode('utf-8', errors='replace').splitlines()):
        line = ANSI.sub('', line)
        stamp, _, message = line.partition(' ')
        try:
            instant = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if instant.tzinfo is None:
                raise ValueError('Missing timezone')
            timestamp = instant.timestamp()
        except ValueError:
            stamp, timestamp, message = None, None, line
        level, source = classify(message)
        # Continuation lines retain the preceding error severity for traceback context.
        if level == 'unknown' and entries and (message.startswith((' ', '\t', 'Traceback', 'Caused by:', 'at '))):
            level, source = entries[-1]['level'], 'continuation'
        message = redact(message[:16000])
        identity = hashlib.sha256(f'{container_id}:{stamp}:{number}:{message}'.encode()).hexdigest()[:20]
        entries.append(dict(id=identity, container_id=container_id, service=name, time=stamp,
                            timestamp=timestamp, level=level, detection=source, message=message))
    return entries


def collect_logs(client_factory):
    client = client_factory()
    since = int(time.time()) - 86400
    try:
        containers = sorted(client.api.containers(all=True), key=lambda c: (c.get('Names') or [''])[0])

        def read(row):
            cid = row['Id']
            name = (row.get('Names') or [cid[:12]])[0].lstrip('/')
            stream = None
            try:
                stream = client.api.logs(cid, stdout=True, stderr=True, timestamps=True,
                                         tail=TAIL, since=since, stream=True, follow=False)
                content = bytearray()
                capped = False
                for chunk in stream:
                    room = MAX_BYTES - len(content)
                    content.extend(chunk[:room])
                    if len(chunk) >= room:
                        capped = True
                        break
                # Drop a possibly partial final entry at the byte boundary.
                if capped:
                    content = content[:content.rfind(b'\n') + 1]
                entries = parse_lines(bytes(content), cid, name)
                return {'id': cid, 'name': name, 'entries': entries,
                        'limited': capped or len(entries) >= TAIL, 'error': None}
            except Exception:
                return {'id': cid, 'name': name, 'entries': [], 'limited': False,
                        'error': 'Logs unavailable. The container may have disappeared or its logging driver may not support reading.'}
            finally:
                if stream is not None and hasattr(stream, 'close'):
                    stream.close()

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(read, containers[:MAX_CONTAINERS]))
        return {'services': [{k: v for k, v in result.items() if k != 'entries'} for result in results],
                'entries': [entry for result in results for entry in result['entries']],
                'container_limit_reached': len(containers) > MAX_CONTAINERS,
                'since': since, 'tail': TAIL, 'max_bytes': MAX_BYTES}
    finally:
        client.close()


def query_logs(snapshot, level='issues', service='', query='', minutes=60, limit=500):
    data = snapshot.get('data') or {}
    cutoff = time.time() - minutes * 60
    matches = []
    counts = dict(critical=0, error=0, warning=0, info=0, debug=0, unknown=0)
    for entry in data.get('entries', []):
        if entry['timestamp'] is not None and entry['timestamp'] < cutoff:
            continue
        if service and entry['container_id'] != service:
            continue
        if query and query.casefold() not in entry['message'].casefold():
            continue
        counts[entry['level']] += 1
        if level == 'issues' and entry['level'] not in ('critical', 'error', 'warning'):
            continue
        if level not in ('all', 'issues') and entry['level'] != level:
            continue
        matches.append(entry)
    matches.sort(key=lambda e: e['timestamp'] or 0, reverse=True)
    return {**{k: v for k, v in snapshot.items() if k != 'data'},
            'entries': matches[:limit], 'matched': len(matches), 'counts': counts,
            'services': data.get('services', []), 'limited': len(matches) > limit,
            'container_limit_reached': data.get('container_limit_reached', False),
            'scope': f'Recent Docker stdout/stderr: up to {TAIL} lines and 256 KiB per container from the last 24 hours, up to {MAX_CONTAINERS} containers. Not a persistent log archive.'}
