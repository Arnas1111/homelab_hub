"""Full frontend smoke test with deterministic API fixtures (no real credentials)."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).parents[1]
STATIC = ROOT / 'app/static'
settings = {'title': 'Homelab Hub', 'refresh_seconds': 5, 'confirm_actions': True, 'version': 'test'}
database = dict(enabled=False, host='', port=5432, database='homelab', username='homelab',
                sslmode='prefer', sample_seconds=30, retention_days=30, include_containers=True,
                password_set=False, status={'last_saved': None, 'error': None, 'running': True})
state = {'history_error': False}
SERIES = {'cpu': [('cpu_percent', 'Host CPU', '%')], 'memory': [('memory_percent', 'Memory utilization', '%'), ('memory_used', 'Used memory', 'B')],
          'storage': [('storage_percent', 'Storage utilization', '%'), ('storage_free', 'Free space', 'B')],
          'network': [('rx_rate', 'Receive', 'B/s'), ('tx_rate', 'Transmit', 'B/s')],
          'containers': [('container_cpu', 'Combined container CPU', '% cores'), ('container_memory', 'Combined container memory', 'B')]}


def handler(route):
    url = urlparse(route.request.url)
    path = url.path
    data = {}
    if path == '/api/metrics/history':
        if state['history_error']:
            route.fulfill(status=503, json={'detail': 'PostgreSQL temporarily unavailable'})
            return
        query = parse_qs(url.query)
        metric = query.get('metric', ['cpu'])[0]
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=1)
        points = []
        for i in range(60):
            point = {'time': (start + timedelta(minutes=i)).isoformat(), 'samples': 2}
            for key, _, unit in SERIES[metric]:
                value = 30 + i % 12 if unit == '%' else 100000 + i * 1000
                point.update({key: value, key + '_max': value + 5, key + '_count': 2})
            points.append(point)
        latest = {key: points[-1][key] for key, _, _ in SERIES[metric]}
        latest.update(cores={'cpu0': 32, 'cpu1': 25}, storage_total=10000000,
                      containers=[{'id': 'abc123', 'name': 'Tdarr', 'cpu_percent': 240, 'memory_used': 300000, 'status': 'running'}])
        data = dict(metric=metric, range=query.get('range', ['24h'])[0], start=start.isoformat(), end=end.isoformat(),
                    bucket_seconds=60, sample_seconds=30, retention_days=30, enabled=True, points=points,
                    series=[dict(key=k, label=l, unit=u) for k, l, u in SERIES[metric]],
                    latest={'sampled_at': end.isoformat(), 'payload': latest}, containers=[{'id': 'abc123', 'name': 'Tdarr'}])
    elif path == '/api/metrics/settings':
        if route.request.method == 'PUT':
            payload = route.request.post_data_json
            database.update({k: v for k, v in payload.items() if k not in ('password', 'clear_password')})
            database['password_set'] = bool(payload['password']) or database['password_set']
        data = database
    elif path == '/api/metrics/test':
        data = {'ok': True, 'server_version': 180000, 'can_create_schema': True, 'schema_exists': False, 'message': 'Connection successful.'}
    elif path == '/api/overview':
        data = dict(settings=settings, containers=[], group_order={}, webui_links=[], server=dict(cpus=4, docker_version='test', metrics={
            'cpu': {'total_percent': 20, 'cores': [{'name': 'CPU 0', 'percent': 20}]},
            'memory': {'total': 10000, 'percent': 40, 'total_human': '16 GB', 'used_human': '6.4 GB'},
            'data_mount': {'total': 100000, 'percent': 60, 'total_human': '1 TB', 'free_human': '400 GB'}}))
    elif path == '/api/icons':
        data = {'icons': []}
    elif path == '/api/integrations':
        data = {'jellyfin': {'active': []}, 'home_assistant': {'entities': []}}
    elif path.startswith('/api/'):
        data = {}
    elif path == '/':
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        for key, value in settings.items():
            html = html.replace('{{ settings.' + key + ' }}', str(value))
        html = html.replace('{{ server_name }}', 'Unraid')
        route.fulfill(content_type='text/html', body=html)
        return
    elif path.startswith('/static/'):
        file = STATIC / path.removeprefix('/static/')
        route.fulfill(path=str(file))
        return
    else:
        route.fulfill(status=404)
        return
    route.fulfill(json=data)


def main():
    with sync_playwright() as p:
        options = {'headless': True}
        if os.getenv('HUB_BROWSER_EXECUTABLE'):
            options['executable_path'] = os.environ['HUB_BROWSER_EXECUTABLE']
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', handler)
        page.goto('http://hub.test/')
        page.get_by_role('button', name='CPU utilization ↗').click()
        page.wait_for_selector('.history-chart')
        assert page.locator('#pageTitle').inner_text() == 'CPU history'
        page.locator('#historyRange').select_option('7d')
        page.wait_for_selector('.history-chart')
        for metric, title in [('memory', 'Memory history'), ('storage', 'Storage history'), ('network', 'Network history'), ('containers', 'Container history')]:
            page.locator(f'.metric-tabs [data-metric-page="{metric}"]').click()
            expect(page.locator('#pageTitle')).to_have_text(title)
            page.wait_for_selector('.history-chart')
            assert page.locator('#pageTitle').inner_text() == title
        page.locator('#historyContainer').select_option('abc123')
        page.wait_for_selector('.history-chart')
        expect(page.locator('#historyContent')).to_contain_text('240.0%')
        state['history_error'] = True
        page.locator('#historyRefresh').click()
        page.wait_for_function("document.getElementById('historyNotice').textContent.includes('temporarily unavailable')")
        assert page.locator('.history-chart').count() == 2
        state['history_error'] = False
        page.locator('#historyRefresh').click()
        page.wait_for_function("!document.getElementById('historyNotice').textContent.includes('temporarily unavailable')")
        page.locator('[data-view="database"]').click()
        page.wait_for_function("document.getElementById('pgStatus').textContent.includes('disabled')")
        page.locator('#pgHost').fill('postgres')
        page.locator('#pgPassword').fill('test-only')
        page.locator('#pgTest').click()
        page.wait_for_function("document.getElementById('pgFeedback').textContent.includes('Connection successful')")
        page.locator('#pgEnabled').check()
        page.locator('#pgSave').click()
        page.wait_for_function("document.getElementById('pgFeedback').textContent.includes('Settings saved')")
        assert page.locator('#pgPassword').input_value() == ''
        assert database['enabled']
        artifacts = Path(os.getenv('HUB_BROWSER_ARTIFACTS', tempfile.gettempdir()))
        page.screenshot(path=str(artifacts / 'hub-history-settings.png'), full_page=True)
        page.locator('[data-view="dashboard"]').click()
        page.get_by_role('button', name='CPU utilization ↗').click()
        page.wait_for_selector('.history-chart')
        page.screenshot(path=str(artifacts / 'hub-history-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_function("document.querySelector('.history-chart').getAttribute('viewBox') === '0 0 360 220'")
        page.screenshot(path=str(artifacts / 'hub-history-mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile overflow'
        page.reload()
        page.wait_for_selector('.history-chart')
        assert page.locator('#pageTitle').inner_text() == 'CPU history'
        assert not errors, errors
        browser.close()
        print('Browser history navigation, range, container filter, outage recovery, settings, password clearing, deep link and mobile checks passed.')


if __name__ == '__main__':
    main()
