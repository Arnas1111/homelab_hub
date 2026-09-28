"""Exercise the complete UI with deterministic object/action API fixtures."""
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
from browser_dashboard import handler as dashboard_handler

lamp = dict(id='zigbee.0x0011223344556677', module='zigbee', type='light',
            name='Living <room>', available=True, state={'power': False, 'brightness': 50},
            capabilities={}, actions=['set_power', 'set_brightness'], updated_at=None)
state = {'failed': False, 'status': 'online', 'objects': [lamp]}
commands = []


def handler(route):
    path = urlparse(route.request.url).path
    if not path.startswith('/api/v1/'):
        return dashboard_handler(route)
    if state['failed']:
        return route.fulfill(status=503, json={'detail': 'Test outage'})
    if path == '/api/v1/modules':
        return route.fulfill(json={'modules': [{'id': 'zigbee', 'status': state['status']}]})
    if path == '/api/v1/objects':
        return route.fulfill(json={'objects': state['objects']})
    if path.endswith('/actions'):
        commands.append(route.request.post_data_json)
        return route.fulfill(status=202, json={'status': 'sent'})
    route.fulfill(status=404, json={'detail': 'Not found'})


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
        page.locator('[data-view="zigbee"]').click()
        expect(page.locator('#zigbeeStatus')).to_have_text('Zigbee2MQTT online')
        card = page.locator('#zigbeeLights article')
        expect(card.locator('h3')).to_have_text('Living <room>')
        assert card.locator('room').count() == 0
        page.evaluate('window.originalLampCard = document.querySelector("#zigbeeLights article")')
        card.get_by_role('button', name='On', exact=True).click()
        expect(page.locator('#zigbeeFeedback')).to_contain_text('Command sent')
        assert commands[-1] == {'action': 'set_power', 'value': True}
        expect(card.locator('strong')).to_have_text('Off')  # No optimistic state.
        slider = card.locator('input')
        expect(slider).to_be_enabled()
        slider.fill('75')
        slider.dispatch_event('change')
        page.wait_for_function('!zigbeeSending && !zigbeeLoading')
        assert commands[-1] == {'action': 'set_brightness', 'value': 75}
        lamp['state'] = {'power': True, 'brightness': 75}
        page.locator('#zigbeeRefresh').click()
        expect(card.locator('strong')).to_have_text('On')
        assert page.evaluate('window.originalLampCard === document.querySelector("#zigbeeLights article")')
        state['failed'] = True
        page.locator('#zigbeeRefresh').click()
        expect(page.locator('#zigbeeStatus')).to_contain_text('Unable to refresh')
        expect(slider).to_be_disabled()
        expect(card).to_have_count(1)
        state['failed'] = False
        lamp['available'] = False
        state['status'] = 'bridge_offline'
        page.locator('#zigbeeRefresh').click()
        expect(page.locator('#zigbeeStatus')).to_contain_text('waiting for Zigbee2MQTT')
        expect(slider).to_be_disabled()
        state['status'] = 'online'
        lamp['available'] = True
        page.locator('#zigbeeRefresh').click()
        expect(slider).to_be_enabled()
        artifacts = Path(os.getenv('HUB_BROWSER_ARTIFACTS', tempfile.gettempdir()))
        page.screenshot(path=str(artifacts / 'hub-zigbee-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(artifacts / 'hub-zigbee-mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        state['objects'] = []
        page.locator('#zigbeeRefresh').click()
        expect(card).to_have_count(0)
        expect(page.locator('#zigbeeStatus')).to_contain_text('No supported lights')
        page.locator('[data-view="containers"]').click()
        expect(page.locator('#containersPanel')).to_be_visible()
        assert not errors, errors
        browser.close()
        print('Zigbee UI: discovery, actions, state reports, stable DOM, outage recovery, removal and mobile passed.')


if __name__ == '__main__':
    main()
