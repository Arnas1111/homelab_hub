# Homelab Hub – Docker/Unraid MVP

A self-hosted web dashboard for managing Docker containers on an Unraid host.

The workspace separates Home, Containers, Metrics, History and Integrations. Home shows favorites and performance; Containers discovers Docker services from metadata and Unraid/Homepage display labels. Background collectors keep resource sampling off the opening request path.

See the [dashboard concept and research](DASHBOARD_CONCEPT.md) for design decisions, supported discovery labels, collection behavior and the roadmap.

### Unraid telemetry

Open **Connections** and save your Unraid server URL and an API key with Info and Array read permissions. **Integrations** then shows hardware, array state and disk temperatures. Docker discovery works through the existing socket mount without this API key. Unraid API readings are live snapshots; PostgreSQL history currently stores host/container performance metrics. Environment defaults are `HUB_UNRAID_URL` and `HUB_UNRAID_API_KEY`.

In **Services → Containers**, pin containers to place them on the visible tile dashboard; open **All containers** to find everything else. Drag selected tiles to reorder them. **Resource and port details** opens the full Docker table and port view. Ctrl/Cmd+K opens container search. **+ Add tile** creates a standalone link with a Web UI URL and built-in icon; suggestions include Unraid, Automations, Zigbee devices, Home Assistant, Node-RED, monitoring, backups, and files. Unraid uses the configured server URL when available. Automation and Zigbee suggestions link to the Hub's own pages. Standalone tiles open links and do not imply monitored availability. Use **Add Web UI / Edit Web UI** directly on a container tile to set its URL and icon. **Edit tile** changes or deletes standalone tiles. Favorites and tiles persist under `/data` and are shared by this Hub.

## Current features

- Container Web UI defaults now include unknown apps with published TCP ports. Common HTTP/HTTPS ports are preferred; obvious SSH/database ports, UDP and loopback-only bindings are excluded. Explicit Web UI labels and saved URLs take priority. Wildcard bindings use the configured Unraid hostname or the Hub hostname; **Settings → Default container Web UI links** offers a host override and an enable switch. These are editable URL suggestions, not availability checks. Host-network containers without published mappings still need an explicit URL.

- **Settings → Appearance → Theme** selects **Homelab dark**, **Artcraft-inspired light**, or **Artcraft-inspired dark**. Both Artcraft variants share grid borders, bold headings and colorful navigation/metric accents; the dark variant uses charcoal surfaces and brighter accent colors. Changes preview immediately; **Save theme** persists the selection under `/data`, and **Cancel preview** restores the saved theme. Logo and favicon uploads remain in the same panel. This feature is part of Homelab Hub, independent of the discontinued Unraid Control experiment.

- Settings includes Zigbee/MQTT setup, custom logo/favicon uploads, administrator password changes, and entry points to service connections and history storage. Changes persist under `/data`.
- Fresh installations need no feature credentials or manually supplied session secret: open the Hub and create the administrator password. Existing `HUB_ADMIN_PASSWORD` remains valid until you change the password in Settings. The session key is generated and persisted automatically when `HUB_SESSION_SECRET` is absent.

Configure a fresh Hub before exposing it to other users: the first completed setup creates its administrator. Changing the password invalidates existing login sessions. Logo and favicon uploads accept PNG/JPEG/WebP up to 512 KB each and appear on the login page as well. MQTT credentials are stored locally in the appdata database and are not returned by settings APIs; protect `/data` and its backups.

Container ports, network attachment, USB/Docker device access and the `/data` volume remain deployment settings. All new feature configuration belongs in the Hub Settings UI; environment variables are optional provisioning defaults.

- Zigbee2MQTT capability-based device cards with power, brightness, color, white temperature, effects and sensor readings; saved room/category groups and type filters — [setup and API](ZIGBEE.md), [architecture and integration plan](ARCHITECTURE.md)

- Central container **Logs** page with error/warning detection, service/time/text filters, context and collection coverage — [scope and setup](LOGS.md)

- Dedicated CPU, memory, storage, network and container history pages
- Optional PostgreSQL 18 background metrics storage with connection setup, retention and historical charts — [setup guide](HISTORY.md)

- Password-protected Web UI
- Docker host overview
- Container state, health, image and published ports
- Per-container CPU and memory usage
- Start / stop / restart / pause / unpause containers
- Tail container logs
- Search/filter containers
- Settings stored in SQLite
- Configurable dashboard title, refresh interval and confirmation prompts

