"""Connector selection, scoped edits, saved secrets, removal and old deep links."""
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect
from browser_dashboard import handler as dashboard_handler

config = {'connectors':[]}
secrets = {}
fail_save = False
commands = []


def handler(route):
    path = urlparse(route.request.url).path
    if path.endswith('/reconnect'):
        return route.fulfill(json={'ok':True})
    if path == '/api/integration-settings' or path.startswith('/api/connectors/'):
        if route.request.method == 'PUT':
            if fail_save:
                return route.fulfill(status=503, json={'detail':'Connection save unavailable'})
            body = route.request.post_data_json
            commands.append(body)
            for key, value in body.items():
                if key.endswith('_clear'):
                    if value: secrets[key.removesuffix('_clear')] = ''
                elif key.endswith(('_api_key', '_token')):
                    if value: secrets[key] = value
                else: config[key] = value
        if route.request.method == 'DELETE':
            connector = path.rsplit('/', 1)[1]
            for key in list(config):
                if key.startswith(connector + '_'): config[key] = ''
            for key in list(secrets):
                if key.startswith(connector + '_'): secrets[key] = ''
        config['connectors'] = [name for name in ('unraid', 'jellyfin', 'home_assistant') if config.get(name + '_url')]
        public = {**config, **{key + '_configured':bool(value) for key, value in secrets.items()}}
        return route.fulfill(json=public)
    return dashboard_handler(route)


def main():
    global fail_save
    with sync_playwright() as p:
        options = {'headless':True}
        if os.getenv('HUB_BROWSER_EXECUTABLE'): options['executable_path'] = os.environ['HUB_BROWSER_EXECUTABLE']
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        errors = []
        page.on('pageerror', lambda error:errors.append(str(error)))
        page.route('**/*', handler)
        page.goto('http://hub.test/connectors')
        expect(page).to_have_url('http://hub.test/integrations')
        expect(page.locator('#pageTitle')).to_have_text('Integrations')
        expect(page.locator('#connectorCards')).to_contain_text('No integrations added yet')
        expect(page.locator('.connection-card')).to_have_count(0)
        expect(page.locator('#unraidPanel')).to_be_hidden()
        expect(page.locator('#integrationsPanelBody .integration-card')).to_have_count(0)
        page.get_by_role('button', name='Add integration', exact=True).click()
        expect(page.locator('.connector-option')).to_have_count(3)
        page.locator('[data-add-connector="jellyfin"]').click()
        expect(page.locator('#jellyfinUrl')).to_be_visible()
        expect(page.locator('#unraidUrl')).to_be_hidden()
        expect(page.locator('#homeAssistantUrl')).to_be_hidden()
        page.locator('#jellyfinUrl').fill('http://media.test')
        page.locator('#jellyfinApiKey').fill('test-media-secret')
        page.get_by_role('button', name='Save connection', exact=True).click()
        expect(page.locator('.connection-card')).to_have_count(1)
        expect(page.locator('.connection-card h3')).to_have_text('Jellyfin')
        expect(page.locator('#connectorEditor')).not_to_be_visible()
        expect(page.locator('.integration-home')).to_have_count(0)
        page.locator('[data-edit-connector="jellyfin"]').click()
        expect(page.locator('#jellyfinApiKey')).to_have_value('')
        page.locator('#jellyfinUrl').fill('http://new-media.test')
        page.evaluate('loadConnectorWorkspace()')
        expect(page.locator('#jellyfinUrl')).to_have_value('http://new-media.test')
        fail_save = True
        page.get_by_role('button', name='Save connection', exact=True).click()
        expect(page.locator('#integrationSettingsSaved')).to_have_text('Connection save unavailable')
        expect(page.locator('#connectorEditor')).to_be_visible()
        fail_save = False
        page.get_by_role('button', name='Save connection', exact=True).click()
        expect(page.locator('#connectorEditor')).not_to_be_visible()
        assert secrets['jellyfin_api_key'] == 'test-media-secret'
        assert all(key.startswith('jellyfin_') for key in commands[-1])
        page.get_by_role('button', name='Add integration', exact=True).click()
        expect(page.locator('.connector-option')).to_have_count(2)
        page.locator('[data-add-connector="home_assistant"]').click()
        page.locator('#homeAssistantUrl').fill('http://home.test')
        page.locator('#homeAssistantToken').fill('test-home-secret')
        page.get_by_role('button', name='Save connection', exact=True).click()
        expect(page.locator('.connection-card')).to_have_count(2)
        page.reload()
        expect(page.locator('.connection-card')).to_have_count(2)
        page.locator('[data-enable-connector="home_assistant"]').uncheck()
        expect(page.locator('.connection-card[data-connector="home_assistant"] small')).to_have_text('Disabled')
        assert secrets['home_assistant_token'] == 'test-home-secret'
        expect(page.locator('.integration-home')).to_have_count(0)
        page.reload()
        expect(page.locator('[data-enable-connector="home_assistant"]')).not_to_be_checked()
        page.locator('[data-enable-connector="home_assistant"]').check()
        page.locator('[data-reconnect-connector="home_assistant"]').click()
        expect(page.locator('#toast')).to_have_text('Checking connection.')
        page.set_viewport_size({'width':390, 'height':844})
        page.locator('[data-edit-connector="home_assistant"]').click()
        expect(page.locator('#connectorEditor')).to_be_visible()
        assert page.locator('#connectorEditor').evaluate('node => node.scrollWidth <= node.clientWidth')
        page.locator('[data-close-connector]').click()
        page.locator('[data-remove-connector="jellyfin"]').click()
        expect(page.locator('.connection-card')).to_have_count(1)
        expect(page.locator('.connection-card h3')).to_have_text('Home Assistant')
        assert secrets['jellyfin_api_key'] == ''
        assert secrets['home_assistant_token'] == 'test-home-secret'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        browser.close()
        print('PASS: unified connectors, empty state, picker, scoped save, secret preservation, failed save, stable draft, removal, deep links and mobile')


if __name__ == '__main__': main()
