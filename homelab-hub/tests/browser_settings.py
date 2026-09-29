"""Settings UI round trips without a broker or production credentials."""
import base64
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
from browser_dashboard import handler as dashboard_handler

config = dict(enabled=False, host='', port=1883, username='', password_set=False,
              tls=False, base_topic='zigbee2mqtt', status={'status':'disabled'})
commands = []
png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=')


def handler(route):
    path = urlparse(route.request.url).path
    if path == '/api/zigbee/settings':
        if route.request.method == 'PUT':
            body = route.request.post_data_json
            commands.append(body)
            config.update({k:v for k,v in body.items() if k not in ('password','clear_password')})
            config['password_set'] = False if body['clear_password'] else bool(body['password']) or config['password_set']
            config['status'] = {'status':'bridge_offline'}
        return route.fulfill(json=config)
    if path == '/api/zigbee/reconnect':
        commands.append('reconnect')
        return route.fulfill(json=config)
    if path == '/api/v1/modules':
        return route.fulfill(json={'modules':[{'id':'zigbee', **config['status']}]})
    if path.startswith('/api/branding/'):
        commands.append((path, route.request.method))
        return route.fulfill(json={'revision':'test-image'})
    if path.startswith('/branding/'):
        return route.fulfill(content_type='image/png', body=png)
    return dashboard_handler(route)


def main():
    with sync_playwright() as p:
        options = {'headless':True}
        if os.getenv('HUB_BROWSER_EXECUTABLE'):
            options['executable_path'] = os.environ['HUB_BROWSER_EXECUTABLE']
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width':1440,'height':1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', handler)
        page.goto('http://hub.test/')
        page.locator('[data-view="settings"]').click()
        expect(page.locator('#mqttStatus')).to_have_text('Zigbee is disabled.')
        page.locator('#mqttEnabled').check()
        page.locator('#mqttHost').fill('broker')
        page.locator('#mqttUser').fill('homelab')
        page.locator('#mqttPassword').fill('test-password')
        page.get_by_role('button', name='Save and connect').click()
        expect(page.locator('#mqttStatus')).to_contain_text('Broker connected')
        expect(page.locator('#mqttPassword')).to_have_value('')
        assert commands[-1]['password'] == 'test-password'
        page.get_by_role('button', name='Save and connect').click()
        page.wait_for_function('!mqttSaving')
        assert commands[-1]['password'] == ''
        expect(page.locator('#mqttSecretStatus')).to_have_text('Password saved.')
        page.locator('#mqttClear').check()
        page.get_by_role('button', name='Save and connect').click()
        expect(page.locator('#mqttSecretStatus')).to_have_text('No broker password saved.')
        page.locator('#mqttReconnect').click()
        page.wait_for_function('!mqttSaving')
        for kind in ('logo','favicon'):
            page.locator(f'#{kind}File').set_input_files({'name':'icon.png','mimeType':'image/png','buffer':png})
            page.locator(f'[data-brand-upload="{kind}"]').click()
            target = page.locator('#hubLogo' if kind == 'logo' else '#hubFavicon')
            expect(target).to_have_attribute('src' if kind == 'logo' else 'href', f'/branding/{kind}?v=test-image')
            page.locator(f'[data-brand-reset="{kind}"]').click()
            expect(page.locator('#brandingStatus')).to_have_text('Default image restored.')
        page.get_by_role('button', name='Service connections', exact=True).click()
        expect(page.locator('#connectorsView')).to_be_visible()
        page.locator('[data-view="settings"]').click()
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Settings overflow on mobile'
        assert not errors, errors
        browser.close()
        print('Settings UI: MQTT save/preserve/clear, reconnect, logo/favicon upload/reset, navigation and mobile passed.')


if __name__ == '__main__':
    main()
