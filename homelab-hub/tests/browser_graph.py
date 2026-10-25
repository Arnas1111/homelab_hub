"""Home modules and the Zigbee flow canvas with a deterministic Hub API."""
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from browser_dashboard import handler as dashboard_handler

layout={'modules':[{'id':id,'width':3} for id in ('welcome','host','services')]}
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
        expect(page.locator('[data-home-module="host"]')).to_be_visible()
        page.get_by_role('button',name='Edit dashboard').click()
        expect(page.locator('#homePalette')).to_be_visible()
        expect(page.locator('#homePulse')).to_be_hidden()
        page.locator('#homePaletteItems').get_by_role('button',name='Clock').click()
        page.locator('[data-home-module="clock"] [data-home-action="resize"]').click()
        page.locator('[data-home-module="clock"] .home-drag-handle').click()
        page.get_by_role('button',name='mint accent').click()
        page.locator('#homePaletteItems').get_by_role('button',name='Notes').click()
        page.locator('#homeInspectorNote').fill('Check the Zigbee network.')
        page.locator('[data-home-module="clock"] .home-drag-handle').drag_to(page.locator('[data-home-module="host"]'))
        page.get_by_role('button',name='Save layout').click()
        expect(page.locator('[data-home-module="clock"]')).to_be_visible()
        page.reload()
        expect(page.locator('#homePulse')).to_be_visible()
        expect(page.locator('#homeNoteText')).to_have_text('Check the Zigbee network.')
        assert next(row['width'] for row in layout['modules'] if row['id']=='clock')==2
        assert next(row['accent'] for row in layout['modules'] if row['id']=='clock')=='mint'
        assert next(row['content'] for row in layout['modules'] if row['id']=='notes')=='Check the Zigbee network.'
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