## Recommended deployment on Unraid: native XML template

This project includes a normal Unraid Docker user template:

```text
unraid/my-homelab-hub.xml
```

The template pulls the published image:

```text
ghcr.io/arnas1111/homelab-hub:latest
```

GitHub Actions publishes that image automatically when changes are pushed to `main`.
The Unraid template includes Docker's `--pull=always` policy so recreating/applying the container fetches the current `latest` image instead of reusing a stale local image.

### 1. Install the Unraid template

Copy or install this template in Unraid:

```text
unraid/my-homelab-hub.xml
```

Or, from a clone/copy of this repository on the Unraid server, import only the template without building anything:

```bash
./import-unraid-template.sh
```

The importer installs only the basic Docker template. Live integrations are configured inside Homelab Hub.

### 2. Create the container through the normal Unraid WebUI

Go to:

```text
Docker -> Add Container -> Template -> Homelab-Hub
```

Review these deployment options:

- **Admin Password** – optional; leave blank to create an administrator in the first-run setup screen.
- **Session Secret** – optional; the Hub generates and persists one under `/data` when omitted.
- **Server Name** – optional display name, e.g. `Tower`.
- **Network Type** – use `docker-internal` if it is a user-defined internal Docker bridge network.
- **WebUI Port** – defaults to `3333`. This is the host/LAN port; the container target stays `8080`.

Then click **Apply**.

Open:

```text
http://YOUR-UNRAID-IP:3333
```

### Template mappings

```text
Host 3333                   -> Container 8080
/mnt/user/appdata/homelab-hub -> /data
/var/run/docker.sock        -> /var/run/docker.sock (rw)
```

The Docker socket is intentionally read/write because Homelab Hub needs Docker Engine write access for Start/Stop/Restart/Pause actions.

### Network isolation

If you want Homelab Hub reachable as `http://UNRAID-IP:3333` but unable to initiate outbound internet traffic, attach it to a user-defined internal Docker bridge network such as `docker-internal`.

Do not use a `br0`/macvlan/ipvlan network with a fixed container IP for this mode. That makes the container behave like a separate LAN device and the WebUI will be reached via the container's own IP instead of the Unraid host IP.

The desired shape is:

```text
Browser -> Unraid IP:3333 -> published Docker port -> Homelab Hub container:8080
Homelab Hub container -> no default outbound internet route
```

## Updating this development build

Push changes to `main`. After GitHub Actions publishes a new `latest` image, update/recreate the container in Unraid. The template includes `--pull=always`, so Docker fetches the current remote `latest` image during recreate/apply.

If you ever want to build directly on Unraid instead, the local installer is still available:

```bash
./unraid-install.sh
```

## Docker Compose deployment (optional)

Compose is still included for testing or deployment outside Unraid:

1. Copy `.env.example` to `.env`.
2. Set a strong `HUB_ADMIN_PASSWORD`.
3. Set a long random `HUB_SESSION_SECRET`.
4. Run:

```bash
docker compose up -d --build
```

## Security

Mounting `/var/run/docker.sock` gives this application administrative control over Docker and effectively powerful control over the Docker host. Do not expose this dashboard directly to the public Internet. Put it behind a trusted reverse proxy/authentication layer if remote access is needed.

The Unraid template stores configured environment values in Unraid's Docker template configuration, so treat the flash/config backup as sensitive when it contains passwords or secrets.

## Optional live integrations

Live integration credentials are stored locally in Homelab Hub's SQLite database under appdata. Do not commit real values to this repository.

Open **Integrations** and press **+ Add integration** to add Unraid, Jellyfin or Home Assistant. Only added connectors appear as cards, with configuration, enable/disable, reconnect and removal controls alongside their live readings. Saving a connector preserves the others; blank secret fields retain saved values. Disabling preserves configuration; removing clears that connector's settings. Existing connections carry over, and old `/connectors` bookmarks open Integrations.

Under **Settings → Login and password**, uncheck **Require password login** and save to open the Hub without signing in. This persists in `/data/access.json`, keeps the administrator password and applies to dashboard and API access. Anyone who can reach the Hub can then use its controls. Turn login back on to require the saved password again; changing this setting invalidates existing sessions.

## Server metrics design

