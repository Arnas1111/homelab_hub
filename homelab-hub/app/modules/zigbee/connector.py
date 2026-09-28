"""Bounded in-memory Zigbee discovery and one reconnecting MQTT network thread."""
import json
import math
import os
import re
import threading
from datetime import datetime, timezone
from urllib.parse import quote

from app.core.objects import ActionRequest, Capability, HubObject


class ZigbeeModule:
    id = "zigbee"

    def __init__(self, environ=None):
        env = os.environ if environ is None else environ
        self.host = env.get("HUB_MQTT_HOST", "").strip()
        self.port = env.get("HUB_MQTT_PORT", "1883")
        self.username = env.get("HUB_MQTT_USERNAME", "")
        self.password = env.get("HUB_MQTT_PASSWORD", "")
        self.tls = env.get("HUB_MQTT_TLS", "false").lower() == "true"
        self.base = env.get("HUB_ZIGBEE_BASE_TOPIC", "zigbee2mqtt").strip("/")
        self.lock = threading.RLock()
        self.client = None
        self.connected = False
        self.bridge_online = False
        self.status = "disabled" if not self.host else "connecting"
        self.devices = {}
        self.states = {}
        self.availability = {}
        self.updated = {}

    def start(self):
        if not self.host or self.client is not None:
            return
        try:
            import paho.mqtt.client as mqtt
            if not self.base or any(c in self.base for c in "#+\x00"):
                raise ValueError("Invalid base topic")
            port = int(self.port)
            if not 1 <= port <= 65535:
                raise ValueError("Invalid port")
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            client.max_queued_messages_set(20)
            if self.username:
                client.username_pw_set(self.username, self.password)
            if self.tls:
                client.tls_set()
            client.on_connect = self._connect
            client.on_disconnect = self._disconnect
            client.on_connect_fail = self._connect_failed
            client.on_message = self._message
            client.on_subscribe = self._subscribed
            client.reconnect_delay_set(min_delay=1, max_delay=60)
            self.client = client
            client.connect_async(self.host, port, keepalive=30)
            client.loop_start()
        except Exception:
            self.status = "configuration_error"
            self.stop()

    def stop(self):
        client, self.client = self.client, None
        if client:
            client.disconnect()
            client.loop_stop()
        with self.lock:
            self.connected = False
            self.bridge_online = False

    def _connect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.connected = not reason_code.is_failure
            self.bridge_online = False
            self.availability.clear()
            self.status = "connected" if self.connected else "connection_failed"
        if self.connected:
            result, _ = client.subscribe(f"{self.base}/#", qos=0)
            if result != 0:
                with self.lock:
                    self.connected = False
                    self.status = "subscription_failed"

    def _disconnect(self, client, userdata, flags, reason_code, properties):
        with self.lock:
            self.connected = False
            self.bridge_online = False
            self.status = "disconnected"

    def _subscribed(self, client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            with self.lock:
                self.connected = False
                self.status = "subscription_failed"

    def _connect_failed(self, client, userdata):
        with self.lock:
            self.status = "connection_failed"

    def _message(self, client, userdata, message):
        # Invalid external payloads must never terminate the MQTT loop.
        try:
            self.ingest(message.topic, message.payload)
        except Exception:
            pass

    def ingest(self, topic, payload):
        if len(payload) > 2_000_000 or not topic.startswith(self.base + "/"):
            return
        suffix = topic[len(self.base) + 1:]
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeError):
            return
        with self.lock:
            if suffix == "bridge/state":
                self.bridge_online = (data.get("state") if isinstance(data, dict) else data) == "online"
            elif suffix == "bridge/devices" and isinstance(data, list):
                devices = {}
                for device in data[:2000]:
                    try:
                        devices.update(self._discover(device))
                    except (ValueError, TypeError, KeyError, AttributeError):
                        continue
                self.devices = devices
                names = {d["topic"] for d in devices.values()}
                self.states = {k: v for k, v in self.states.items() if k in names}
                self.updated = {k: v for k, v in self.updated.items() if k in names}
                self.availability = {k: v for k, v in self.availability.items() if k in names}
                # Subscribe again to obtain retained states even if broker sent
                # them before the discovery message, or a device was renamed.
                if self.client and names:
                    self.client.subscribe([(f"{self.base}/{name}", 0) for name in sorted(names)])
                    self.client.subscribe([(f"{self.base}/{name}/availability", 0) for name in sorted(names)])
            else:
                names = {d["topic"] for d in self.devices.values()}
                if suffix in names and isinstance(data, dict):
                    # Store only properties used by discovered objects.
                    allowed = {f["property"] for d in self.devices.values() if d["topic"] == suffix
                               for f in d["features"].values()}
                    self.states.setdefault(suffix, {}).update({k: v for k, v in data.items() if k in allowed})
                    self.updated[suffix] = datetime.now(timezone.utc).isoformat()
                elif suffix.endswith("/availability") and suffix[:-13] in names:
                    self.availability[suffix[:-13]] = (data.get("state") if isinstance(data, dict) else data) == "online"

    def _discover(self, device):
        if not isinstance(device, dict) or device.get("type") == "Coordinator":
            return {}
        ieee = device.get("ieee_address", "")
        name = device.get("friendly_name", "")
        if not re.fullmatch(r"0x[0-9a-fA-F]{16}", ieee) or not isinstance(name, str) or not name:
            return {}
        if any(c in name for c in "#+\x00") or name.startswith("bridge/"):
            return {}
        result = {}
        for expose in (device.get("definition") or {}).get("exposes", []):
            if not isinstance(expose, dict) or expose.get("type") != "light":
                continue
            features = {}
            for feature in expose.get("features", []):
                key = {"state": "power", "brightness": "brightness"}.get(feature.get("name"))
                if key and isinstance(feature.get("property"), str) and type(feature.get("access")) is int:
                    if key == "brightness":
                        low, high = feature.get("value_min", 0), feature.get("value_max", 254)
                        if not all(type(v) in (int, float) and math.isfinite(v) for v in (low, high)) or low >= high:
                            continue
                    features[key] = feature
            if not features:
                continue
            endpoint = str(expose.get("endpoint", ""))
            object_id = f"zigbee.{ieee.lower()}" + (f".{quote(endpoint, safe='')}" if endpoint else "")
            result[object_id] = {"topic": name, "name": name + (f" ({endpoint})" if endpoint else ""), "features": features}
        return result

    def describe(self):
        with self.lock:
            status = self.status
            if self.connected:
                status = "online" if self.bridge_online else "bridge_offline"
            return {"id": self.id, "name": "Zigbee", "status": status,
                    "object_types": ["light"], "capabilities": ["power", "brightness"],
                    "object_count": len(self.devices)}

    def objects(self):
        with self.lock:
            result = []
            for object_id, device in self.devices.items():
                state, capabilities, actions = {}, {}, []
                raw = self.states.get(device["topic"], {})
                for key, feature in device["features"].items():
                    writable = bool(feature["access"] & 2)
                    capabilities[key] = Capability(type="boolean" if key == "power" else "number", writable=writable,
                                                   unit="%" if key == "brightness" else None,
                                                   minimum=0 if key == "brightness" else None,
                                                   maximum=100 if key == "brightness" else None)
                    if writable:
                        actions.append(f"set_{key}")
                    value = raw.get(feature["property"])
                    if key == "power" and value is not None:
                        if value == feature.get("value_on", "ON"):
                            state[key] = True
                        elif value == feature.get("value_off", "OFF"):
                            state[key] = False
                    elif key == "brightness" and type(value) in (int, float) and math.isfinite(value):
                        low, high = feature.get("value_min", 0), feature.get("value_max", 254)
                        state[key] = round(max(0, min(100, (value - low) * 100 / (high - low))), 1)
                result.append(HubObject(id=object_id, module=self.id, type="light", name=device["name"],
                                        available=self.connected and self.bridge_online and self.availability.get(device["topic"], True),
                                        state=state, capabilities=capabilities, actions=actions,
                                        updated_at=self.updated.get(device["topic"])))
            return result

    def act(self, object_id: str, request: ActionRequest):
        with self.lock:
            device = self.devices[object_id]
            key = {"set_power": "power", "set_brightness": "brightness"}.get(request.action)
            feature = device["features"].get(key)
            if feature is None or not feature["access"] & 2:
                raise ValueError("Unsupported action")
            value = request.value
            if key == "power":
                if type(value) is not bool:
                    raise ValueError("Expected boolean")
                value = feature.get("value_on", "ON") if value else feature.get("value_off", "OFF")
            else:
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
                    raise ValueError("Expected percentage")
                low, high = feature.get("value_min", 0), feature.get("value_max", 254)
                value = round(low + value * (high - low) / 100)
            if not self.client or not self.connected or not self.bridge_online or not self.availability.get(device["topic"], True):
                raise RuntimeError("Unavailable")
            # QoS 0 deliberately avoids replaying queued actuator commands after
            # reconnect. Device reports, never this publish, update API state.
            info = self.client.publish(f"{self.base}/{device['topic']}/set",
                                       json.dumps({feature["property"]: value}), qos=0, retain=False)
            if info.rc != 0:
                raise RuntimeError("Publish failed")
        info.wait_for_publish(timeout=2)
        if not info.is_published():
            raise RuntimeError("Publish timed out")
        return {"status": "sent", "object_id": object_id, "action": request.action}
