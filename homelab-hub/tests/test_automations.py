"""Fresh event delivery, durable timers, retriggers and authenticated rule editing."""
import copy
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1]))
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from app.modules.zigbee.automation import Automations, Rule, automation_router
from app.modules.zigbee.connector import ZigbeeModule
from test_zigbee import light


class MemoryPreferences:
    def __init__(self): self.values = {}
    def read(self, key, default=None): return copy.deepcopy(self.values.get(key, default))
    def write(self, key, value): self.values[key] = copy.deepcopy(value)


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.module = ZigbeeModule({})
        self.module.connected = self.module.bridge_online = True
        self.sensor = 'zigbee.0x0011223344556688'
        self.target = 'zigbee.0x0011223344556677'
        self.module.ingest('zigbee2mqtt/bridge/devices', json.dumps([light(), {
            'ieee_address': '0x0011223344556688', 'friendly_name': 'Motion', 'definition': {'exposes': [
                {'name':'occupancy', 'property':'occupancy', 'type':'binary', 'access':1, 'value_on':True, 'value_off':False},
                {'name':'action', 'property':'action', 'type':'enum', 'access':1, 'values':['single', 'double']},
                {'name':'battery', 'property':'battery', 'type':'numeric', 'access':1}]}}]).encode())
        self.module.act = Mock()
        self.prefs = MemoryPreferences()
        self.engine = Automations(self.prefs, self.module, clock=lambda:self.now)
        self.module.on_report = self.engine.notify
        self.rule = Rule(name='Motion light', source=self.sensor, property='occupancy', equals=True,
                         target=self.target, seconds=5)
        self.id = self.engine.save_rule(self.rule)['id']

    def test_motion_retrigger_extends_and_off_happens_without_browser(self):
        self.engine.process(self.sensor, {'occupancy':True})
        self.assertTrue(self.module.act.call_args.args[1].value)
        self.now += 4
        self.engine.process(self.sensor, {'occupancy':True})
        self.now += 2
        self.engine.tick()
        self.assertEqual(self.module.act.call_count, 2)
        self.now += 3
        self.engine.tick()
        self.assertFalse(self.module.act.call_args.args[1].value)
        self.assertFalse(self.engine.pending)

    def test_partial_reports_false_and_retained_do_not_trigger(self):
        self.engine.process(self.sensor, {'battery':99})
        self.engine.process(self.sensor, {'occupancy':False})
        self.module.ingest('zigbee2mqtt/Motion', b'{"occupancy":true}', retained=True)
        self.assertTrue(self.engine.events.empty())
        self.module.act.assert_not_called()
        self.module.ingest('zigbee2mqtt/Motion', b'{"battery":98}')
        _, source, values = self.engine.events.get_nowait()
        self.assertEqual(values, {'battery':98})
        self.engine.process(source, values)
        self.module.act.assert_not_called()

    def test_restart_recovers_overdue_off_and_retries_outage(self):
        self.engine.process(self.sensor, {'occupancy':True})
        recovered = Automations(self.prefs, self.module, clock=lambda:self.now)
        saved = self.prefs.read('zigbee_automations')
        recovered.rules, recovered.pending = saved['rules'], saved['pending']
        self.now += 20
        self.module.act.side_effect = RuntimeError('offline')
        recovered.tick()
        self.assertTrue(recovered.pending)
        self.module.act.side_effect = None
        self.now += 5
        recovered.tick()
        self.assertFalse(self.module.act.call_args.args[1].value)
        self.assertFalse(recovered.pending)

    def test_delete_and_disable_preserve_cleanup(self):
        self.engine.process(self.sensor, {'occupancy':True})
        self.engine.save_rule(self.rule.model_copy(update={'enabled':False}), self.id)
        self.engine.process(self.sensor, {'occupancy':True})
        self.assertEqual(self.module.act.call_count, 1)
        self.engine.delete(self.id)
        self.now += 5
        self.engine.tick()
        self.assertFalse(self.module.act.call_args.args[1].value)

    def test_worker_loads_persisted_deadline_at_start(self):
        self.engine.process(self.sensor, {'occupancy':True})
        self.now += 10
        done = threading.Event()
        self.module.act.side_effect = lambda target, request: done.set() if request.value is False else None
        recovered = Automations(self.prefs, self.module, clock=lambda:self.now)
        recovered.start()
        try:
            self.assertTrue(done.wait(2), 'Background worker did not recover switch-off')
        finally:
            recovered.stop()
        self.assertFalse(self.prefs.read('zigbee_automations')['pending'])

    def test_repeated_button_events_and_shared_target_deadline(self):
        self.engine.save_rule(self.rule.model_copy(update={'property':'action', 'equals':'single', 'seconds':20}))
        self.engine.process(self.sensor, {'action':'single'})
        self.now += 1
        self.engine.process(self.sensor, {'action':'single'})
        self.engine.process(self.sensor, {'occupancy':True})
        self.assertEqual(self.engine.pending[self.target]['due'], 1021)
        self.assertEqual(self.module.act.call_count, 3)

    def test_invalid_capability_values_and_actuator_triggers_rejected(self):
        for change in [{'equals':'true'}, {'target':self.sensor}, {'source':self.target, 'property':'power'}, {'property':'missing'}]:
            with self.assertRaises(HTTPException):
                self.engine.save_rule(self.rule.model_copy(update=change))

    def test_api_authentication_and_crud(self):
        def auth(request: Request):
            if request.headers.get('x-test-auth') != 'yes': raise HTTPException(401)
        app = FastAPI()
        app.include_router(automation_router(self.engine, auth))
        with TestClient(app) as client:
            path = '/api/zigbee/automations'
            for method in ['get', 'post', 'put', 'delete']:
                url = path + ('/' + self.id if method in ['put', 'delete'] else '')
                self.assertEqual(getattr(client, method)(url).status_code, 401)
            client.headers['x-test-auth'] = 'yes'
            result = client.post(path, json=self.rule.model_dump())
            self.assertEqual(result.status_code, 201)
            rule_id = result.json()['id']
            self.assertEqual(client.put(path+'/'+rule_id, json={**self.rule.model_dump(), 'seconds':0}).status_code, 422)
            self.assertEqual(client.delete(path+'/'+rule_id).status_code, 200)
            self.assertEqual(len(client.get(path).json()['rules']), 1)

    def test_occupancy_holds_until_false_and_reoccupancy_cancels_off(self):
        self.engine.save_rule(self.rule.model_copy(update={'while_occupied':True}), self.id)
        self.engine.process(self.sensor, {'occupancy':False})
        self.module.act.assert_not_called()
        self.engine.process(self.sensor, {'occupancy':True})
        self.now += 60
        self.engine.process(self.sensor, {'battery':90})
        self.engine.tick()
        self.assertEqual(self.module.act.call_count, 1)
        self.assertIsNone(self.engine.snapshot()['rules'][0]['off_at'])
        self.engine.process(self.sensor, {'occupancy':False})
        first_due = self.engine.pending[self.target]['due']
        self.now += 2
        self.engine.process(self.sensor, {'occupancy':False})
        self.assertEqual(self.engine.pending[self.target]['due'], first_due)
        self.engine.process(self.sensor, {'occupancy':True})
        self.now += 5
        self.engine.tick()
        self.assertTrue(self.module.act.call_args.args[1].value)
        self.engine.process(self.sensor, {'occupancy':False})
        self.now += 4
        self.engine.tick()
        self.assertTrue(self.module.act.call_args.args[1].value)
        self.now += 1
        self.engine.tick()
        self.assertFalse(self.module.act.call_args.args[1].value)

    def test_occupancy_hold_and_false_countdown_survive_restart(self):
        self.engine.save_rule(self.rule.model_copy(update={'while_occupied':True}), self.id)
        self.engine.process(self.sensor, {'occupancy':True})
        self.now += 30
        recovered = Automations(self.prefs, self.module, clock=lambda:self.now)
        recovered.start()
        try:
            recovered.tick()
            self.assertTrue(recovered.holds)
            recovered.process(self.sensor, {'occupancy':False})
        finally:
            recovered.stop()
        self.now += 5
        done = threading.Event()
        self.module.act.side_effect = lambda target, request: done.set() if request.value is False else None
        restarted = Automations(self.prefs, self.module, clock=lambda:self.now)
        restarted.start()
        try:
            self.assertTrue(done.wait(2))
        finally:
            restarted.stop()

    def test_shared_target_does_not_turn_off_while_any_sensor_is_occupied(self):
        self.engine.save_rule(self.rule.model_copy(update={'while_occupied':True}), self.id)
        self.engine.save_rule(self.rule.model_copy(update={'property':'action', 'equals':'single', 'seconds':20}))
        self.engine.process(self.sensor, {'occupancy':True})
        self.engine.process(self.sensor, {'action':'single'})
        self.now += 25
        self.engine.tick()
        self.assertTrue(self.module.act.call_args.args[1].value)
        self.engine.process(self.sensor, {'occupancy':False})
        self.now += 5
        self.engine.tick()
        self.assertFalse(self.module.act.call_args.args[1].value)

    def test_disabling_or_deleting_held_rule_schedules_cleanup(self):
        for delete in (False, True):
            self.engine.save_rule(self.rule.model_copy(update={'while_occupied':True}), self.id)
            self.engine.process(self.sensor, {'occupancy':True})
            if delete:
                self.engine.delete(self.id)
            else:
                self.engine.save_rule(self.rule.model_copy(update={'enabled':False, 'while_occupied':True}), self.id)
            self.assertFalse(self.engine.holds)
            self.now += 5
            self.engine.tick()
            self.assertFalse(self.module.act.call_args.args[1].value)

    def test_two_occupancy_sensors_hold_until_both_are_clear(self):
        objects = self.module.objects()
        second_sensor = next(obj for obj in objects if obj.id == self.sensor).model_copy(update={'id':'zigbee.second-sensor'})
        self.module.objects = Mock(return_value=objects + [second_sensor])
        self.engine.save_rule(self.rule.model_copy(update={'while_occupied':True}), self.id)
        self.engine.save_rule(self.rule.model_copy(update={'source':second_sensor.id, 'while_occupied':True}))
        self.engine.process(self.sensor, {'occupancy':True})
        self.engine.process(second_sensor.id, {'occupancy':True})
        self.engine.process(self.sensor, {'occupancy':False})
        self.now += 10
        self.engine.tick()
        self.assertTrue(self.module.act.call_args.args[1].value)
        self.engine.process(second_sensor.id, {'occupancy':False})
        self.now += 5
        self.engine.tick()
        self.assertFalse(self.module.act.call_args.args[1].value)

    def test_occupancy_mode_rejects_nonoccupancy_and_false_triggers(self):
        for changes in ({'equals':False}, {'property':'action', 'equals':'single'}, {'property':'battery', 'equals':90}):
            with self.assertRaises(HTTPException):
                self.engine.save_rule(self.rule.model_copy(update={**changes, 'while_occupied':True}), self.id)


if __name__ == '__main__': unittest.main()
