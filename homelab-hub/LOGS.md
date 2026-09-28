# Central container logs

Open **Logs** in the sidebar to investigate recent messages across Docker containers. The default filter includes critical, error and warning lines. Filter by container, time, severity or message text. **Service context** selects that container, clears the text search and shows all severities in the current time window. Auto refresh can be paused for investigation.

## Collection and coverage

The Hub reads Docker stdout/stderr through the existing socket. No extra deployment or API key is needed. Requests return a shared background snapshot; logging does not run on Home or delay overview discovery. Collection refreshes at most once every 15 seconds while requested. A pass already in progress finishes even if you leave Logs.

Each pass reads at most 500 recent lines and 256 KiB per container from the last 24 hours, for up to 200 containers in name order. The response displays up to 500 matching lines, newest first. Narrow the filters when the result limit is reached. A byte-limited source may omit newer as well as older messages; incomplete final lines at that limit are discarded. Very long individual displayed messages are clipped to 16,000 characters. The coverage panel identifies capped and unreadable containers.

Counts describe the captured lines after service, time and text filtering, before severity filtering. They are not lifetime totals or unique incidents. Identical errors can appear multiple times. Lines without a valid timestamp remain visible and cannot be time-filtered.

Only logs readable through Docker are included. Files written inside containers, Unraid host syslog, remote services and bookmarks are not collected. Some logging drivers cannot serve logs through Docker; these appear as unavailable sources. Rotated logs, removed containers, and events older than the capture window cannot be recovered. Snapshots are in memory and disappear when the Hub restarts. This feature does not write logs to the PostgreSQL metrics database.

## Error detection

The detector prefers recognized textual JSON fields (`level`, `severity`, `log_level`, `loglevel`), then explicit text levels such as `level=error` or `[ERROR]`. These take precedence over words in the message: an INFO entry about an error handler remains INFO.

Without an explicit level, words such as exception, failed, panic, warning, deprecated or timeout provide a best-effort classification. Common summaries such as `0 errors` are excluded. Traceback continuation lines inherit the preceding severity. Unknown messages remain available through **All levels** or **Unknown**. The UI labels the detection method; keyword matches can be false positives and do not prove that the service is down. HTTP status codes without an explicit level are not automatically classified.

The page requires the Hub administrator session and escapes message content before rendering. Common password, token, API-key and authorization fields are masked before entering the cache. This is best-effort masking, not a guarantee for arbitrary application output; avoid logging secrets at the source.

## Relationship to Grafana

The usual Grafana logging stack separates responsibilities: Alloy collects logs, Loki retains and queries them, and Grafana Explore/Logs Drilldown provides investigation. See the [official Loki tutorial](https://grafana.com/docs/loki/latest/get-started/quick-start/tutorial/) and [log visualization documentation](https://grafana.com/docs/loki/latest/visualize/grafana/).

This built-in view provides immediate, bounded investigation with the existing socket. Continuous historical collection, retention beyond Docker rotation, log-based alerting and multi-host searches would require a persistent backend. A future Loki connector should expose those capabilities explicitly rather than silently treating recent snapshots as complete history.

## Validation

Tests cover severity precedence, keyword false positives, traceback context, common-secret masking, timestamps and filtering, byte limits, partial-source failures, authentication, background loading responses, safe HTML rendering, service context, failed-refresh retention and mobile layout. Real application formats and logging drivers should still be checked on the deployed host.
