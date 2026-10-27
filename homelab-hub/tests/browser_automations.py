"""Deep links, browser history and automation editing with deterministic APIs."""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
from browser_dashboard import handler as dashboard_handler
from browser_history import STATIC

rules = [dict(id='test-rule',name='Hall motion',enabled=True,source='zigbee.sensor',property='occupancy',equals=True,
              target='zigbee.lamp',seconds=5,while_occupied=False,time_condition=None,status='Ready',off_at=None)]
objects = [dict(id='zigbee.sensor', name='Hall motion', type='sensor', actions=[], capabilities={
    'occupancy':dict(type='boolean'), 'action':dict(type='enum', options=['single', 'double'])}),
    dict(id='zigbee.lamp', name='Hall light', type='light', actions=['set_power'], capabilities={'power':dict(type='boolean')})]


def handler(route):
    path = urlparse(route.request.url).path
    if path == '/api/v1/objects':
        return route.fulfill(json={'objects':objects})
    if path.startswith('/api/zigbee/automations/time-settings'):
        return dashboard_handler(route)
    if path.startswith('/api/zigbee/automations'):
        method = route.request.method
        if method == 'PUT':
            rule = dict(route.request.post_data_json, id='test-rule', status='Ready', off_at=None)
            rules[:] = [rule]
        elif method == 'DELETE': rules.clear()
        return route.fulfill(json={'rules':rules,'graphs':[], 'pending_count':0, 'connection':'online'})
    return dashboard_handler(route)


def main():
    with sync_playwright() as p:
        options = {'headless':True}
        if os.getenv('HUB_BROWSER_EXECUTABLE'): options['executable_path'] = os.environ['HUB_BROWSER_EXECUTABLE']
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        errors = []
        documents = []
        page.on('pageerror', lambda error:errors.append(str(error)))
        page.on('request', lambda request: documents.append(request.url) if request.resource_type == 'document' else None)
        page.route('**/*', handler)
        page.goto('http://hub.test/containers')
        expect(page.locator('#pageTitle')).to_have_text('Containers')
        page.wait_for_timeout(1000)
        assert len(documents) == 1, documents
        assert page.locator('.nav-item').first.evaluate("node => getComputedStyle(node).textDecorationLine") == 'none'
        page.locator('[data-view="home"]').click()
        expect(page).to_have_url('http://hub.test/home')
        page.go_back()
        expect(page.locator('#pageTitle')).to_have_text('Containers')
        page.go_forward()
        expect(page.locator('#pageTitle')).to_have_text('Home')
        page.reload()
        expect(page.locator('#pageTitle')).to_have_text('Home')
        page.locator('#homePulse [data-metric-page="cpu"]').click()
        expect(page).to_have_url('http://hub.test/history#metrics/cpu')
        page.go_back()
        expect(page.locator('#pageTitle')).to_have_text('Home')
        page.go_forward()
        expect(page.locator('#metricDetailView')).to_have_class('view active')
        page.goto('http://hub.test/history')
        expect(page.locator('#pageTitle')).to_have_text('CPU history')
        expect(page).to_have_url('http://hub.test/history')
        page.locator('.metric-tabs [data-metric-page="memory"]').click()
        page.go_back()
        expect(page).to_have_url('http://hub.test/history')
        expect(page.locator('#pageTitle')).to_have_text('CPU history')
        page.go_forward()
        expect(page.locator('#pageTitle')).to_have_text('Memory history')
        page.go_back()
        expect(page.locator('#pageTitle')).to_have_text('CPU history')
        page.locator('[data-nav-group="services"] summary').click()
        page.locator('[data-view="services"]').click()
        page.go_back()
        expect(page).to_have_url('http://hub.test/history')
        expect(page.locator('#pageTitle')).to_have_text('CPU history')
        page.go_forward()
        expect(page.locator('#pageTitle')).to_have_text('Containers')
        page.goto('http://hub.test/automations')
        expect(page.locator('#pageTitle')).to_have_text('Automations')
        expect(page.locator('#legacyAutomation')).to_have_count(0)
        expect(page.locator('#automationAllCards h3')).to_have_text('Hall motion')
        page.locator('#automationAllCards [data-toggle]').focus()
        rules[0]['status']='Device report received'
        page.evaluate('loadGraphAutomations()')
        expect(page.locator('#automationAllCards [data-toggle]')).to_be_focused()
        page.locator('#automationAllCards [data-toggle]').click()
        expect(page.locator('#automationAllCards [data-toggle]')).to_have_text('Enable')
        assert rules[0]['enabled'] is False
        page.locator('#automationAllCards [data-toggle]').click()
        expect(page.locator('#automationAllCards [data-toggle]')).to_have_text('Disable')
        assert rules[0]['enabled'] is True
        page.set_viewport_size({'width':390, 'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.on('dialog', lambda dialog:dialog.accept())
        page.get_by_role('button', name='Delete', exact=True).click()
        expect(page.locator('#automationAllCards')).to_contain_text('No automations yet')
        # Reproduce the previous handler's lack of preventDefault. Restoration
        # must still select the view without following the section anchor.
        legacy_source = (STATIC / 'app.js').read_text(encoding='utf-8').replace(
            "    event.preventDefault();\n    const routePath", "    const routePath")
        page.route('**/static/app.js*', lambda route: route.fulfill(content_type='application/javascript', body=legacy_source))
        before = len(documents)
        page.goto('http://hub.test/containers')
        expect(page.locator('#pageTitle')).to_have_text('Containers')
        page.wait_for_timeout(1000)
        assert len(documents) == before + 1, documents
        assert not errors, errors
        browser.close()
        print('PASS: deep links, reload, back/forward/history, legacy-rule management, mobile, delete')


if __name__ == '__main__': main()
