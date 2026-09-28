"""Discovery, protocol mapping and authenticated generic API without hardware."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1]))
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from app.core.objects import ActionRequest, ModuleRegistry, object_router
from app.modules.zigbee.connector import ZigbeeModule


def light(name="Living room", endpoint=None, access=7):
    expose = {"type": "light", "features": [
        {"name": "state", "property": "state", "access": access, "value_on": "ON", "value_off": "OFF"},
        {"name": "brightness", "property": "brightness", "access": access, "value_min": 0, "value_max": 254}]}
    if endpoint:
        expose["endpoint"] = endpoint
        for feature in expose["features"]:
            feature["property"] += "_" + endpoint
    return {"ieee_address": "0x0011223344556677", "friendly_name": name, "definition": {"exposes": [expose]}}


class ZigbeeTests(unittest.TestCase):
    def setUp(self):
        self.module = ZigbeeModule({"HUB_MQTT_HOST": "broker", "HUB_MQTT_PASSWORD": "PRIVATE"})
        self.module.client = Mock()
        self.module.client.publish.return_value.rc = 0
        self.module.client.publish.return_value.is_published.return_value = True
        self.module.connected = True
        self.feed("bridge/state", {"state": "online"})
        self.feed("bridge/devices", [light()])
        self.id = self.module.objects()[0].id

    def feed(self, topic, value):
        self.module.ingest("zigbee2mqtt/" + topic, json.dumps(value).encode())

    def test_discovery_state_and_partial_reports(self):
        self.feed("Living room", {"state": "ON", "brightness": 127})
        self.feed("Living room", {"state": "OFF"})
        obj = self.module.objects()[0]
        self.assertEqual(obj.state, {"power": False, "brightness": 50})
        self.assertTrue(obj.available)
        self.assertIsNotNone(obj.updated_at)
        self.assertEqual(obj.capabilities["brightness"].unit, "%")
        self.assertNotIn("PRIVATE", json.dumps(self.module.describe()))

    def test_publish_percentage_and_no_optimistic_state(self):
        self.module.act(self.id, ActionRequest(action="set_brightness", value=100))
        self.module.client.publish.assert_called_once_with('zigbee2mqtt/Living room/set', '{"brightness": 254}', qos=0, retain=False)
        self.assertEqual(self.module.objects()[0].state, {})
        self.module.act(self.id, ActionRequest(action="set_power", value=False))
        self.assertEqual(json.loads(self.module.client.publish.call_args.args[1]), {"state": "OFF"})

    def test_invalid_commands_never_publish(self):
        for value in [True, "50", -1, 101, None, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                self.module.act(self.id, ActionRequest(action="set_brightness", value=value))
        for value in [1, "ON", None]:
            with self.assertRaises(ValueError):
                self.module.act(self.id, ActionRequest(action="set_power", value=value))
        self.module.client.publish.assert_not_called()

    def test_rename_removal_and_endpoint(self):
        self.feed("bridge/devices", [light("Renamed")])
        self.assertEqual(self.module.objects()[0].id, self.id)
        self.module.act(self.id, ActionRequest(action="set_power", value=True))
        self.assertEqual(self.module.client.publish.call_args.args[0], 'zigbee2mqtt/Renamed/set')
        self.feed("bridge/devices", [light("Multi", endpoint="left")])
        obj = self.module.objects()[0]
        self.assertTrue(obj.id.endswith(".left"))
        self.module.act(obj.id, ActionRequest(action="set_power", value=True))
        self.assertEqual(json.loads(self.module.client.publish.call_args.args[1]), {"state_left": "ON"})
        self.feed("bridge/devices", [])
        self.assertEqual(self.module.objects(), [])

    def test_readonly_unknown_and_malformed_devices(self):
        self.feed("bridge/devices", [None, {"definition": None}, light(access=1)])
        self.assertEqual(self.module.objects()[0].actions, [])
        with self.assertRaises(ValueError):
            self.module.act(self.id, ActionRequest(action="set_power", value=True))
        self.module._message(None, None, Mock(topic="zigbee2mqtt/bridge/devices", payload=b'{broken'))
        self.assertEqual(len(self.module.objects()), 1)

    def test_disconnect_availability_and_recovery(self):
        self.feed("Living room/availability", {"state": "offline"})
        self.assertFalse(self.module.objects()[0].available)
        with self.assertRaises(RuntimeError):
            self.module.act(self.id, ActionRequest(action="set_power", value=True))
        self.feed("Living room/availability", {"state": "online"})
        self.module._disconnect(None, None, None, None, None)
        self.assertFalse(self.module.objects()[0].available)
        self.module.client.subscribe.return_value = (0, 1)
        self.module._connect(self.module.client, None, None, Mock(is_failure=False), None)
        self.assertFalse(self.module.objects()[0].available)
        self.feed("bridge/state", {"state": "online"})
        self.assertTrue(self.module.objects()[0].available)

    def test_failed_publish_and_ack_timeout(self):
        self.module.client.publish.return_value.rc = 4
        with self.assertRaises(RuntimeError):
            self.module.act(self.id, ActionRequest(action="set_power", value=True))
        self.module.client.publish.return_value.rc = 0
        self.module.client.publish.return_value.is_published.return_value = False
        with self.assertRaises(RuntimeError):
            self.module.act(self.id, ActionRequest(action="set_power", value=True))

    def test_disabled_and_bad_configuration_are_contained(self):
        module = ZigbeeModule({})
        module.start()
        self.assertEqual(module.describe()["status"], "disabled")
        module = ZigbeeModule({"HUB_MQTT_HOST": "broker", "HUB_MQTT_PORT": "bad"})
        module.start()
        self.assertEqual(module.describe()["status"], "configuration_error")

    def test_authenticated_api_validation_and_failure_isolation(self):
        registry = ModuleRegistry()
        registry.register(self.module)
        broken = Mock(id="broken")
        broken.objects.side_effect = RuntimeError("PRIVATE")
        broken.describe.side_effect = RuntimeError("PRIVATE")
        registry.register(broken)
        def auth(request: Request):
            if request.cookies.get("session") != "test":
                raise HTTPException(401)
        app = FastAPI()
        app.include_router(object_router(registry, auth))
        with TestClient(app) as client:
            for url in ["/modules", "/objects", f"/objects/{self.id}"]:
                self.assertEqual(client.get("/api/v1" + url).status_code, 401)
            url = f"/api/v1/objects/{self.id}/actions"
            self.assertEqual(client.post(url, json={"action": "set_power", "value": True}).status_code, 401)
            client.cookies.set("session", "test")
            self.assertEqual(len(client.get('/api/v1/objects').json()['objects']), 1)
            self.assertNotIn("PRIVATE", client.get('/api/v1/modules').text)
            self.assertEqual(client.get('/api/v1/objects/missing.id').status_code, 404)
            self.assertEqual(client.get('/api/v1/objects?module=missing').json(), {"objects": []})
            self.assertEqual(client.post(url, json={"action": "set_power", "value": True}).status_code, 202)
            self.assertEqual(client.post(url, json={"action": "set_power", "value": "true"}).status_code, 422)
            self.assertEqual(client.post(url, json={"action": "reboot", "value": True}).status_code, 422)
            self.module.client.publish.side_effect = RuntimeError("PRIVATE")
            response = client.post(url, json={"action": "set_power", "value": True})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("PRIVATE", response.text)
