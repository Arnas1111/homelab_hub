# Review of the Copilot handoff

**Update:** Dedicated statistic pages and PostgreSQL background history have now been implemented. See [HISTORY.md](HISTORY.md) for configuration, data scope, retention and validation. The original findings and remaining-work list below describe the earlier review baseline; PostgreSQL is no longer unimplemented.

Reviewed baseline: `9a71b2a` (11 September 2026). The checkout was clean.

## Findings and changes

- **Broken container interactions:** the render cache ignored folded groups, search mode, group order, icons and WebUI links. Those inputs now invalidate the cache; polling updates status and resource cells in place. Search also reapplies section visibility on the cached path.
- **Incomplete flicker fix:** metrics and integration panels were still replaced every poll. These now reconcile existing DOM nodes and attributes. Focused controls are preserved, including when an integration request finishes after interaction starts. Structural container changes still rebuild the table; this is not a full keyed frontend rewrite.
- **Refresh failure recovery:** a failed overview request replaced the table and stopped scheduled polling. Last received data now stays visible with a failure label, and polling retries.
- **Hidden search target:** Ctrl/Cmd+F now finds a visible search input or opens Containers and unfolds its search section.
- **Settings edits:** polling no longer overwrites unsaved fields while Settings is open.
- **CPU sampling:** the formula already used Docker CPU units (100% per logical core). Copilot's host-normalized label was incorrect. More significantly, `one_shot=True` skips the two-cycle sample used for interval utilization. Collection now requests two cycles. This adds sampling latency; the existing pool runs up to 16 container requests concurrently.
- **Metric scope:** the network card now identifies its container network namespace limitation. Bridge-mode `/proc/net/dev` does not represent all Unraid traffic. Data mount capacity is not individual disk health or appdata folder size.
- **Integration isolation:** Docker discovery failures no longer block Home Assistant. An explicit Jellyfin URL avoids creating a Docker client. Connector exceptions remain contained to their own card.
- **Version:** published images now receive the source commit as `HUB_VERSION`; local Docker builds default to `dev`. The existing environment override still works.
- **Validation:** added Node regression tests for caching, folding, search, preference updates and refresh recovery; Python tests for CPU sampling and integration isolation; a CI checks workflow.

## Validation limits

Five JavaScript regression tests and JavaScript syntax checking passed locally using VS Code's bundled Node runtime. `git diff --check` passed. No usable standalone Python or Docker runtime was available in this session, so Python tests and compilation are configured in CI but have not run locally. Tests use isolated functions and mocks; they do not replace browser or Unraid integration testing. The new CI workflow runs separately from image publication.

No live Jellyfin or Home Assistant credentials/endpoints were used. The earlier claim that HTTP 401 errors were fixed is unverified: additional headers and better messages cannot establish that authentication succeeds. Verify both connectors against the running services after deployment.

## Remaining feature work

1. PostgreSQL 18 metrics history: separate module, secret-safe configuration and connection testing, migrations, background sampling independent of open browsers, retention, time-range charts, and outage handling.
2. FileBrowser Quantum: verify the deployed version's API/authentication, then build a Files page with permission-aware navigation, streaming downloads/uploads and file operations.
3. Hosted WebCal: define calendar storage and authenticated export/subscription behavior. Removing Agenda did not implement a calendar service; legacy Nextcloud settings/code still remain.
4. Host telemetry: collect actual Unraid network/disk metrics through a deliberate host integration; current container-visible metrics cannot provide the full picture.
5. Continue module extraction as features are built. Avoid a broad refactor before integration behavior has coverage.

## Useful deployment checks

- Fold/unfold a group, search for all of its containers, clear search, change an icon/link and reorder groups.
- Watch metrics and Home Assistant controls across several polls; use a slider while an update is in flight.
- Interrupt connectivity and restore it: existing data should remain and refresh should recover automatically.
- Compare container CPU with `docker stats` under sustained load, allowing for different sampling times.
- Use Ctrl+F from Metrics, Settings and a folded Containers section.
- Check Settings shows the source commit after the next published build.

References: [Docker stats formulas](https://docs.docker.com/reference/api/engine/version/v1.45/), [Docker SDK sampling options](https://docker-py.readthedocs.io/en/stable/api.html).
