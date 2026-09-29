# Zigbee2MQTT devices

The Zigbee page builds compact cards from device capabilities: power, brightness,
white temperature (mired), color and effects where supported, plus sensor readings,
battery and signal quality. Search or filter by device type. Open **Details & grouping**
on a card, enter a room/category and save; select **Room / category** in the grouping
selector to arrange devices. Assignments persist under `/data`. These are Hub display
groups, not Zigbee multicast groups; commands target individual devices.

The Hub connects to an existing MQTT broker and Zigbee2MQTT installation.
Home Assistant is not required. The coordinator belongs to Zigbee2MQTT, not the
Hub container; keep the Hub's existing `/data` and Docker socket mounts.

## Unraid configuration

Open **Settings → Zigbee / MQTT** in the Hub. Enable the integration and enter
the broker hostname/IP (without a URL prefix), port, username, password, TLS
choice and base topic. **Save and connect** persists the configuration in SQLite
under `/data` and immediately reconnects. **Reconnect saved settings** retries
the stored configuration. No container restart is needed.

Blank password fields retain the saved password; use **Clear saved password** to
remove it. Saved in-app settings take precedence over all MQTT environment
defaults, including an explicitly disabled integration. The environment variables
below remain available for initial provisioning without saved Zigbee settings.
The broker, Zigbee2MQTT and USB device mapping remain separate deployment requirements.

In the Hub container template, configure these environment variables (the
MQTT fields are optional and appear under advanced settings):

| Variable | Default | Meaning |
| --- | --- | --- |
| `HUB_MQTT_HOST` | empty | Broker hostname/IP; empty disables Zigbee |
| `HUB_MQTT_PORT` | `1883` | Broker TCP port |
| `HUB_MQTT_USERNAME` | empty | Optional broker account |
| `HUB_MQTT_PASSWORD` | empty | Account password; never returned by the API |
| `HUB_MQTT_TLS` | `false` | `true` enables certificate-verified TLS; set port explicitly |
| `HUB_ZIGBEE_BASE_TOPIC` | `zigbee2mqtt` | Must match Zigbee2MQTT's MQTT base topic |

Apply/restart the Hub after changing environment defaults. The broker must be reachable
from the Hub's Docker network. A broker on the same internal user-defined bridge
can be addressed by its container name. Existing deployed templates can add
these variables using Unraid's **Add another Path, Port, Variable…**.

Zigbee2MQTT must publish JSON device state and bridge discovery under the same
base topic. The Hub account needs subscribe/read access to `<base>/#` and publish
access to device `<base>/<friendly_name>/set` topics. Pair lights through the
Zigbee2MQTT frontend. The Hub does not install Zigbee2MQTT or permit joining.
Device availability is optional; enable it in Zigbee2MQTT to detect individual
offline devices. Lights, switches and exposed numeric/binary/enum sensor readings are supported.

Open **Zigbee** in the Hub. Connection errors stay on this page. On/Off and the
brightness slider are enabled only when the provider is available. The view
refreshes every five seconds while visible. A sent command does not overwrite
the reported state; a subsequent device message supplies the result.

## API v1

All routes use the existing authenticated `hub_session` cookie. Unauthenticated
requests return 401. No API key is implemented in this milestone.

* `GET /api/v1/modules` → `{ "modules": [...] }` (registered v1 providers only)
* `GET /api/v1/objects?module=zigbee` → `{ "objects": [...] }`
* `GET /api/v1/objects/{id}` → one object, or 404
* `POST /api/v1/objects/{id}/actions` → 202 after sending, 422 for an invalid
  action/value, 503 for unavailable provider/publish failure

Example object (the ID is illustrative):

```json
{
  "id": "zigbee.0x0011223344556677",
  "module": "zigbee",
  "type": "light",
  "name": "Living room",
  "available": true,
  "state": {"power": true, "brightness": 50},
  "capabilities": {
    "power": {"type": "boolean", "writable": true},
    "brightness": {"type": "number", "writable": true, "unit": "%", "minimum": 0, "maximum": 100}
  },
  "actions": ["set_power", "set_brightness"],
  "updated_at": "2026-09-28T10:00:00+00:00"
}
```

Action bodies are `{"action":"set_power","value":true}` or
`{"action":"set_brightness","value":100}`. Booleans and percentages are
strictly validated. The response `{"status":"sent", ...}` means MQTT bytes
were sent, **not** that the lamp acknowledged them. Commands use QoS 0 without
retain so actuator commands are not replayed after reconnection. On an ambiguous
timeout, refresh the reported state before retrying. Brightness changes do not
force a separate power command; power-on behavior depends on the device.

## Hardware acceptance

1. Start broker/Zigbee2MQTT with a paired dimmable lamp; configure and restart Hub.
2. Log in. Confirm **Zigbee** shows online and `/api/v1/objects` lists the lamp.
3. Use On, Off and brightness 50/100%. Confirm physical behavior and subsequent
   reported API values (rounding follows the lamp's raw brightness range).
4. Rename the lamp in Zigbee2MQTT: the Hub name changes, its object ID stays stable.
5. Stop Zigbee2MQTT or broker: controls become unavailable; Docker still works.
   Restart: discovery and controls recover without restarting Hub.
6. Remove a device: it disappears after the next bridge discovery message.

Reference contracts: [Zigbee2MQTT exposes](https://www.zigbee2mqtt.io/guide/usage/exposes.html),
[MQTT topics](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html),
[Paho client lifecycle](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).
Architecture and later phases: [ARCHITECTURE.md](ARCHITECTURE.md).
