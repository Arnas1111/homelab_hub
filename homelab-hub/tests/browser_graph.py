"""Home modules and the Zigbee flow canvas with a deterministic Hub API."""
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from browser_dashboard import handler as dashboard_handler

layout={'modules':[{'id':id,'width':2 if id in ('welcome','status','host','services') else 1}
                   for id in ('welcome','status','host','services','attention','connections')]}
graphs=[]
objects=[dict(id='zigbee.motion',name='Motion sensor',type='sensor',available=True,state={'occupancy':False},actions=[],
              capabilities={'occupancy':{'type':'boolean','label':'Occupancy'}}),
         dict(id='zigbee.light',name='Hall light',type='light',available=True,state={'power':False},
              actions=['set_power','set_brightness'],capabilities={'power':{'type':'boolean'},'brightness':{'type':'number','minimum':0,'maximum':100}})]


def handler(route):
    global layout
    path=urlparse(route.request.url).path
    if path=='/api/home/layout':
        if route.request.method=='PUT': layout=route.request.post_data_json
        return route.fulfill(json=layout)
    if path=='/api/v1/objects': return route.fulfill(json={'objects':objects})
    if path=='/api/zigbee/automations/graphs':
        if route.request.method=='POST':
            graphs.append(dict(route.request.post_data_json,id='graph-1',status='Ready'))
            return route.fulfill(status=201,json={'id':'graph-1'})
    if path.startswith('/api/zigbee/automations/graphs/'):
        if route.request.method=='PUT': graphs[:]=[dict(route.request.post_data_json,id='graph-1',status='Ready')]
        if route.request.method=='DELETE': graphs.clear()
        return route.fulfill(json={'id':'graph-1'})
    if path=='/api/zigbee/automations':
        return route.fulfill(json={'graphs':graphs,'rules':[],'pending_count':0,'connection':'online'})
    if path=='/api/zigbee/automations/time-settings':
        return route.fulfill(json={'configured':True,'timezone':'Europe/Berlin','solar_enabled':False})
    return dashboard_handler(route)


def main():
    with sync_playwright() as p:
        options={'headless':True}
        if os.getenv('HUB_BROWSER_EXECUTABLE'): options['executable_path']=os.environ['HUB_BROWSER_EXECUTABLE']
        browser=p.chromium.launch(**options)
        page=browser.new_page(viewport={'width':1440,'height':950})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.route('**/*',handler)
        page.goto('http://hub.test/home')
        expect(page.locator('[data-home-module="attention"]')).to_be_visible()
        page.get_by_role('button',name='Customize Home').click()
        page.locator('[data-module="attention"] [data-enabled]').uncheck()
        page.locator('[data-module="zigbee"] [data-enabled]').check()
        page.locator('[data-module="zigbee"] [data-width]').select_option('2')
        page.get_by_role('button',name='Save layout').click()
        expect(page.locator('[data-home-module="attention"]')).to_be_hidden()
        expect(page.locator('[data-home-module="zigbee"]')).to_be_visible()
        page.reload()
        expect(page.locator('[data-home-module="attention"]')).to_be_hidden()
        assert next(row['width'] for row in layout['modules'] if row['id']=='zigbee')==2
        page.goto('http://hub.test/automations')
        expect(page.locator('[data-nav-group="zigbee"]')).to_have_attribute('open','')
        page.get_by_role('button',name='+ New automation').click()
        palette=page.locator('#graphItemPalette')
        palette.get_by_role('button',name='Motion sensor').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='When state reports').click()
        palette.get_by_role('button',name='Hall light').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='Do action').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='Wait').click()
        palette.get_by_role('button',name='Hall light').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='Do action').click()
        page.locator('#graphInspector [data-field="value"]').select_option('false')
        page.locator('#graphName').fill('Motion → hallway')
        assert page.evaluate('graphCurrent.edges.length')==6
        page.get_by_role('button',name='Save',exact=True).click()
        expect(page.locator('#automationAllCards h3')).to_have_text('Motion → hallway')
        assert graphs[0]['nodes'][-1]['value'] is False
        page.get_by_role('button',name='Edit canvas').click()
        expect(page.locator('#graphName')).to_have_value('Motion → hallway')
        page.locator('#graphName').fill('Edited draft')
        page.evaluate('loadGraphAutomations()')
        expect(page.locator('#graphName')).to_have_value('Edited draft')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors,errors
        browser.close()
        print('PASS: Home module persistence, nested navigation, flow canvas, save/edit, mobile width')


if __name__=='__main__': main()
