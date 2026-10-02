"""Deep links, browser history and automation editing with deterministic APIs."""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
from browser_dashboard import handler as dashboard_handler
from browser_history import STATIC

rules = []
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
        if method in ('POST', 'PUT'):
            rule = dict(route.request.post_data_json, id='test-rule', status='Ready', off_at=None)
            rules[:] = [rule]
        elif method == 'DELETE': rules.clear()
        return route.fulfill(json={'rules':rules, 'pending_count':0, 'connection':'online'})
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
        page.locator('[data-view="services"]').click()
        expect(page).to_have_url('http://hub.test/services')
        page.go_back()
        expect(page.locator('#pageTitle')).to_have_text('Containers')
        page.go_forward()
        expect(page.locator('#pageTitle')).to_have_text('Services')
        page.reload()
        expect(page.locator('#pageTitle')).to_have_text('Services')
        page.locator('[data-metric-page="cpu"]').first.click()
        expect(page).to_have_url('http://hub.test/history#metrics/cpu')
        page.go_back()
        expect(page.locator('#pageTitle')).to_have_text('Services')
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
        page.locator('[data-view="services"]').click()
        page.go_back()
        expect(page).to_have_url('http://hub.test/history')
        expect(page.locator('#pageTitle')).to_have_text('CPU history')
        page.go_forward()
        expect(page.locator('#pageTitle')).to_have_text('Services')
        page.goto('http://hub.test/automations')
        expect(page.locator('#pageTitle')).to_have_text('Automations')
        expect(page.locator('#automationSource')).to_have_value('zigbee.sensor')
        page.locator('#automationName').fill('Motion <hall>')
        page.locator('#automationSeconds').fill('5')
        page.locator('#automationWhileOccupied').check()
        page.locator('#automationTimeEnabled').check()
        page.locator('#automationClock').fill('20:15')
        page.locator('#automationTimeAfter').uncheck()
        expect(page.locator('#automationEqualsLabel')).to_be_hidden()
        expect(page.locator('#automationSecondsLabel')).to_contain_text('occupancy becomes false')
        page.get_by_role('button', name='Save automation').click()
        expect(page.locator('.automation-card h3')).to_have_text('Motion <hall>')
        assert rules[0]['equals'] is True
        assert rules[0]['seconds'] == 5
        assert rules[0]['while_occupied'] is True
        assert rules[0]['time_condition']['time'] == '20:15'
        assert rules[0]['time_condition']['after'] is False
        expect(page.locator('.automation-summary')).to_contain_text('before 20:15')
        expect(page.locator('.automation-summary')).to_contain_text('stays on')
        page.get_by_role('button', name='Edit', exact=True).click()
        expect(page.locator('#automationWhileOccupied')).to_be_checked()
        expect(page.locator('#automationTimeEnabled')).to_be_checked()
        expect(page.locator('#automationClock')).to_have_value('20:15')
        page.locator('#automationTimeBoundary').select_option('sunset')
        expect(page.locator('#automationClockLabel')).to_be_hidden()
        page.locator('#automationSolarOffset').fill('-15')
        page.locator('#automationName').fill('Unsaved draft')
        page.evaluate('loadAutomations()')
        expect(page.locator('#automationName')).to_have_value('Unsaved draft')
        page.locator('#automationProperty').select_option('action')
        expect(page.locator('#automationOccupancyLabel')).to_be_hidden()
        page.locator('#automationValue').select_option('double')
        page.locator('#automationEnabled').uncheck()
        page.get_by_role('button', name='Save automation').click()
        expect(page.locator('.automation-card h3')).to_contain_text('Disabled')
        assert rules[0]['equals'] == 'double'
        assert rules[0]['while_occupied'] is False
        assert rules[0]['time_condition']['boundary'] == 'sunset'
        assert rules[0]['time_condition']['offset_minutes'] == -15
        page.set_viewport_size({'width':390, 'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.on('dialog', lambda dialog:dialog.accept())
        page.get_by_role('button', name='Delete', exact=True).click()
        expect(page.locator('#automationRules')).to_contain_text('No automations yet')
        # Reproduce the previous handler's lack of preventDefault. Restoration
        # must still select the view without following the section anchor.
        legacy_source = (STATIC / 'app.js').read_text(encoding='utf-8').replace(
            "    event.preventDefault();\n    if (!window.hubRestoringRoute", "    if (!window.hubRestoringRoute")
        page.route('**/static/app.js*', lambda route: route.fulfill(content_type='application/javascript', body=legacy_source))
        before = len(documents)
        page.goto('http://hub.test/containers')
        expect(page.locator('#pageTitle')).to_have_text('Containers')
        page.wait_for_timeout(1000)
        assert len(documents) == before + 1, documents
        assert not errors, errors
        browser.close()
        print('PASS: deep links, reload, back/forward/history, motion/button rules, stable drafts, mobile, delete')


if __name__ == '__main__': main()
