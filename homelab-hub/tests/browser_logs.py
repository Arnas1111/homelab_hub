"""Central logs UI checks using bounded collector-shaped fixtures."""
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect
from browser_dashboard import handler as dashboard_handler

state = {'failed': False}
queries = []


def handler(route):
    url = urlparse(route.request.url)
    if url.path != '/api/logs':
        return dashboard_handler(route)
    if state['failed']:
        return route.fulfill(status=503, json={'detail': 'Test outage'})
    query = parse_qs(url.query)
    queries.append(query)
    level = query.get('level', ['issues'])[0]
    rows = [dict(id='one', container_id='abc', service='Media', time=datetime.now(timezone.utc).isoformat(),
                 level='error', detection='inferred', message='Request failed <script>alert(1)</script>'),
            dict(id='two', container_id='abc', service='Media', time=datetime.now(timezone.utc).isoformat(),
                 level='info', detection='explicit', message='Request started')]
    if level != 'all':
        rows = [r for r in rows if r['level'] == level or level == 'issues' and r['level'] == 'error']
    text = query.get('q', [''])[0]
    rows = [r for r in rows if text.lower() in r['message'].lower()]
    route.fulfill(json=dict(entries=rows, matched=len(rows), counts={'error': 1, 'info': 1},
        services=[{'id': 'abc', 'name': 'Media', 'limited': True, 'error': None}, {'id': 'def', 'name': 'Unavailable', 'error': 'Driver cannot read logs'}],
        loading=False, error=None, updated_at=datetime.now(timezone.utc).isoformat(), limited=False,
        scope='Recent Docker stdout/stderr; not a persistent archive.'))


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
        assert not queries, 'Home must not collect logs'
        page.locator('[data-view="logs"]').click()
        expect(page.locator('.aggregate-log-entry')).to_have_count(1)
        expect(page.locator('.aggregate-log-entry pre')).to_contain_text('<script>alert(1)</script>')
        artifacts = Path(os.getenv('HUB_BROWSER_ARTIFACTS', tempfile.gettempdir()))
        page.screenshot(path=str(artifacts / 'hub-logs-desktop.png'), full_page=True)
        assert page.locator('.aggregate-log-entry script').count() == 0
        page.locator('[data-log-context]').click()
        expect(page.locator('.aggregate-log-entry')).to_have_count(2)
        assert queries[-1]['service'] == ['abc']
        assert queries[-1]['level'] == ['all']
        page.locator('#aggregateLogSearch').fill('started')
        expect(page.locator('.aggregate-log-entry')).to_have_count(1)
        page.locator('#aggregateLogCoverage summary').click()
        expect(page.locator('#aggregateLogCoverageBody')).to_contain_text('Driver cannot read logs')
        expect(page.locator('#aggregateLogCoverageBody')).to_contain_text('Capture limit reached')
        state['failed'] = True
        page.locator('#aggregateLogsRefresh').click()
        expect(page.locator('#aggregateLogStatus')).to_contain_text('previous results retained')
        expect(page.locator('.aggregate-log-entry')).to_have_count(1)
        state['failed'] = False
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(artifacts / 'hub-logs-mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow'
        page.locator('.nav-item[data-view="home"]').click()
        expect(page.locator('#homeView')).to_be_visible()
        assert not errors, errors
        browser.close()
        print('Log filters, service context, escaping, source coverage, outage retention and mobile checks passed.')


if __name__ == '__main__':
    main()
