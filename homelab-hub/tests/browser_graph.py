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
        expect(page.locator('[data-nav-group="zigbee"]')).to_have_attribute('open','')
        page.get_by_role('button',name='+ New automation').click()
        name_gap=page.locator('#graphName').evaluate('''input => {
            const label=input.closest('label'),range=document.createRange();
            range.selectNodeContents(label.firstChild);
            return input.getBoundingClientRect().top-range.getBoundingClientRect().bottom;
        }''')
        assert name_gap >= 8, name_gap
        contrast=page.locator('#graphSave').evaluate('''button => {
            const luminance = color => {
                const rgb=color.match(/\\d+/g).slice(0,3).map(Number).map(value => {
                    const x=value/255; return x <= .04045 ? x/12.92 : ((x+.055)/1.055)**2.4;
                });
                return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
            };
            const style=getComputedStyle(button), foreground=luminance(style.color), background=luminance(style.backgroundColor);
            return (Math.max(foreground,background)+.05)/(Math.min(foreground,background)+.05);
        }''')
        assert contrast >= 4.5, contrast
        palette=page.locator('#graphItemPalette')
        palette.get_by_role('button',name='Motion sensor').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='When item reports').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='While less than').click()
        palette.get_by_role('button',name='Hall light').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='Do action').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='Wait').click()
        palette.get_by_role('button',name='Hall light').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='Do action').click()
        assert page.evaluate('graphCurrent.edges.length')==0, 'new cards must not connect automatically'
        theme=page.evaluate('''() => {
            const old=document.body.dataset.theme;
            document.body.dataset.theme='paper';
            const radius=selector=>getComputedStyle(document.querySelector(selector)).borderTopLeftRadius;
            const result=[radius('.graph-editor'),radius('.graph-palette'),radius('.graph-node')];
            if (old === undefined) delete document.body.dataset.theme;
            else document.body.dataset.theme=old;
            return result;
        }''')
        assert theme==['0px','0px','0px'], theme
        page.evaluate("for (let i=1;i<8;i++) graphLink('n'+i,'n'+(i+1))")
        short_wire=page.locator('#graphWires .graph-wire').first.get_attribute('d')
        assert short_wire.count('L')==1 and 'Q' not in short_wire, short_wire
        page.locator('#graphFit').click()
        page.locator('#graphNodes [data-node="n2"] .graph-node-head').click()
        page.locator('#graphNodes [data-node="n3"] .graph-node-head').dblclick()
        expect(page.locator('#graphInspector [data-field="operator"]')).to_have_value('lt')
        expect(page.locator('#graphInspector [data-field="property"]')).to_have_value('temperature')
        expect(page.locator('#graphInspector [data-field="property"]')).to_be_focused()
        page.locator('#graphNodes [data-node="n5"] .graph-node-head').click()
        page.locator('#graphNodes [data-node="n8"] .graph-node-head').click()
        page.locator('#graphInspector [data-field="value"]').focus()
        page.locator('#graphInspector [data-field="value"]').select_option('false')
        expect(page.locator('#graphInspector [data-field="value"]')).to_be_focused()
        head=page.locator('#graphNodes [data-node="n8"] .graph-node-head')
        head.focus()
        previous_x=page.evaluate('graphCurrent.nodes.at(-1).x')
        head.press('ArrowRight')
        assert page.evaluate('graphCurrent.nodes.at(-1).x')==previous_x+23
        start=head.bounding_box()
        page.mouse.move(start['x']+start['width']/2,start['y']+start['height']/2)
        page.mouse.down()
        page.mouse.move(start['x']+start['width']/2-70,start['y']+start['height']/2-25,steps=5)
        page.mouse.up()
        assert page.evaluate('graphCurrent.nodes.at(-1).x') < previous_x+23, 'placed card should drag again'
        assert page.evaluate('window.getSelection().toString()')=='', 'dragging should not select card text'
        assert page.evaluate('graphCurrent.nodes.every(node => node.x % 23 === 0 && node.y % 23 === 0)')
        port=page.locator('#graphNodes [data-node="n8"] [data-port="out"]')
        sizes=port.evaluate('element => [getComputedStyle(element).width,getComputedStyle(element,"::after").width]')
        assert sizes==['28px','10px'], sizes
        assert page.locator('#graphConnections').count()==0
        assert page.locator('.graph-move-panel').count()==0
        page.locator('#graphZoomOut').click()
        assert page.evaluate('graphCamera.scale') < 1
        page.locator('#graphFit').click()
        assert page.evaluate('getComputedStyle(document.querySelector("#graphViewport")).overflow')=='hidden'
        page.locator('#graphViewport').scroll_into_view_if_needed()
        viewport=page.locator('#graphViewport').bounding_box()
        corner_x=viewport['x']+viewport['width']-20
        corner_y=viewport['y']+80
        camera_x=page.evaluate('graphCamera.x')
        page.mouse.move(corner_x,corner_y)
        page.mouse.down()
        page.mouse.move(corner_x-35,corner_y-20,steps=3)
        page.mouse.up()
        assert page.evaluate('graphCamera.x') < camera_x, 'dragging the background should pan the canvas'
        page.locator('#graphFit').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='Wait').click()
        page.locator('#graphNodes [data-node="n9"] .graph-node-head').press('Delete')
        assert page.evaluate('graphCurrent.nodes.length')==8
        expect(page.locator('.graph-inspector')).to_be_hidden()
        page.locator('#graphFit').click()
        page.locator('#graphWires .graph-wire-hit').first.focus()
        page.locator('#graphWires .graph-wire-hit').first.press('Delete')
        assert page.evaluate('graphCurrent.edges.length')==6
        page.locator('#graphNodes [data-node="n1"]').hover()
        page.locator('#graphNodes [data-node="n1"] [data-port="out"]').drag_to(page.locator('#graphNodes [data-node="n2"] .graph-node-body'))
        assert page.evaluate('graphCurrent.edges.length')==7, 'dragging between dots should create a connection'
        wire=page.locator('#graphWires .graph-wire').first.get_attribute('d')
        assert 'L' in wire and 'C' not in wire, wire
        page.locator('#graphNodes [data-node="n1"]').hover()
        page.locator('#graphNodes [data-node="n1"] [data-port="out"]').click()
        page.locator('#graphNodes [data-node="n2"] [data-port="in"]').click()
        expect(page.locator('#graphFeedback')).to_contain_text('already connected')
        page.locator('#graphNodes [data-node="n8"]').hover()
        page.locator('#graphNodes [data-node="n8"] [data-port="out"]').click()
        page.locator('#graphNodes [data-node="n1"] [data-port="in"]').click()
        expect(page.locator('#graphFeedback')).to_contain_text('loop')
        page.locator('#graphName').fill('Motion → hallway')
        assert page.evaluate('graphCurrent.edges.length')==7
        page.get_by_role('button',name='Save',exact=True).click()
        expect(page.locator('#automationAllCards h3')).to_have_text('Motion → hallway')
        assert graphs[0]['nodes'][-1]['value'] is False
        page.get_by_role('button',name='Edit canvas').click()
        expect(page.locator('#graphName')).to_have_value('Motion → hallway')
        page.locator('#graphName').fill('Edited draft')
        page.evaluate('loadGraphAutomations()')
        expect(page.locator('#graphName')).to_have_value('Edited draft')
        page.locator('#graphCancel').click()
        page.get_by_role('button',name='+ New automation').click()
        palette.get_by_role('button',name='Motion sensor').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='When item reports').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='Do action').click()
        page.evaluate("graphLink('n1','n2'); graphLink('n2','n3')")
        page.locator('#graphFit').click()
        page.locator('#graphNodes [data-node="n2"] .graph-node-head').click()
        page.locator('#graphNodes [data-node="n3"] .graph-node-head').click()
        expect(page.locator('#graphInspector [data-field="target_item"]')).to_have_value('')
        page.locator('#graphInspector [data-field="target_item"]').select_option('zigbee.light')
        expect(page.locator('#graphInspector [data-field="action"]')).to_have_value('set_power')
        assert page.evaluate('graphCurrent.nodes[2].target_item')=='zigbee.light'
        page.locator('#graphName').fill('Motion targets hall light')
        page.get_by_role('button',name='Save',exact=True).click()
        assert graphs[-1]['nodes'][2]['target_item']=='zigbee.light'
        page.get_by_role('button',name='+ New automation').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='When time is reached').click()
        page.locator('#graphInspector [data-field="time"]').fill('19:30')
        palette.get_by_role('button',name='Hall light').click()
        page.locator('#graphLogicPalette').get_by_role('button',name='Do action').click()
        page.evaluate("graphLink('n1','n2'); graphLink('n2','n3')")
        page.locator('#graphName').fill('Evening light')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        columns=page.locator('.graph-workspace > *').evaluate_all('nodes => nodes.map(node => ({top:node.getBoundingClientRect().top,bottom:node.getBoundingClientRect().bottom}))')
        assert columns[0]['bottom'] <= columns[1]['top'] and columns[1]['bottom'] <= columns[2]['top']
        page.get_by_role('button',name='Save',exact=True).click()
        assert graphs[-1]['nodes'][0]['kind']=='clock_trigger'
        assert graphs[-1]['nodes'][0]['time_condition']['time']=='19:30'
        assert not errors,errors
        browser.close()
        print('PASS: Home module persistence, nested navigation, flow canvas, save/edit, mobile width')


if __name__=='__main__': main()
