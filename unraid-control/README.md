# Unraid Control — independent preview

An original Unraid-focused control center on branch `unraid-control-center`.
Target: **Unraid 7.2.3 with the Unraid API enabled**. This app does not import
Homelab source or Unraid application source. The public GraphQL schema is used
as an interface contract. This preview is **not yet a complete replacement for
the native Unraid WebUI**.

## Run on Unraid

Use [unraid-template.xml](unraid-template.xml) with the separate preview image
`ghcr.io/arnas1111/unraid-control-center:preview`. The default host port is
**3334**. Its appdata directory is independent of Homelab. No Docker socket,
host boot mount, shell access, or elevated container privileges are required.

1. Open the preview and create its local administrator password.
2. In Settings, save the Unraid URL and an API key. Blank keys preserve the
   saved key; **Clear saved API key** removes it. Credentials never return in
   the settings API. Configuration persists under `/data/control.sqlite`.
3. Test & reconnect. The preview uses GraphQL introspection to detect fields
   and operations in the installed API. Introspection must be available to the
   key. If blocked, review Unraid API developer/sandbox settings.
4. Enable server controls only when ready to use them. Each command requires
   a one-use, expiring confirmation and a typed operation name. API permissions
   remain authoritative; detecting a schema field does not grant permission.
5. Configure the optional Homelab URL for shortcut suggestions. Homelab's
   MQTT/automation engine remains in that separate app during migration.

The API address must be reachable from the container. TLS verification remains
enabled; use a trusted certificate when connecting over HTTPS. Authentication
can be disabled in Settings for the user's local deployment. The administrator
identity remains saved so login can be re-enabled. Sessions expire after 12 h
and are invalidated on restart or login-setting changes.

Stopping the array also stops dependent Docker/VM workloads and can stop this
control center itself. Array start/stop requires testing from an environment
that remains available through the operation. Encrypted-array unlock is not
implemented. A timeout can mean the command was accepted but its response was
lost; commands are never automatically retried. Inspect server state first.

## Implemented

- Original responsive interface, bookmarked routes, back/forward navigation,
  command navigation, focused pages and independent section errors.
- API schema capability detection; optional fields are omitted for older APIs.
- Array, parity/cache/boot devices, temperatures, errors and capacity. Sizes
  reported as KB are converted to bytes; missing readings remain unknown.
- Confirmed array start/stop, non-correcting parity verification, pause/resume/
  cancel, Docker lifecycle, VM lifecycle, and notification archive operations.
- Share inventory/placement, network interfaces, unread notifications, and
  API-plugin inventory (explicitly **not** all installed `.plg` plugins).
- CPU/memory readings and a short browser-session CPU chart. It is not durable
  metrics history. API polling is bounded, cached 10 s and per-section single
  flight; raw disk-layout queries that can wake sleeping disks are not polled.
- Custom service tiles with original vector icons, suggestions, groups,
  enable/hide, editing and deletion. Docker Web UI links come from the API.
- Persistent connection/access preferences and a bounded command activity log.
- No arbitrary GraphQL proxy, no arbitrary host commands, no raw upstream
  errors or credentials in responses, no credential-bearing HTTP redirects.

## Remaining scope

See [FEATURE_PARITY.md](FEATURE_PARITY.md). Native share editing, users, disk
assignment/formatting, detailed pool/ZFS operations, SMART tests, Docker
templates/install/update, VM hardware editing/consoles, full plugin management,
OS upgrades, terminal, file manager, and the Homelab feature migration are
**not implemented**. Native WebUI links are labeled as such. Unsupported
controls do not pretend to work.

Live queries and mutations are covered by mocked-schema/transport tests;
**no operations have been executed against the user's server**. Validate the
installed schema, key permissions, and real state transitions on Unraid 7.2.3
before calling this production-ready or claiming performance gains.

## Local development

Python 3.12, dependencies from requirements.txt. Set `CONTROL_DATA` to an
independent writable directory, then run:

```sh
uvicorn control.main:app --host 127.0.0.1 --port 8080
python -m unittest discover -s tests
node --check static/control.js
```

Browser checks additionally need Playwright/Chromium; `CONTROL_BROWSER_EXECUTABLE`
can select a system browser. Do not use Homelab's existing `/data` directory as
this preview's data directory.

## Research

- [Official WebGUI tour](https://docs.unraid.net/unraid-os/getting-started/explore-the-user-interface/tour-the-web-gui/)
- [Official API guide](https://docs.unraid.net/API/how-to-use-the-api/)
- [Official public API schema](https://github.com/unraid/api/blob/main/api/generated-schema.graphql)
- [Official share/storage behavior](https://docs.unraid.net/unraid-os/using-unraid-to/manage-storage/shares/)

The public `main` schema evolves independently of OS 7.2.3. Runtime schema
detection is mandatory; the referenced schema is not assumed to match the host.
