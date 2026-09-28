# Architecture and staged integration plan

## Repository baseline

The application is Python/FastAPI, served by Uvicorn in a Python 3.12 Docker image.
`app/main.py` composes the application, serves Jinja templates and static files,
owns signed-cookie login, SQLite settings, Docker controls, host measurements and
several HTTP integrations. SQLite and icons live under `/data`; Docker uses the
existing socket mount. PostgreSQL is optional and stores metric history only.
The frontend is plain JavaScript and CSS, with a shared API helper and polling.
No frontend build step or SPA framework is present.

Already extracted:

| Area | Responsibility | Remaining coupling |
| --- | --- | --- |
| `core/snapshot.py` | Nonblocking, single-flight cache | Collectors composed in main |
| `modules/docker/discovery.py` | Inventory, service URLs, metadata | Controls, statistics and routes in main |
| `modules/unraid/connector.py` | Unraid HTTP telemetry | Settings and routes in main |
| `modules/metrics/` | PostgreSQL history and sampling | Routes/configuration composed in main |
| `modules/logs/collector.py` | Log collection, severity, filtering | Routes/cache in main; current workspace work preserved |
| `static/board.js`, `history.js`, `logs.js` | Focused frontend features | Shared helpers/navigation in app.js |

Home Assistant light controls, Jellyfin and legacy Nextcloud settings are still
in main. They are separate from the new Zigbee integration. FileBrowser Quantum
and hosted WebCal are roadmap items, not implemented modules. The actual Unraid
template currently defaults to host port **3333**, container port **8080**.

## First milestone implemented

`core/objects.py` defines `HubObject`, `Capability`, `ActionRequest`, a small
explicit registry and an authenticated API router. `modules/zigbee/connector.py`
implements that provider contract. Composition in main registers Zigbee and
starts/stops its MQTT connection alongside existing services. No package scanning,
plugin loader, additional database or framework is needed.

The v1 registry currently contains **Zigbee only**. Existing Docker, Unraid,
metrics and logs continue using their existing APIs; they are not falsely
advertised as migrated object providers. New providers register an ID, module
description, object snapshot and action handler. Their object IDs must begin
with `<module>.`. Per-provider failures are contained during discovery.

Objects expose a stable ID, module, type, display name, availability, last report
time, state, capability metadata and allowed action names. Brightness is always
0–100 percent; `power` is a boolean. Unknown state is omitted, never fabricated.
Zigbee identities use IEEE addresses plus optional endpoint, independent of
friendly name. One device can therefore expose multiple light objects. Only
light power/brightness are mapped in this milestone; feature access bits govern
whether actions are offered. MQTT property names and raw ranges remain inside
the provider.

The MQTT loop runs in one background thread with reconnect backoff. Object
snapshots and discovery/state mutation share a lock. API reads never connect to
the broker. Lost MQTT/bridge/device connectivity marks objects unavailable;
last reported values remain visible. State is in memory and repopulates from
Zigbee2MQTT after restart. Without per-device availability reports, availability
means the bridge is reachable, not that an individual bulb has been probed.

The browser uses the same v1 object/action API intended for future clients.
Cards keep their DOM and active controls during refresh. Existing login applies
to all new endpoints. API-key management is intentionally deferred: Android
needs revocable/scoped credentials, not a second use of the administrator password.

## Refactoring and integration sequence

1. **Current:** isolate Zigbee, establish generic object/action contract, deliver
   discovery → REST → WebUI → power/brightness. Validate offline and with real hardware.
2. **Sensors:** map read-only exposed measurements, units, multiple capabilities,
   state freshness and sensor subtype semantics; reuse existing object endpoints.
3. **Groups:** discover group membership, define group availability and partial
   action results; add all-off/all-100% using supported capabilities.
4. **Existing providers:** extract Docker route/service boundaries under regression
   coverage, then adapt inventory/actions to `docker_container` objects. Adapt
   Unraid to `server` objects. Preserve old endpoints through compatibility routes.
5. **Widget discovery:** add `/api/v1/widgets` describing renderable types and
   required capabilities; implement compatibility matching independently of Zigbee.
6. **External access:** scoped/revocable API tokens, API contract/version tests,
   explicit freshness and action acknowledgement semantics where supported.
7. **Android:** native widget host/configurator consuming only objects,
   capabilities, state and actions. No MQTT, Zigbee or WebView dependency.

Color temperature/RGB and writable capability schemas can extend the light
contract after this milestone. `/api/v1/widgets`, sensors, groups and Android
are deliberately not placeholder implementations.

## Validation boundaries

`tests/test_zigbee.py` covers discovery, partial state, stable IDs, endpoint
mapping, range/access validation, disconnect recovery, publish failure and API
authentication/isolation using a fake MQTT client. Existing Python and Node
regressions remain part of CI. Hardware acceptance requires a reachable broker,
a running Zigbee2MQTT instance and a paired lamp; see [ZIGBEE.md](ZIGBEE.md).

Local validation for this milestone: 43 Python tests completed (41 passed,
2 PostgreSQL integration tests skipped because no test database was configured),
10 Node regression tests passed, and all four browser suites passed with
headless Edge (Zigbee, dashboard, history, logs). JavaScript syntax, Python
compilation, both Unraid XML templates and `git diff --check` passed. Browser
fixtures cover desktop/mobile layouts, object actions, retained DOM, device
reports, removal and outage recovery; no real MQTT broker or lamp was accessed.
