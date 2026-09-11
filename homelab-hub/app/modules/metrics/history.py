"""Optional PostgreSQL history. SQLite owns configuration, PostgreSQL owns samples."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import math
import threading
import time
import uuid
from typing import Literal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator


class HistorySettings(BaseModel):
    enabled: bool = False
    host: str = Field(default="", max_length=253, pattern=r"^[a-zA-Z0-9_.:-]*$")
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(default="homelab", min_length=1, max_length=63)
    username: str = Field(default="homelab", min_length=1, max_length=63)
    password: str = Field(default="", max_length=2000, repr=False)
    clear_password: bool = False
    sslmode: Literal["disable", "prefer", "require", "verify-full"] = "prefer"
    sample_seconds: int = Field(default=30, ge=10, le=3600)
    retention_days: int = Field(default=30, ge=1, le=365)
    include_containers: bool = True

    @model_validator(mode="after")
    def configured_when_enabled(self):
        if self.enabled and not self.host:
            raise ValueError("A database hostname is required to enable history")
        return self


RANGES = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000}
SERIES = {
    "cpu": [("cpu_percent", "Host CPU", "%")],
    "memory": [("memory_percent", "Memory utilization", "%"), ("memory_used", "Used memory", "B"), ("memory_available", "Available memory", "B")],
    "storage": [("storage_percent", "Storage utilization", "%"), ("storage_free", "Free space", "B")],
    "network": [("rx_rate", "Receive", "B/s"), ("tx_rate", "Transmit", "B/s")],
    "containers": [("container_cpu", "Combined container CPU", "% cores"), ("container_memory", "Combined container memory", "B")],
}


def safe_error(exc):
    # Database diagnostics may contain credentials/connection strings. Never return str(exc).
    if isinstance(exc, psycopg.errors.InsufficientPrivilege):
        return "Database permissions denied. The Hub role needs schema creation and read/write access to its tables."
    if isinstance(exc, psycopg.errors.UndefinedTable):
        return "History tables are not initialized. Save and enable collection to initialize them."
    if isinstance(exc, psycopg.OperationalError):
        return "Cannot connect to PostgreSQL. Check hostname, port, database, credentials, TLS and network access."
    return "History operation failed. Check database availability, permissions and server compatibility."


class HistoryStore:
    def __init__(self, sqlite_factory, collector):
        self.sqlite_factory = sqlite_factory
        self.collector = collector
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.thread = None
        self.last_saved = None
        self.last_error = None
        self.schema_target = None
        self.last_prune = 0

    def initialize(self):
        with closing(self.sqlite_factory()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS metrics_config (id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL, source_id TEXT NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO metrics_config VALUES (1, ?, ?)", (HistorySettings().model_dump_json(), str(uuid.uuid4())))

    def config(self):
        with closing(self.sqlite_factory()) as conn:
            row = conn.execute("SELECT config, source_id FROM metrics_config WHERE id=1").fetchone()
        return HistorySettings.model_validate_json(row[0]), row[1]

    def public(self):
        cfg, _ = self.config()
        values = cfg.model_dump(exclude={"password", "clear_password"})
        values["password_set"] = bool(cfg.password)
        with self.lock:
            values["status"] = {"last_saved": self.last_saved, "error": self.last_error, "running": bool(self.thread and self.thread.is_alive())}
        return values

    def merged(self, payload):
        saved, _ = self.config()
        values = payload.model_dump()
        values["password"] = "" if payload.clear_password else (payload.password or saved.password)
        values["clear_password"] = False
        return HistorySettings(**values)

    def save(self, payload):
        with self.lock:
            cfg = self.merged(payload)
            with closing(self.sqlite_factory()) as conn, conn:
                conn.execute("UPDATE metrics_config SET config=? WHERE id=1", (cfg.model_dump_json(),))
            self.last_error = None
            self.last_saved = None
            self.schema_target = None
            self.last_prune = 0
        self.wake.set()
        return self.public()

    def connect(self, cfg):
        if not cfg.host:
            raise psycopg.OperationalError("Missing host")
        return psycopg.connect(host=cfg.host, port=cfg.port, dbname=cfg.database,
                               user=cfg.username, password=cfg.password, sslmode=cfg.sslmode,
                               connect_timeout=5, application_name="homelab-hub",
                               options="-c statement_timeout=8000 -c lock_timeout=3000",
                               row_factory=dict_row)

    def test(self, payload):
        with self.connect(self.merged(payload)) as conn:
            version = conn.info.server_version
            can_create = conn.execute("SELECT has_database_privilege(current_database(), 'CREATE') AS allowed").fetchone()["allowed"]
            schema = conn.execute("SELECT oid FROM pg_namespace WHERE nspname='homelab_hub'").fetchone()
            return {"ok": True, "server_version": version, "can_create_schema": can_create,
                    "schema_exists": bool(schema), "message": "Connection successful. Saving with collection enabled initializes the history tables; write permissions are checked then."}

    def ensure_schema(self, conn):
        conn.execute("CREATE SCHEMA IF NOT EXISTS homelab_hub")
        conn.execute("CREATE TABLE IF NOT EXISTS homelab_hub.schema_version (version INTEGER PRIMARY KEY)")
        versions = conn.execute("SELECT version FROM homelab_hub.schema_version").fetchall()
        if any(row["version"] > 1 for row in versions):
            raise RuntimeError("Unsupported schema")
        conn.execute("CREATE TABLE IF NOT EXISTS homelab_hub.samples (source_id UUID NOT NULL, sampled_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL, PRIMARY KEY(source_id, sampled_at))")
        conn.execute("INSERT INTO homelab_hub.schema_version VALUES (1) ON CONFLICT DO NOTHING")

    def write(self, cfg, source_id, sample, sampled_at):
        # Each operation has its own connection/transaction; no connections cross threads.
        target = (cfg.host, cfg.port, cfg.database, cfg.username, cfg.sslmode)
        with self.connect(cfg) as conn:
            if self.schema_target != target:
                self.ensure_schema(conn)
            conn.execute("INSERT INTO homelab_hub.samples VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (source_id, sampled_at, Jsonb(sample)))
            prune = time.monotonic() - self.last_prune >= 3600
            if prune:
                # Bounded batches keep large retention changes from locking a collection cycle.
                conn.execute("DELETE FROM homelab_hub.samples WHERE source_id=%s AND sampled_at IN (SELECT sampled_at FROM homelab_hub.samples WHERE source_id=%s AND sampled_at < %s ORDER BY sampled_at LIMIT 10000)", (source_id, source_id, sampled_at - timedelta(days=cfg.retention_days)))
        self.schema_target = target
        if prune:
            self.last_prune = time.monotonic()

    def collect_once(self):
        cfg, source = self.config()
        if not cfg.enabled:
            return cfg.sample_seconds
        sample = self.collector(cfg.include_containers)
        sampled_at = datetime.now(timezone.utc)
        # Recheck configuration after the potentially slow Docker sampling call.
        with self.lock:
            current, _ = self.config()
            if current != cfg or self.stop_event.is_set():
                return 1
            self.write(cfg, source, sample, sampled_at)
            self.last_saved = sampled_at.isoformat()
            self.last_error = None
        return cfg.sample_seconds

    def run(self):
        while not self.stop_event.is_set():
            self.wake.clear()
            try:
                delay = self.collect_once()
            except Exception as exc:
                with self.lock:
                    self.last_error = safe_error(exc)
                delay = 30
            self.wake.wait(delay)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, name="metrics-history", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=15)

    def history(self, metric, range_name, container_id=None):
        cfg, source = self.config()
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=RANGES[range_name])
        bucket = max(cfg.sample_seconds, math.ceil(RANGES[range_name] / 360))
        definitions = SERIES[metric]
        expressions = []
        for key, _, _ in definitions:
            expression = sql.SQL("(payload ->> {})::double precision").format(sql.Literal(key))
            if metric == "containers" and container_id:
                field = "cpu_percent" if key == "container_cpu" else "memory_used"
                expression = sql.SQL("(SELECT (c ->> {})::double precision FROM jsonb_array_elements(payload->'containers') c WHERE c->>'id'={} LIMIT 1)").format(sql.Literal(field), sql.Literal(container_id))
            expressions.extend([sql.SQL("AVG({}) AS {}").format(expression, sql.Identifier(key)),
                                sql.SQL("MAX({}) AS {}").format(expression, sql.Identifier(key + "_max")),
                                sql.SQL("COUNT({}) AS {}").format(expression, sql.Identifier(key + "_count"))])
        query = sql.SQL("SELECT date_bin(%s::interval, sampled_at, '2000-01-01'::timestamptz) AS time, count(*) AS samples, {} FROM homelab_hub.samples WHERE source_id=%s AND sampled_at >= %s AND sampled_at <= %s GROUP BY 1 ORDER BY 1").format(sql.SQL(", ").join(expressions))
        with self.connect(cfg) as conn:
            rows = conn.execute(query, (timedelta(seconds=bucket), source, start, end)).fetchall()
            latest = conn.execute("SELECT sampled_at, payload FROM homelab_hub.samples WHERE source_id=%s ORDER BY sampled_at DESC LIMIT 1", (source,)).fetchone()
            choices = []
            if metric == "containers":
                choices = conn.execute("SELECT DISTINCT c->>'id' AS id, c->>'name' AS name FROM homelab_hub.samples CROSS JOIN LATERAL jsonb_array_elements(payload->'containers') c WHERE source_id=%s AND sampled_at >= %s ORDER BY name LIMIT 200", (source, start)).fetchall()
        return {"metric": metric, "range": range_name, "start": start, "end": end, "bucket_seconds": bucket,
                "series": [{"key": key, "label": label, "unit": unit} for key, label, unit in definitions],
                "points": rows, "latest": latest, "containers": choices, "enabled": cfg.enabled,
                "sample_seconds": cfg.sample_seconds, "retention_days": cfg.retention_days}
