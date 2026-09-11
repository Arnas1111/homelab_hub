# Performance pages and PostgreSQL 18 history

Open **Performance history** in the sidebar, or select the CPU, memory or storage heading in the overview. Each statistic has its own URL: `/#metrics/cpu`, `/#metrics/memory`, `/#metrics/storage`, `/#metrics/network`, and `/#metrics/containers`.

Pages offer 1-hour, 6-hour, 24-hour, 7-day and 30-day ranges, average/peak curves, exact sampled values in a table, and the latest stored readings. The Containers page can filter by container ID, including containers removed since collection. A recreated container has a new ID and a separate history. Empty intervals and failed measurements are not drawn as zero utilization. Charts aggregate into at most about 360 time buckets; averages are weighted by actual valid samples, and peaks retain the maximum sample in each bucket.

## Connect your database

1. Update the Hub container after the image build completes.
2. Open **History storage** in the sidebar.
3. Enter your PostgreSQL hostname/IP, port (normally 5432), database, username and password. The address must be reachable **from the Hub container**. `localhost` means the Hub container itself, not Unraid or another container.
4. Select TLS mode, sample interval, retention and whether to include Docker containers. Defaults are 30 seconds, 30 days, and container sampling enabled.
5. Use **Test connection**. This checks connectivity/authentication and reports the server version and schema-creation permission; it neither saves changes nor creates tables.
6. Enable collection and **Save history settings**. Check the collection status for a successful stored sample. The first CPU/network reading needs a second sample to calculate a rate.

The database must already exist. A role that owns a dedicated database is simplest. For example, an administrator can create a role and database in `psql`:

```sql
CREATE ROLE homelab LOGIN;
\password homelab
CREATE DATABASE homelab OWNER homelab;
```

Use the interactive password prompt rather than committing a password in a script. An existing database also works if the role can create the `homelab_hub` schema and owns or has the needed access to its tables. The Hub does not create users, databases, PostgreSQL containers, or alter unrelated tables.

On Unraid's `docker-internal` network, attach PostgreSQL to a reachable network or use a reachable host address and published PostgreSQL port. The Hub's Docker template and `/data` mapping do not need to change. Changing an XML template in the repository does not update an already-installed container's settings.

TLS `prefer` permits fallback to an unencrypted connection. `require` enforces encryption without hostname verification. For certificate/hostname verification, choose `verify-full` and configure libpq's trust file, for example by mounting a CA certificate and setting `PGSSLROOTCERT` in the container.

## Storage and operation

- Configuration and the password remain in SQLite under `/data/hub.db`. Passwords are never returned by the settings API; leave the password blank to retain it, or select **Clear saved password**. Treat appdata backups as sensitive.
- PostgreSQL stores samples in `homelab_hub.samples`, keyed by a stable Hub source UUID and UTC timestamp. `homelab_hub.schema_version` tracks the schema. Each snapshot contains typed numeric measurements in JSONB plus per-core and optional per-container detail.
- Collection runs in one background thread per Hub process, independent of browser requests. Run the supplied single-worker Uvicorn command; multiple worker processes would collect duplicates. CPU/network counters are independent of live overview polling.
- Collection starts disabled. Saving settings enables collection only when selected. Schema setup runs on first write. Database errors are shown as contained status messages, retried after 30 seconds, and do not block the live overview. There is no local outage spool: downtime remains a visible gap.
- A 30-second interval produces approximately 2,880 snapshots/day; snapshot size depends on core/container counts. Sampling duration is added to the interval, so slow Docker responses can reduce the actual rate. Choose a longer interval or disable container sampling on larger hosts.
- Retention removes only this Hub's expired samples, in batches of up to 10,000 each hour while collection is enabled. Large retention reductions may take several passes. Disabling collection preserves existing data and pauses retention. Changing databases leaves the old database untouched.
- Separate installations get separate source UUIDs. Copying the same appdata directory also copies that identity; don't run two copies against the same history store simultaneously.
- History queries have a maximum 30-day range and return bounded aggregated charts. PostgreSQL connection, statement and lock timeouts keep failures bounded. Large container-history queries may require a shorter selected range.

## What the readings mean

- **CPU:** host utilization, 100% across all cores; per-core detail is the latest stored sample.
- **Memory:** host total minus available memory, plus used/available bytes.
- **Storage:** filesystem backing `/data`; this is not Unraid array health, disk SMART data or directory size.
- **Network:** the Hub's network namespace; bridge mode excludes other host traffic.
- **Containers:** Docker CPU uses 100% per logical core, and can exceed 100%. Memory uses Docker working-set usage. Combined totals are missing when a container read fails, rather than silently undercounting it.

## Validation

CI starts a disposable PostgreSQL 18 service and tests schema initialization, writes, history queries, null samples, aggregation, source isolation, retention and reading history after collection is disabled. Unit tests cover secret preservation/redaction, API authentication/validation, disabled collection and background recovery. Image publishing waits for these checks.

Implementation references: [Psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html), [PostgreSQL 18 time bucketing](https://www.postgresql.org/docs/18/functions-datetime.html).
