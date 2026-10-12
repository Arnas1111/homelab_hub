"""Custom tiles and container Web UI overrides, including polling and reloads."""
import os
from playwright.sync_api import sync_playwright, expect
from browser_dashboard import handler, webui_links


def main():
    with sync_playwright() as p:
        options = {'headless':True}
        if os.getenv('HUB_BROWSER_EXECUTABLE'): options['executable_path'] = os.environ['HUB_BROWSER_EXECUTABLE']
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        errors = []
        page.on('pageerror', lambda error:errors.append(str(error)))
        page.route('**/*', handler)
        page.goto('http://hub.test/services')
        page.locator('#addServiceTile').click()
        page.locator('#serviceTilePreset').select_option(label='Unraid')
        expect(page.locator('#serviceTileUrl')).to_have_value('http://tower.test')
        page.locator('#serviceTileForm [type=submit]').click()
        unraid = page.locator('#allServices .service-card').filter(has=page.locator('strong', has_text='Unraid'))
        expect(unraid.locator('.service-main a')).to_have_attribute('href', 'http://tower.test/')
        expect(unraid.locator('img')).to_have_attribute('src', '/icons/dashboard/unraid.svg')
        page.locator('#addServiceTile').click()
        page.locator('#serviceTilePreset').select_option(label='Automations')
        page.locator('#serviceTileForm [type=submit]').click()
        expect(page.locator('#allServices a[href="http://hub.test/automations"]')).to_have_count(1)
        jellyfin = page.locator('#allServices [data-service-key="container:jellyfin"]')
        jellyfin.get_by_role('button', name='Edit Web UI').click()
        page.locator('#serviceTileUrl').fill('http://media.test:8096')
        page.locator('#serviceTileIcon').select_option('jellyfin')
        page.evaluate('refresh()')
        expect(page.locator('#serviceTileUrl')).to_have_value('http://media.test:8096')
        page.locator('#serviceTileForm [type=submit]').click()
        expect(jellyfin.locator('.service-main a')).to_have_attribute('href', 'http://media.test:8096/')
        expect(jellyfin.locator('img')).to_have_attribute('src', '/icons/dashboard/jellyfin.svg')
        page.reload()
        expect(jellyfin.locator('.service-main a')).to_have_attribute('href', 'http://media.test:8096/')
        expect(page.locator('#allServices .service-card')).to_have_count(8)
        unraid.get_by_role('button', name='Edit tile').click()
        page.locator('#serviceTileName').fill('Tower console')
        page.locator('#serviceTileForm [type=submit]').click()
        expect(page.locator('#allServices')).to_contain_text('Tower console')
        page.set_viewport_size({'width':390, 'height':844})
        page.locator('#addServiceTile').click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        expect(page.locator('#serviceTileDialog')).to_be_visible()
        page.locator('#serviceTileClose').click()
        page.on('dialog', lambda dialog:dialog.accept())
        page.locator('#allServices .service-card').filter(has=page.locator('strong', has_text='Tower console')).get_by_role('button', name='Edit tile').click()
        page.locator('#serviceTileDelete').click()
        expect(page.locator('#allServices .service-card')).to_have_count(7)
        assert not any(link['label'] == 'Tower console' for link in webui_links)
        assert not errors, errors
        browser.close()
        print('PASS: suggested/custom tiles, icons, container Web UI, stable drafts, reload, mobile and deletion')


if __name__ == '__main__': main()
