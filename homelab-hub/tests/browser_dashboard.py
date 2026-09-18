"""Exercise the workspace with discovered services, slow stats and independent integrations."""
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect
from browser_history import handler as history_handler, settings

favorites = []
requests = []
containers = [dict(id=str(i), short_id=str(i), name=name.lower().replace(' ', '-'), display_name=name,
                   image='example/' + name.lower(), status='running', health='unhealthy' if i == 2 else None,
                   group_name=group, icon='docker', ports=[], discovered_url='http://tower:8096/' if i == 0 else '',
                   integration='jellyfin' if i == 0 else None, stats_available=False)
              for i, (name, group) in enumerate([('Jellyfin', 'Media'), ('Sonarr', 'Media'), ('Backups', 'Infrastructure'),
                                                ('Home Assistant', 'Automation'), ('Grafana', 'Infrastructure'), ('Photos', 'Files')])]


def handler(route):
    url = urlparse(route.request.url)
    requests.append(url)
    if url.path == '/api/overview':
        route.fulfill(json=dict(settings=settings, containers=containers, board={'favorites': favorites},
            webui_links=[], group_order={}, connections={'unraid': True},
            discovery={'loading': False, 'error': None, 'updated_at': '2026-09-18T12:00:00Z'},
            server=dict(name='Tower', cpus=8, memory_total=34359738368, containers_running=6, containers_total=6,
                metrics={'cpu': {'total_percent': 14, 'cores': [{'name': 'CPU 0', 'percent': 14}]},
                         'memory': {'total': 34359738368, 'percent': 42, 'available_human': '18.6 GB'},
                         'data_mount': {'total': 100000, 'percent': 78, 'free_human': '2.4 TB'}})))
    elif url.path == '/api/board':
        favorites[:] = route.request.post_data_json['favorites']
        route.fulfill(json={'favorites': favorites})
    elif url.path == '/api/unraid':
        route.fulfill(json={'data': {'configured': True, 'info': {'cpu': {'brand': 'Test processor'}, 'os': {'distro': 'Unraid', 'release': '7'}},
                                    'array': {'state': 'STARTED', 'capacity_bytes': {'free': 2400000000000},
                                              'disks': [{'name': 'disk1', 'status': 'DISK_OK', 'temp': 34}]}}})
    elif url.path.startswith('/icons/'):
        route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="4" fill="#9ac4ff"/></svg>')
    else:
        history_handler(route)


def main():
    with sync_playwright() as p:
        options = {'headless': True}
        if os.getenv('HUB_BROWSER_EXECUTABLE'):
            options['executable_path'] = os.environ['HUB_BROWSER_EXECUTABLE']
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('**/*', handler)
        page.goto('http://hub.test/')
        expect(page.locator('#homeServices .service-card')).to_have_count(6)
        assert page.evaluate('new Set([...document.querySelectorAll("[id]")].map(e => e.id)).size === document.querySelectorAll("[id]").length'), 'Duplicate element IDs'
        expect(page.locator('#homeAttention')).to_contain_text('Backups')
        assert not any(r.path in ('/api/icons', '/api/integrations', '/api/unraid') for r in requests)
        assert all(parse_qs(r.query)['include_stats'] == ['false'] for r in requests if r.path == '/api/overview')
        expect(page.locator('#homeServices a').first).to_have_attribute('href', 'http://tower:8096/')
        artifacts = Path(os.getenv('HUB_BROWSER_ARTIFACTS', tempfile.gettempdir()))
        page.screenshot(path=str(artifacts / 'hub-home-desktop.png'), full_page=True)
        page.get_by_role('button', name='Pin Jellyfin', exact=True).click()
        expect(page.locator('#homeServices .service-card')).to_have_count(1)
        page.reload()
        expect(page.locator('#homeServices .service-card')).to_have_count(1)
        page.keyboard.press('Control+k')
        expect(page.locator('#serviceSearch')).to_be_focused()
        page.locator('#serviceSearch').fill('sonarr')
        expect(page.locator('#allServices .service-card')).to_have_count(1)
        page.locator('#serviceSearch').fill('')
        page.locator('#serviceFilter').select_option('attention')
        expect(page.locator('#allServices')).to_contain_text('Backups')
        expect(page.locator('#allServices .service-card')).to_have_count(1)
        page.locator('#serviceFilter').select_option('all')
        page.locator('#manageServices').click()
        expect(page.locator('.webui-editor')).to_have_attribute('open', '')
        expect(page.locator('.webui-editor')).to_be_visible()
        page.locator('.nav-item[data-view="containers"]').click()
        expect(page.locator('.container-row')).to_have_count(6)
        expect(page.locator('.container-cpu').first).to_have_text('\u2014')
        assert any(parse_qs(r.query).get('include_stats') == ['true'] for r in requests)
        page.locator('.nav-item[data-view="integrations"]').click()
        expect(page.locator('#unraidPanel')).to_contain_text('Test processor')
        expect(page.locator('#unraidPanel')).to_contain_text('disk1')
        page.locator('.nav-item[data-view="home"]').click()
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(artifacts / 'hub-home-mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow'
        page.locator('.nav-item[data-view="services"]').click()
        expect(page.locator('#allServices .service-card')).to_have_count(6)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Services overflow'
        assert not errors, errors
        browser.close()
        print('Workspace discovery, independent loading, favorites persistence, search, filtering, pending stats, Unraid and mobile checks passed.')


if __name__ == '__main__':
    main()
