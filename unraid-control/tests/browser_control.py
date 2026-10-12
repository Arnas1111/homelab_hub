"""Original workspace interactions with deterministic API contracts."""
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

STATIC = Path(__file__).resolve().parents[1] / 'static'
settings = {'title':'Unraid Control','url':'https://tower.example','enabled':True,'api_key_configured':True,
            'controls_enabled':True,'login_required':True,'homelab_url':'http://hub.example:3333'}
tiles, commands, errors = [], [], []
sections = {
    'system':{'os':{'hostname':'Tower','release':'7.2.3','uptime':'4 days'},'cpu':{'brand':'AMD Ryzen 7','cores':8,'threads':16},'versions':{'unraid':'7.2.3'}},
    'metrics':{'cpu':{'percentTotal':18.4},'memory':{'total':34359738368,'used':12884901888,'percentTotal':37.5}},
    'storage':{'state':'STARTED','capacity':{'kilobytes':{'free':6442450944,'used':12884901888,'total':19327352832}},
               'disks':[{'id':'disk:1','name':'disk1','device':'sdb','size':8589934592,'status':'DISK_OK','temp':33,'fsUsed':6442450944,'fsFree':2147483648,'fsType':'xfs','numErrors':0}],
               'caches':[{'id':'cache:1','name':'cache','device':'nvme0n1','size':1073741824,'status':'DISK_OK','temp':39,'fsUsed':268435456,'fsFree':805306368,'fsType':'btrfs','numErrors':0}],
               'parities':[], 'parityCheckStatus':{'status':'COMPLETED','progress':100,'errors':0,'speed':'162','running':False}},
    'docker':{'containers':[{'id':'docker:1','names':['/Jellyfin'],'image':'jellyfin/jellyfin:latest','state':'RUNNING','autoStart':True,'webUiUrl':'https://media.example'},
                            {'id':'docker:2','names':['/Home Assistant'],'image':'homeassistant/home-assistant:stable','state':'RUNNING','autoStart':True,'webUiUrl':'https://home.example'},
                            {'id':'docker:3','names':['/Backups'],'image':'example/backup','state':'EXITED','autoStart':False}]},
    'vms':{'domains':[{'id':'vm:1','name':'Windows workstation','state':'RUNNING'}]},
    'shares':[{'id':'share:1','name':'media','comment':'Films and music','used':6442450944,'free':2147483648,'cache':False,'allocator':'highwater','include':[],'exclude':[]}],
    'network':[{'id':'nic:1','name':'br0','operstate':'up','speed':1000,'ipAddress':'192.0.2.20','mtu':1500,'virtual':False}],
    'notifications':{'list':[{'id':'notice:1','title':'Parity verification completed','subject':'No parity errors found','description':'Last verification finished successfully.','importance':'INFO'}]},
    'plugins':[{'name':'Unraid API','version':'installed','hasApiModule':True}],
}


def handler(route):
    path = urlparse(route.request.url).path
    if path.startswith('/static/'):
        file = STATIC / Path(path).name
        kind = 'text/css' if file.suffix == '.css' else 'application/javascript'
        return route.fulfill(body=file.read_text(encoding='utf-8'),content_type=kind)
    if not path.startswith('/api/'):
        return route.fulfill(body=(STATIC/'index.html').read_text(encoding='utf-8'),content_type='text/html')
    if path == '/api/access': data = {'setup':False,'authenticated':True}
    elif path == '/api/settings':
        if route.request.method == 'PUT':
            incoming = route.request.post_data_json
            settings.update({k:v for k,v in incoming.items() if k not in ('api_key','clear_api_key')})
        data = settings
    elif path == '/api/tiles':
        if route.request.method == 'PUT': tiles[:] = route.request.post_data_json['tiles']
        data = {'tiles':tiles}
    elif path == '/api/capabilities':
        data = {'controls_enabled':True,'actions':['docker.start','docker.stop','docker.restart','vm.stop','array.stop','parity.start','notification.archive']}
    elif path.startswith('/api/sections/'):
        section = path.rsplit('/',1)[1]
        data = {'data':sections[section],'sampled_at':1781268000,'stale':False,'error':None}
    elif path == '/api/actions/prepare':
        incoming = route.request.post_data_json
        data = {'token':'single-use','confirmation':incoming['operation'],'impact':'This will stop a workload.','expires_in':60}
    elif path == '/api/actions/execute':
        commands.append(route.request.post_data_json)
        data = {'ok':True}
    elif path == '/api/audit': data = {'events':[]}
    elif path == '/api/reconnect': data = {'actions':['docker.start']}
    else: data = {'ok':True}
    return route.fulfill(json=data)


