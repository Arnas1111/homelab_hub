"""Home modules and the Zigbee flow canvas with a deterministic Hub API."""
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from browser_dashboard import handler as dashboard_handler

layout={'modules':[{'id':id,'width':3} for id in ('welcome','host','services')]}
graphs=[]
objects=[dict(id='zigbee.motion',name='Motion sensor',type='sensor',available=True,state={'occupancy':False,'temperature':18},actions=[],
              capabilities={'occupancy':{'type':'boolean','label':'Occupancy'},'temperature':{'type':'number','label':'Temperature'}}),
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
            graph_id='graph-'+str(len(graphs)+1)
            graphs.append(dict(route.request.post_data_json,id=graph_id,status='Ready'))
            return route.fulfill(status=201,json={'id':graph_id})
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
        expect(page.locator('#automationGuide')).to_be_visible()
        expect(page.locator('#graphViewport')).to_have_count(0)
        page.locator('#automationGuide > summary').click()
        page.locator('#automationGuide details > summary').click()
        expect(page.locator('#automationDeviceReference')).to_contain_text('Hall light')
        page.get_by_role('button',name='+ New automation').click()
        expect(page.locator('#graphCode')).to_be_visible()
        page.locator('#graphName').fill('Hallway at night')
        page.locator('#graphCode').fill('when "Motion sensor".occupancy == true\nnonsense')
        expect(page.locator('#graphCodeFeedback')).to_contain_text('Line 2')
        page.get_by_role('button',name='Save',exact=True).click()
        assert not graphs, 'invalid text must not be saved'
        combined=('when "Motion sensor".occupancy == true\n'
                  'during 18:00..05:30\n'
                  'do "Hall light".power = on\n\n'
                  'when "Motion sensor".occupancy == false\n'
                  'during 18:00..05:30\n'
                  'wait 5s\n'
                  'if "Motion sensor".occupancy == false\n'
                  'do "Hall light".power = off')
        page.locator('#graphCode').fill(combined)
        page.get_by_role('button',name='Check rule').click()
        expect(page.locator('#graphCodeFeedback')).to_contain_text('2 paths')
        page.get_by_role('button',name='Save',exact=True).click()
        assert len(graphs[-1]['nodes'])==10
        assert len(graphs[-1]['edges'])==8
        assert graphs[-1]['code']==combined
        page.locator('#automationAllCards [data-edit]').click()
        expect(page.locator('#graphCode')).to_have_value(combined)
        page.locator('#graphCode').fill(combined.replace('wait 5s','wait 10s'))
        page.get_by_role('button',name='Save',exact=True).click()
        assert next(node['seconds'] for node in graphs[-1]['nodes'] if node['kind']=='delay')==10
        page.locator('#automationAllCards [data-toggle]').click()
        expect(page.locator('#automationAllCards [data-toggle]')).to_have_text('Enable')
        page.get_by_role('button',name='+ New automation').click()
        page.locator('#graphName').fill('Sunset light')
        page.locator('#graphCode').fill('at sunset+15m\ndo "Hall light".power = on')
        page.get_by_role('button',name='Save',exact=True).click()
        assert graphs[-1]['nodes'][0]['time_condition']['boundary']=='sunset'
        assert graphs[-1]['nodes'][0]['time_condition']['offset_minutes']==15
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors,errors
        browser.close()
        print('PASS: Home persistence, code automation, guide, save/edit, mobile width')


if __name__=='__main__': main()
