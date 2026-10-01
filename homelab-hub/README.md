# Homelab Hub – Docker/Unraid MVP

A self-hosted web dashboard for managing Docker containers on an Unraid host.

The workspace now separates Home, Services, Containers, Metrics, History and Integrations. Home shows favorites, capacity and container alerts; Services automatically discovers applications from Docker metadata and Unraid/ Homepage display labels. Background collectors keep resource sampling off the opening request path.

See the [dashboard concept and research](DASHBOARD_CONCEPT.md) for design decisions, supported discovery labels, collection behavior and the roadmap.

### Unraid telemetry

Open **Connections** and save your Unraid server URL and an API key with Info and Array read permissions. **Integrations** then shows hardware, array state and disk temperatures. Docker discovery works through the existing socket mount without this API key. Unraid API readings are live snapshots; PostgreSQL history currently stores host/container performance metrics. Environment defaults are `HUB_UNRAID_URL` and `HUB_UNRAID_API_KEY`.

In **Services**, pin applications for Home, search with Ctrl/Cmd+K, or use **Manage links** to override a URL. Favorites are shared by this Hub and persisted under `/data`. Explicit URLs are useful for host networking, dedicated container IPs or reverse proxies.

## Current features

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

Open **Settings -> Connectors** in Homelab Hub to configure Jellyfin, Nextcloud, and Home Assistant. Secret fields are not echoed back to the browser; leave them blank to keep the saved value or use the clear checkbox to remove them.

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

Every workspace section has a bookmarkable URL: `/home`, `/services`, `/containers`,
`/metrics`, `/history`, `/integrations`, `/logs`, `/zigbee`, `/automations`, `/settings`,
`/connectors`, and `/database`. `/` still opens Home. Reload and browser back/forward
restore the selected section; signing in returns to the requested section.

Open **Automations** (also linked from Settings) to configure a rule without Docker
environment variables. For example: select a motion sensor, `occupancy = true`, a
light, and `5` seconds. Each fresh matching report turns the target on and extends
its switch-off timer. The Hub executes rules without an open browser. Rules can be
edited, disabled or deleted. Button devices with an exposed `action` enum support
rules such as `action = single` using the same editor.

Rules and pending switch-off deadlines persist in `/data/hub.db`. Retained MQTT
messages are ignored for triggering; unrelated partial reports do not retrigger.
After a Hub restart, overdue switch-offs are attempted when Zigbee is reachable.
Failed switch-offs retry every five seconds; failed activations are not replayed.
Disabling/deleting a rule does not cancel an existing switch-off. Rules sharing a
target use the latest deadline. Manual control does not cancel that deadline.

This first version supports sensor/button equality triggers and one timed on/off
target per rule (1 second to 24 hours), with up to 100 rules. Timers run on the Hub,
so an outage may delay switch-off. Status reports command delivery, not guaranteed
physical device state. Zigbee2MQTT and the MQTT broker must remain reachable.