def main():
    with sync_playwright() as p:
        options = {'headless':True}
        if os.getenv('CONTROL_BROWSER_EXECUTABLE'): options['executable_path'] = os.environ['CONTROL_BROWSER_EXECUTABLE']
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width':1440,'height':1100})
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.route('**/*',handler)
        page.goto('http://control.test/')
        expect(page.locator('h1')).to_have_text('Overview')
        expect(page.locator('#content')).to_contain_text('18.4')
        artifacts = Path(os.getenv('CONTROL_BROWSER_ARTIFACTS', tempfile.gettempdir()))
        artifacts.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(artifacts/'unraid-control-overview.png'),full_page=True)
        page.locator('.nav-link[data-page=storage]').click()
        expect(page.locator('#content')).to_contain_text('disk1')
        expect(page.locator('#content')).to_contain_text('8.0 TiB')
        expect(page.locator('#content')).to_contain_text('33 °C')
        page.locator('.nav-link[data-page=docker]').click()
        expect(page.locator('#content')).to_contain_text('Jellyfin')
        page.locator('[data-operation="docker.stop"]').first.click()
        expect(page.locator('#confirmationDialog')).to_be_visible()
        assert not commands, 'A command ran before explicit confirmation'
        page.locator('#confirmationText').fill('docker.stop')
        page.locator('#confirmationForm button').click()
        expect(page.locator('#confirmationDialog')).not_to_be_visible()
        assert len(commands) == 1
        page.locator('#sectionSearch').fill('backups')
        expect(page.locator('#results .row')).to_have_count(1)
        page.locator('.nav-link[data-page=services]').click()
        page.locator('#addTile').click()
        page.locator('#tilePreset').select_option(label='Automations')
        expect(page.locator('#tileUrl')).to_have_value('http://hub.example:3333/automations')
        page.locator('#tileForm [type=submit]').click()
        expect(page.locator('#tileDialog')).not_to_be_visible()
        expect(page.locator('.service-tile')).to_have_count(3)
        page.reload()
        expect(page.locator('.service-tile')).to_have_count(3)
        page.locator('[data-tile]').click()
        page.locator('#tileName').fill('Sensor <rules>')
        page.evaluate('refresh()')
        expect(page.locator('#tileName')).to_have_value('Sensor <rules>')
        page.locator('#tileForm [type=submit]').click()
        expect(page.locator('#content')).to_contain_text('Sensor <rules>')
        page.keyboard.press('Control+k')
        page.locator('#commandSearch').fill('shares')
        page.locator('.command-result').click()
        expect(page.locator('h1')).to_have_text('Shares')
        expect(page).to_have_url('http://control.test/shares')
        page.go_back()
        expect(page.locator('h1')).to_have_text('Services')
        page.locator('.nav-link[data-page=settings]').click()
        page.locator('[name=title]').fill('My server')
        page.evaluate('refresh()')
        expect(page.locator('[name=title]')).to_have_value('My server')
        page.locator('#settingsForm [type=submit]').click()
        expect(page.locator('#settingsMessage')).to_contain_text('Settings saved')
        assert 'api_key' not in settings
        page.locator('.nav-link[data-page=tools]').click()
        expect(page.locator('#content')).to_contain_text('parity incomplete')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#menuToggle').click()
        page.locator('.nav-link[data-page=overview]').click()
        expect(page.locator('h1')).to_have_text('Overview')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(artifacts/'unraid-control-mobile.png'),full_page=True)
        assert not errors, errors
        browser.close()
        print('PASS: original overview/storage, confirmation, tiles/persistence, escaping, stable drafts, command navigation, history, settings, mobile')


if __name__ == '__main__': main()
