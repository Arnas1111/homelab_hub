# Homelab Hub: a home for services and operations

Research and implementation: 18 September 2026.

The product should answer three questions quickly: **What can I open? What needs attention? What is using capacity?** Home answers these at a glance. Services is the complete directory; Containers is the administration workspace; Metrics and History explain resource usage; Integrations contains connected application data and controls.

## Research and design decisions

These are original implementation choices informed by the projects below, not copied components or a claim of feature parity.

| Project / primary source | Useful idea | Decision for this Hub |
| --- | --- | --- |
| [Homepage: Docker discovery](https://gethomepage.dev/configs/docker/) | Container labels describe applications and groups | Accept `homepage.*` display metadata alongside Hub labels and Unraid WebUI templates. Credentials remain separate. |
| [Homarr: Docker integration](https://homarr.dev/docs/integrations/docker/) | A dashboard can combine applications with Docker operations | Keep container actions and logs, accessible from service Details, with their own administration page. |
| [Grafana: dashboard best practices](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/) | Organize information around questions and drill down from summaries | Four capacity summaries lead into existing historical charts; units, missing data and collection timestamps remain visible. |
| [Glance](https://github.com/glanceapp/glance) | Restrained columns, focused widgets, caching, lightweight frontend | Use one service column and one attention/connections column; background snapshots remove collectors from the request path. |
| [Dashy documentation](https://dashy.to/docs/) | Configurable personal dashboard and navigation | Persist favorites, support groups and manual links, and provide keyboard search. A free-form layout editor is future work. |
| [Heimdall](https://github.com/linuxserver/Heimdall) | Application launching is a valuable core workflow | Make the application name and icon the launch target; show operational details separately. |
| [Organizr](https://organizr.org/) | One entry point for multiple services | Use clear page navigation. Embedded applications and SSO require their own authentication design and are not implemented here. |
| [Unraid API](https://docs.unraid.net/API/how-to-use-the-api/) | Read hardware, array and disk information through GraphQL | Add a read-only adapter for real array state and disk temperature. Docker metadata cannot substitute for this source. |

## Implemented workspace

- **Home:** server identity, running-container count, CPU, memory and storage summaries, eight quick-access services or saved favorites, reported container problems, and connection setup hints.
- **Services:** automatic grouping and recognition, label-derived names/icons/links, manual external links, search, favorites and attention/running filters. Ctrl/Cmd+K opens search. External bookmarks explicitly have no availability monitoring.
- **Containers:** existing state controls, logs, grouping, resource usage and published-port inventory. Resource sampling happens in the background. Missing readings are not zero usage.
- **Metrics / History:** existing utilization charts, capacity gauges, detailed statistic pages and optional PostgreSQL 18 history. History collection remains independent of browser visits.
- **Integrations:** existing Jellyfin activity and Home Assistant controls, plus Unraid hardware, array state and disk temperatures. Connection setup is separate from everyday viewing.

Visual rules: neutral surfaces, one blue interaction accent, green for running state, amber for attention or elevated utilization, red for critical utilization. Text accompanies color. Application logos may retain their identity colors. A stopped container is not automatically an incident, and a running container is not proof that its web application is reachable.

## Why opening was slow, and what changed

The previous startup awaited the full icon catalog, then the overview request could wait for resource samples across every container. It also rendered and refreshed panels unrelated to the visible page.

Home now requests Docker list metadata and host readings through independent, single-flight caches. Docker inventory uses a list call and an info call, without per-container inspect or stats calls. Cold requests return immediately with a discovery state; subsequent polls fill the page. Last successful snapshots survive upstream failures with a status message. Concurrent viewers share collection work within one application process. Icons are local assets; the icon picker catalog loads only when opening container details.

Container statistics run when the Containers or Metrics view requests them. Application integrations load on their own page. Hidden browser tabs and settings/history views do not keep polling the overview. PostgreSQL collection retains its separate configured sampling schedule.

Cache defaults: Docker inventory 10 seconds, container resources 10 seconds, host readings 5 seconds, Unraid 30 seconds. These are maximum refresh frequencies, not guaranteed measurement intervals. Caches are process-local and refresh on demand, with inventory and host collection warmed at startup. Docker actions invalidate inventory/resources. Connection changes invalidate the Unraid snapshot, including an in-flight result from the old configuration.

## Automatic discovery and Unraid setup

The existing socket mount and `/data` persistence contract are unchanged. The directory recognizes common media, automation, storage and infrastructure images. Recognition provides presentation defaults, not an authenticated integration.

Supported label precedence:

1. Existing saved Hub icon/group and WebUI preferences.
2. `homelab.name`, `homelab.group`, `homelab.icon`, `homelab.href`, `homelab.description`.
3. Matching `homepage.*` display labels.
4. Unraid `net.unraid.docker.webui` and `net.unraid.docker.icon`, then recognized image/name defaults and existing known-port links.

Example labels: `homepage.name=Jellyfin`, `homepage.group=Media`, `homepage.href=https://media.example.com`. Only display metadata is extracted; arbitrary Docker labels and widget credentials are not sent to the browser. This is display-label compatibility, not support for Homepage widget configuration.

Unraid templates such as `http://[IP]:[PORT:8096]/` use the hostname through which the Hub is accessed and the container's published TCP port. Host-network, dedicated-IP, reverse-proxy and VPN routes may need an explicit URL override in Services. Unresolved templates are not emitted as working links.

For real Unraid telemetry, open **Connections**, set the server URL and API key, and save. Create a key with Info and Array read access in Unraid's API settings. The connector uses `/graphql` and `x-api-key`; it validates TLS normally and refuses redirects to avoid forwarding credentials to another destination. The key is retained server-side and never returned by normal settings responses. Environment defaults: `HUB_UNRAID_URL`, `HUB_UNRAID_API_KEY`.

Array space comes from `capacity.kilobytes`, normalized to bytes. The similarly named `capacity.disks` counts disk slots, not storage space; this distinction was verified against the [Unraid array schema](https://github.com/unraid/api/blob/main/api/src/unraid-api/graph/resolvers/array/array.model.ts).

## Scope and next priorities

This release establishes the shared workspace and discovery foundation. It does not implement every integration advertised by the researched projects.

1. Service-level availability and incident history, with opt-in endpoints, timeouts and explicit expected uptime. Docker running/health state is only one signal.
2. Isolate the remaining Jellyfin/Home Assistant collectors into modules and separate cached endpoints, following the Unraid adapter. Their existing aggregate endpoint can still wait for a slow integration on the Integrations page.
3. Add tested adapters for download queues, media-library activity, uptime monitors and virtualization hosts. Each adapter needs its own credential setup, clear data scope and failure state.
4. Persist Unraid-specific disk temperatures/array events in history with a versioned schema. Current PostgreSQL history stores the existing host/container metrics; Unraid API readings are live snapshots only.
5. Multiple hosts, per-user layouts, RBAC and external identity require deliberate data-model/authentication work. This release remains one Hub, one Docker endpoint, shared favorites.

Validation includes cache concurrency/invalidation, metadata and link handling, credential redaction, authenticated API routes, frontend regressions, and desktop/mobile browser workflows. The CI suite also exercises PostgreSQL 18 before image publication. Browser data and Unraid responses are fixtures; live Unraid/API credentials and real-host opening times have not been tested here.
