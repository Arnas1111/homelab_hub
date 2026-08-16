# Homelab Hub – Docker/Unraid MVP

A self-hosted web dashboard for managing Docker containers on an Unraid host.

## Current features

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

### 2. Create the container through the normal Unraid WebUI

Go to:

```text
Docker -> Add Container -> Template -> Homelab-Hub
```

Set at least:

- **Admin Password** – password for the Hub WebUI.
- **Session Secret** – a long random value. Generate one in the Unraid terminal with `openssl rand -hex 32`.
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

Live integration credentials are runtime-only environment variables in the Unraid template. Do not commit real values to this repository.

- `HUB_JELLYFIN_API_KEY` enables the active Jellyfin streams card. `HUB_JELLYFIN_URL` is optional when the Jellyfin container publishes TCP 8096/8920 and can be discovered from Docker. `HUB_JELLYFIN_PUBLIC_URL` controls the Open link.
- `HUB_NEXTCLOUD_CALENDAR_URL` accepts a public Nextcloud ICS export/subscription URL for the weekly agenda card.
- `HUB_HOME_ASSISTANT_URL`, `HUB_HOME_ASSISTANT_TOKEN`, and `HUB_HOME_ASSISTANT_ENTITIES` enable Home Assistant sensors and `light.*` toggles. In Home Assistant, create a long-lived access token from your user profile page, then paste it into the masked Unraid field.

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
