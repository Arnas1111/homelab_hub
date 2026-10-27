"""Item → trigger → condition/action → delay graph behavior."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1]))
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from app.modules.zigbee.automation import Automations, automation_router
from app.modules.zigbee.connector import ZigbeeModule
from app.modules.zigbee.graph_automation import GraphRule, compare
from app.modules.zigbee.graph_automation import window_allows
from test_automations import MemoryPreferences
from test_zigbee import light


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.now=1000
        self.prefs=MemoryPreferences()
        self.module=ZigbeeModule({})
        self.module.connected=self.module.bridge_online=True
        self.sensor='zigbee.0x0011223344556688'
        self.lamp='zigbee.0x0011223344556677'
        device={'ieee_address':'0x0011223344556688','friendly_name':'Motion','definition':{'exposes':[
            {'name':'occupancy','property':'occupancy','type':'binary','access':1,'value_on':True,'value_off':False},
            {'name':'action','property':'action','type':'enum','access':1,'values':['single','double']}]}}
        self.module.ingest('zigbee2mqtt/bridge/devices',json.dumps([light(),device]).encode())
        self.module.act=Mock()
        self.engine=Automations(self.prefs,self.module,clock=lambda:self.now)
        self.graph={'name':'Motion flow','enabled':True,'nodes':[
            self.node('sensor','item',item=self.sensor),
            self.node('trigger','trigger',property='occupancy',value=True),
            self.node('lamp1','item',item=self.lamp),
            self.node('on','action',action='set_power',value=True),
            self.node('wait','delay',seconds=5),
            self.node('lamp2','item',item=self.lamp),
            self.node('off','action',action='set_power',value=False)],
            'edges':[{'source':a,'target':b} for a,b in zip(
                ['sensor','trigger','lamp1','on','wait','lamp2'],
                ['trigger','lamp1','on','wait','lamp2','off'])]}

    @staticmethod
    def node(node_id,kind,**values):
        return {'id':node_id,'kind':kind,**values}

    def save(self):
        return self.engine.save_graph(GraphRule.model_validate(self.graph))['id']

    def test_event_actions_delay_and_retrigger(self):
        graph_id=self.save()
        self.engine.process(self.sensor,{'occupancy':False})
        self.module.act.assert_not_called()
        self.engine.process(self.sensor,{'occupancy':True})
        self.assertTrue(self.module.act.call_args.args[1].value)
        self.assertIn(graph_id+':wait:'+self.lamp,self.engine.graph_jobs)
        self.now+=4
        self.engine.process(self.sensor,{'occupancy':True})
        self.now+=2
        self.engine.tick()
        self.assertEqual(self.module.act.call_count,2)
        self.now+=3
        self.engine.tick()
        self.assertFalse(self.module.act.call_args.args[1].value)
        self.assertFalse(self.engine.graph_jobs)

    def test_action_can_select_target_device_after_trigger(self):
        self.graph={'name':'Hallway motion','enabled':True,'nodes':[
            self.node('sensor','item',item=self.sensor),
            self.node('trigger','trigger',property='occupancy',value=True),
            self.node('on','action',target_item=self.lamp,action='set_power',value=True),
            self.node('lamp','item',item=self.lamp)],
            'edges':[{'source':'sensor','target':'trigger'},
                     {'source':'trigger','target':'on'},
                     {'source':'on','target':'lamp'}]}
        self.save()
        self.engine.process(self.sensor,{'occupancy':True})
        self.assertEqual(self.module.act.call_args.args[0],self.lamp)
        self.assertTrue(self.module.act.call_args.args[1].value)

        self.graph['nodes'][2]['target_item']='zigbee.missing'
        with self.assertRaises(HTTPException):
            self.save()

    def test_state_condition_reads_current_item_and_branch(self):
        self.graph['nodes'].insert(3,self.node('check','condition',property='power',value=True))
        self.graph['edges'].remove({'source':'lamp1','target':'on'})
        self.graph['edges'] += [{'source':'lamp1','target':'check'},{'source':'check','target':'on'}]
        self.save()
        self.module.ingest('zigbee2mqtt/Living room',b'{"state":"OFF"}')
        self.engine.process(self.sensor,{'occupancy':True})
        self.module.act.assert_not_called()
        self.module.ingest('zigbee2mqtt/Living room',b'{"state":"ON"}')
        self.engine.process(self.sensor,{'occupancy':True})
        self.assertTrue(self.module.act.call_args.args[1].value)

    def test_button_action_and_time_condition(self):
        self.graph['nodes'][1].update(property='action',value='double')
        self.graph['nodes'].insert(3,self.node('time','time',time_condition={
            'boundary':'clock','time':'23:59','after':True,'offset_minutes':0}))
        self.graph['edges'].remove({'source':'lamp1','target':'on'})
        self.graph['edges'] += [{'source':'lamp1','target':'time'},{'source':'time','target':'on'}]
        self.prefs.write('automation_time',{'timezone':'Europe/Berlin'})
        self.save()
        self.engine.process(self.sensor,{'action':'single'})
        self.engine.process(self.sensor,{'action':'double'})
        self.module.act.assert_not_called()

    def test_comparison_operators_and_numeric_validation(self):
        self.assertTrue(compare(18, 20, 'lt'))
        self.assertTrue(compare(20, 20, 'lte'))
        self.assertTrue(compare(21, 20, 'gt'))
        self.assertTrue(compare(20, 20, 'gte'))
        self.assertTrue(compare(False, True, 'ne'))
        self.assertFalse(compare(False, 1, 'lt'))
        self.assertFalse(compare(True, 1, 'eq'))
        self.graph['nodes'][1]['operator'] = 'lt'
        with self.assertRaises(HTTPException):
            self.save()

    def test_clock_trigger_fires_once_each_local_day_and_survives_restart(self):
        self.prefs.write('automation_time', {'timezone':'Europe/Berlin'})
        berlin = ZoneInfo('Europe/Berlin')
        self.now = datetime(2026, 10, 26, 17, 59, 59, tzinfo=berlin).timestamp()
        self.graph = {'name':'Evening light', 'enabled':True, 'nodes':[
            self.node('clock','clock_trigger',time_condition={'boundary':'clock','time':'18:00','after':True,'offset_minutes':0}),
            self.node('lamp','item',item=self.lamp),
            self.node('on','action',action='set_power',value=True)],
            'edges':[{'source':'clock','target':'lamp'},{'source':'lamp','target':'on'}]}
        graph_id = self.save()
        self.engine.tick()
        self.module.act.assert_not_called()
        self.now += 1
        self.engine.tick()
        self.assertEqual(self.module.act.call_count,1)
        self.engine.tick()
        self.assertEqual(self.module.act.call_count,1)
        recovered = Automations(self.prefs,self.module,clock=lambda:self.now)
        saved = self.prefs.read('zigbee_automations')
        recovered.graphs = saved['graphs']
        recovered.graph_fired = saved['graph_fired']
        recovered.tick()
        self.assertEqual(self.module.act.call_count,1)
        self.assertEqual(recovered.graph_fired[graph_id+':clock'],'2026-10-26')
        self.now = datetime(2026, 10, 27, 18, 0, tzinfo=berlin).timestamp()
        recovered.tick()
        self.assertEqual(self.module.act.call_count,2)

    def test_time_window_crosses_midnight_in_saved_timezone(self):
        berlin=ZoneInfo('Europe/Berlin')
        clock=lambda hour,minute:datetime(2026,10,25,hour,minute,tzinfo=berlin).timestamp()
        self.assertTrue(window_allows('18:00','00:00',clock(23,59),'Europe/Berlin'))
        self.assertFalse(window_allows('18:00','00:00',clock(0,0),'Europe/Berlin'))
        self.assertTrue(window_allows('22:00','06:00',clock(1,0),'Europe/Berlin'))
        self.assertFalse(window_allows('22:00','06:00',clock(12,0),'Europe/Berlin'))
        self.prefs.write('automation_time',{'timezone':'Europe/Berlin'})
        self.graph['nodes'].insert(3,self.node('window','window',start='18:00',end='00:00'))
        self.graph['edges'].remove({'source':'lamp1','target':'on'})
        self.graph['edges'] += [{'source':'lamp1','target':'window'},{'source':'window','target':'on'}]
        self.save()
        self.now=clock(16,0)
        self.engine.process(self.sensor,{'occupancy':True})
        self.module.act.assert_not_called()
        self.now=clock(20,0)
        self.engine.process(self.sensor,{'occupancy':True})
        self.assertTrue(self.module.act.call_args.args[1].value)

    def test_restart_and_delete_preserve_scheduled_branch(self):
        graph_id=self.save()
        self.engine.process(self.sensor,{'occupancy':True})
        self.engine.delete_graph(graph_id)
        saved=self.prefs.read('zigbee_automations')
        recovered=Automations(self.prefs,self.module,clock=lambda:self.now)
        recovered.graphs,recovered.graph_jobs=saved['graphs'],saved['graph_jobs']
        self.now+=5
        recovered.tick()
        self.assertFalse(self.module.act.call_args.args[1].value)
        self.assertFalse(recovered.graph_jobs)

    def test_invalid_cycle_target_action_and_value_rejected(self):
        for change in ('cycle','target','value'):
            candidate=json.loads(json.dumps(self.graph))
            if change=='cycle': candidate['edges'].append({'source':'off','target':'lamp1'})
            if change=='target': candidate['nodes'][-1]['action']='set_temperature'
            if change=='value': candidate['nodes'][1]['value']='true'
            with self.subTest(change=change),self.assertRaises(HTTPException):
                self.engine.save_graph(GraphRule.model_validate(candidate))

    def test_graph_routes_require_login_and_validate_before_saving(self):
        def auth(request: Request):
            if request.headers.get('x-user') != 'owner': raise HTTPException(401)
        app=FastAPI()
        app.include_router(automation_router(self.engine,auth))
        with TestClient(app) as client:
            url='/api/zigbee/automations/graphs'
            self.assertEqual(client.post(url,json=self.graph).status_code,401)
            client.headers['x-user']='owner'
            result=client.post(url,json=self.graph)
            self.assertEqual(result.status_code,201)
            graph_id=result.json()['id']
            self.assertEqual(client.get('/api/zigbee/automations').json()['graphs'][0]['id'],graph_id)
            bad=json.loads(json.dumps(self.graph))
            bad['nodes'][1]['property']='missing'
            self.assertEqual(client.put(url+'/'+graph_id,json=bad).status_code,422)
            self.assertEqual(client.delete(url+'/'+graph_id).status_code,200)
            self.assertEqual(self.engine.graphs,{})


if __name__=='__main__': unittest.main()