The overview prioritizes CPU and memory trends plus a used/free storage ring. Neutral cards use blue for utilization below 75%, amber from 75%, and red from 90%, with text labels. These thresholds are visual guides, not health alerts. Expand **Resource details** for per-core readings, container rankings and Hub network traffic. Memory rankings compare bytes used. Charts use a fixed 0–100% scale and elapsed time, retaining up to 80 browser samples from the last 30 minutes; longer sampling interruptions appear as gaps.

The layout follows [Grafana's dashboard guidance](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/) on meaningful color and focused views, and [Nielsen Norman Group's chart guidance](https://www.nngroup.com/articles/dashboards-preattentive/) on readable comparisons. The storage ring has just two parts and explicit values; time trends and container comparisons use lines and bars.

See [the implementation review](REVIEW.md) for verified fixes, validation limits and the remaining FileBrowser Quantum, PostgreSQL metrics history and WebCal work. Published builds display their source commit in Settings. Container CPU uses Docker units (100% per logical core); host CPU uses total machine capacity. Network metrics reflect the Hub's network namespace.

Development checks:

```text
node --check app/static/app.js
node --test tests/frontend.test.cjs
python -m compileall -q app
python -m unittest discover -s tests
```

## Planned next integrations

- Unraid API connector (Unraid 7.2+) for array state, disks, shares and system information
- VM management
- Disk temperatures / SMART health
- UPS data
- Notifications / alerts
- Service tiles that contain live information rather than simple bookmarks
- Multiple servers / remote hosts
- Role-based permissions
- Authentik/OIDC login
- Web terminal/exec with explicit permissions (optional)
- Docker update status and image update actions
- Compose stack grouping and stack controls
# Section links and Zigbee automations

Every workspace section has a bookmarkable URL: `/home`, `/containers`,
`/container-details`, `/metrics`, `/history`, `/integrations`, `/logs`, `/zigbee`,
`/automations`, `/settings`, and `/database`. `/services` redirects to Containers;
`/connectors` remains an alias for Integrations. `/` still opens Home. Reload and browser back/forward
restore the selected section; signing in returns to the requested section.

Open **Automations** (also linked from Settings) to configure a rule without Docker
environment variables. For example: select a motion sensor, `occupancy = true`, a
light, and `5` seconds. Each fresh matching report turns the target on and extends
its switch-off timer. The Hub executes rules without an open browser. Rules can be
edited, disabled or deleted. Button devices with an exposed `action` enum support
rules such as `action = single` using the same editor.

For motion sensors, select `occupancy` and check **Keep the light on while occupied**.
The Hub holds the light on while occupancy is true, then starts the configured
switch-off countdown on the first fresh false report. Repeated false reports do
not extend that countdown; a fresh true report cancels it. An occupied rule prevents
other rules from switching off the same target. Holds and deadlines persist across
restarts; a recovered hold waits for a fresh false report. Disabling, deleting or
changing an occupied rule to another target schedules cleanup for its old target.

Check **Only activate when a time condition matches** to limit a sensor/button rule
to before or after a local clock time, sunrise, or sunset. **After this time is true**
allows activation at/after the boundary; unchecked means before. Solar offsets from
-180 to +180 minutes are supported. Boundaries use the current local calendar day
and reset at midnight; this is an activation condition, not a scheduled on/off action.
Existing switch-off timers and occupancy releases always finish regardless of time.

In **Settings → Automation time and solar location**, save your IANA timezone and
editable latitude/longitude (or use the browser's **Use current location** button).
Sunrise and sunset are calculated daily on the Hub using [Astral](https://astral.readthedocs.io/en/latest/package.html),
without an internet API. You can disable solar times or recalculate the preview.
If a solar event is unavailable, the associated rule does not activate; other rules
keep working. Configuration persists under `/data` and follows timezone/DST changes.

The Unraid server name on **Home** opens the Unraid WebUI in a new tab using the
server address saved in its connector. It stays plain text until an address is saved.

Rules and pending switch-off deadlines persist in `/data/hub.db`. Retained MQTT
messages are ignored for triggering; unrelated partial reports do not retrigger.
After a Hub restart, overdue switch-offs are attempted when Zigbee is reachable.
Failed switch-offs retry every five seconds; failed activations are not replayed.
Disabling/deleting a rule does not cancel an existing switch-off. Rules sharing a
target use the latest deadline. Manual control does not cancel that deadline.

Automations support sensor/button equality triggers and occupancy holds, with one
on/off target per rule (1 second to 24 hours), and up to 100 rules. Timers run on the Hub,
so an outage may delay switch-off. Status reports command delivery, not guaranteed
physical device state. Zigbee2MQTT and the MQTT broker must remain reachable.

### Organized workspace and flow automations

The sidebar starts collapsed and groups **Services → Containers**, **Zigbee → Devices /
Automations**, **Performance → History / Logs**, and **Settings → General /
Integrations / Metrics / Metrics storage**. Existing direct section URLs continue
to work.

Home keeps its normal view minimal. **Edit dashboard** opens an in-place canvas:
add modules from the palette, drag existing cards to reorder them, select a card
to set its width and accent, or remove it. Keyboard and touch users can use the
move buttons. Available modules include service search, Performance, Favorites,
a local clock, and an editable note. In edit mode, modules become non-interactive
grid previews; favorite chips can be dragged to reorder them. Save commits
the layout to `/data/hub.db` for all browsers; Cancel restores the previous view.

New Zigbee automations use a two-dimensional flow canvas. Drag an **Item** card
from the discovered Zigbee list, then add and connect **When item reports**, **When
time is reached**, **While item equals/differs/less than/greater than**, **While
time matches**, **Do action**, and **Wait** cards. Select a card to
edit its property, comparison, action, or delay. Item cards set the device context
for following cards, so a light can be a condition as well as an action target.
An action card also has a **Target device** selector; choose the light there
even when its Item card appears later in the flow. Older flows that rely on a
preceding Item card continue to use that context.
For example: motion item → occupancy true → light item → power on → wait 5 seconds
→ light item → power off. Another path can check whether light A is on and turn
off light B. Time cards gate actions using saved timezone/solar settings; place
an **While inside time window** card for a range such as 18:00 until 00:00; ranges crossing
midnight are supported in the saved timezone.

New cards remain disconnected until you connect them. Drag a card to move it;
click to select it, double-click to focus its settings, and press Delete to
remove the selected card. Drag from the small output dot, shown on hover or
selection, onto another card to connect it. Input dots appear while connecting.
Click a wire or focus it and press Delete to remove that connection. The card
palette and canvas help can be collapsed. Keyboard arrow keys still move a
focused card, and the inspector retains a Remove card button.

Drag the empty background to pan. Use the +/− buttons or Ctrl/⌘+wheel to zoom;
**Fit** frames the flow. The canvas has no internal scrollbars. Cards snap to
the grid. Invalid self-links, loops, and incoming clock-trigger links are
rejected before saving; the server also validates each flow. Connection handles
follow the [draw.io hover-and-drag pattern](https://www.drawio.com/docs/manual/editor/panels/connection-points-hide/).
The [code and interface review](IMPROVEMENT_REVIEW.md) records remaining work.

**Programming** in the editor offers a short text form for independent trigger
paths in one automation. Use device names from **Add cards**, for example:

```text
when "Motion sensor".occupancy = true
during 18:00..05:30
do "Hall light".power = on

when "Motion sensor".occupancy = false
during 18:00..05:30
wait 5s
if "Motion sensor".occupancy = false
do "Hall light".power = off
```

Each `when` begins a new trigger path; `at 18:00` starts a clock path. `during`
checks the configured local timezone and supports windows across midnight.
Later `if` lines check the latest device state, and `item "Device"` changes
context for later conditions. Save the automation timezone in Settings first.
Valid edits update the canvas after a short pause. Incomplete or
invalid lines leave the last valid canvas intact and show a line error; Save
requires fixing that error or restoring code from the canvas. Changes made on
a supported set of independent paths update the code too. Forked branches,
solar cards, and other unrepresentable flows remain editable on the canvas; **Start code
draft** keeps the canvas until a valid replacement is entered.

Flows are validated before saving: discovered items and supported capabilities,
matching value types, connected cards, and no cycles. Delayed branches persist
through Hub restarts and retry after connection failures. A repeated trigger
restarts its matching wait card. Conditions use the latest **reported** device
state; a command immediately before a condition may not have a new report yet.
Clock triggers run once per local day during the matching minute and persist
their last fired date across restarts. Comparison cards evaluate the latest
reported state when the flow reaches them; order comparisons require numeric
properties. Earlier timed rules keep running and appear as cards with enable,
disable, and delete controls. Recreate one on the canvas to change its flow.

The Home layout follows Homarr's board/widget separation and Homepage's
configurable sections; service cards retain Heimdall's simple app-launcher role.
The flow canvas uses Node-RED's palette and connected-node idea while retaining
the Hub's validated Zigbee object contract.
