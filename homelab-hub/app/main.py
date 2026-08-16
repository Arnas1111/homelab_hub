import json
import os
import pwd
import random
import re
import secrets
import shutil
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urljoin, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

import docker
from docker.errors import APIError, DockerException, NotFound
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeSerializer
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("HUB_DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "hub.db"
BUNDLED_ICON_DIR = APP_DIR / "static" / "icons" / "dashboard"
USER_ICON_DIR = DATA_DIR / "icons" / "dashboard"
DASHBOARD_ICON_CDN = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg"
ICON_RE = re.compile(r"^[a-z0-9-]{1,90}$")
CPU_SAMPLE_LOCK = threading.Lock()
LAST_CPU_SAMPLE: dict[str, tuple[int, int]] | None = None
NETWORK_SAMPLE_LOCK = threading.Lock()
LAST_NETWORK_SAMPLE: tuple[float, int, int] | None = None
PROC_SAMPLE_LOCK = threading.Lock()
LAST_PROC_SAMPLE: dict[str, tuple[int, int]] | None = None
LAST_PROC_TOTAL: int | None = None
PARTY_MODE_STOP = threading.Event()
PARTY_MODE_THREAD: threading.Thread | None = None
PARTY_MODE_DELAY = 1.75
WHITE_MODE_KELVIN = {
    "auto": 4000,
    "warm": 2700,
    "neutral": 4000,
    "cold": 6500,
    "cold_warm": 4000,
}

ADMIN_PASSWORD = os.getenv("HUB_ADMIN_PASSWORD", "")
SESSION_SECRET = os.getenv("HUB_SESSION_SECRET", "") or secrets.token_urlsafe(48)
SERVER_NAME = os.getenv("HUB_SERVER_NAME", "Unraid")

app = FastAPI(title="Homelab Hub", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

templates = Environment(
    loader=FileSystemLoader(APP_DIR / "static"),
    autoescape=select_autoescape(["html", "xml"]),
)
signer = URLSafeSerializer(SESSION_SECRET, salt="homelab-hub-session")


class SettingsPayload(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    refresh_seconds: int = Field(ge=1, le=60)
    confirm_actions: bool


class ContainerPrefsPayload(BaseModel):
    icon: str = Field(default="", max_length=90, pattern=r"^[a-z0-9-]*$")
    group_name: str = Field(default="", max_length=80)


class IconDownloadPayload(BaseModel):
    icon: str = Field(max_length=90, pattern=r"^[a-z0-9-]+$")


class OrderPayload(BaseModel):
    groups: list[str] = Field(default_factory=list)
    containers: dict[str, list[str]] = Field(default_factory=dict)


class WebuiLinkPayload(BaseModel):
    link_key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=500)
    icon: str = Field(default="", max_length=90, pattern=r"^[a-z0-9-]*$")
    container_name: str = Field(default="", max_length=120)
    enabled: bool = True
    sort_order: int = 0
    source: Literal["auto", "manual"] = "manual"


class WebuiLinksPayload(BaseModel):
    links: list[WebuiLinkPayload] = Field(default_factory=list)


class IntegrationSettingsPayload(BaseModel):
    jellyfin_url: str = Field(default="", max_length=500)
    jellyfin_public_url: str = Field(default="", max_length=500)
    jellyfin_api_key: str = Field(default="", max_length=5000)
    jellyfin_api_key_clear: bool = False
    nextcloud_calendar_url: str = Field(default="", max_length=1000)
    nextcloud_url: str = Field(default="", max_length=500)
    nextcloud_username: str = Field(default="", max_length=200)
    nextcloud_app_password: str = Field(default="", max_length=5000)
    nextcloud_app_password_clear: bool = False
    nextcloud_calendar_name: str = Field(default="", max_length=200)
    home_assistant_url: str = Field(default="", max_length=500)
    home_assistant_token: str = Field(default="", max_length=5000)
    home_assistant_token_clear: bool = False
    home_assistant_entities: str = Field(default="", max_length=2000)


class HomeAssistantTogglePayload(BaseModel):
    entity_id: str = Field(min_length=1, max_length=160)


class HomeAssistantColorPayload(BaseModel):
    entity_id: str = Field(min_length=1, max_length=160)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class HomeAssistantWhitePayload(BaseModel):
    entity_id: str = Field(min_length=1, max_length=160)
    mode: Literal["warm", "cold", "cold_warm"]


class HomeAssistantPartyPayload(BaseModel):
    enabled: bool
    craziness: int = Field(default=5, ge=1, le=10)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS container_prefs (
                container_name TEXT PRIMARY KEY,
                icon TEXT NOT NULL DEFAULT '',
                group_name TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(container_prefs)").fetchall()}
        if "sort_order" not in existing_columns:
            conn.execute("ALTER TABLE container_prefs ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS group_prefs (
                group_name TEXT PRIMARY KEY,
                sort_order INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webui_links (
                link_key TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                url TEXT NOT NULL,
                icon TEXT NOT NULL DEFAULT '',
                container_name TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'manual'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS integration_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
            """
        )
        defaults = {
            "title": "Homelab Hub",
            "refresh_seconds": "5",
            "confirm_actions": "true",
        }
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )


@app.on_event("startup")
def startup() -> None:
    USER_ICON_DIR.mkdir(parents=True, exist_ok=True)
    init_db()


def get_settings() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    values = {r["key"]: r["value"] for r in rows}
    return {
        "title": values.get("title", "Homelab Hub"),
        "refresh_seconds": int(values.get("refresh_seconds", "5")),
        "confirm_actions": values.get("confirm_actions", "true").lower() == "true",
    }


def get_container_prefs() -> dict[str, dict]:
    with db() as conn:
        rows = conn.execute("SELECT container_name, icon, group_name, sort_order FROM container_prefs").fetchall()
    return {
        r["container_name"]: {
            "icon": r["icon"],
            "group_name": r["group_name"],
            "sort_order": r["sort_order"],
        }
        for r in rows
    }


def get_group_order() -> dict[str, int]:
    with db() as conn:
        rows = conn.execute("SELECT group_name, sort_order FROM group_prefs").fetchall()
    return {r["group_name"]: r["sort_order"] for r in rows}


def save_container_prefs(container_name: str, payload: ContainerPrefsPayload) -> dict:
    icon = payload.icon.strip().lower()
    group_name = " ".join(payload.group_name.strip().split())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO container_prefs(container_name, icon, group_name)
            VALUES (?, ?, ?)
            ON CONFLICT(container_name) DO UPDATE SET
                icon=excluded.icon,
                group_name=excluded.group_name
            """,
            (container_name, icon, group_name),
        )
    return {"container_name": container_name, "icon": icon, "group_name": group_name}


def save_order(payload: OrderPayload) -> dict:
    with db() as conn:
        for index, group_name in enumerate(payload.groups):
            clean_group = " ".join(group_name.strip().split()) or "Ungrouped"
            conn.execute(
                """
                INSERT INTO group_prefs(group_name, sort_order)
                VALUES (?, ?)
                ON CONFLICT(group_name) DO UPDATE SET sort_order=excluded.sort_order
                """,
                (clean_group, index),
            )
        for names in payload.containers.values():
            for index, container_name in enumerate(names):
                clean_name = container_name.strip()
                if not clean_name:
                    continue
                conn.execute(
                    """
                    INSERT INTO container_prefs(container_name, sort_order)
                    VALUES (?, ?)
                    ON CONFLICT(container_name) DO UPDATE SET sort_order=excluded.sort_order
                    """,
                    (clean_name, index),
                )
    return {"ok": True}


def get_webui_links() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT link_key, label, url, icon, container_name, enabled, sort_order, source
            FROM webui_links
            ORDER BY sort_order, label
            """
        ).fetchall()
    return [
        {
            "link_key": row["link_key"],
            "label": row["label"],
            "url": row["url"],
            "icon": row["icon"],
            "container_name": row["container_name"],
            "enabled": bool(row["enabled"]),
            "sort_order": row["sort_order"],
            "source": row["source"],
        }
        for row in rows
    ]


def save_webui_links(payload: WebuiLinksPayload) -> dict:
    with db() as conn:
        conn.execute("DELETE FROM webui_links")
        for index, link in enumerate(payload.links):
            conn.execute(
                """
                INSERT INTO webui_links(link_key, label, url, icon, container_name, enabled, sort_order, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.link_key.strip(),
                    link.label.strip(),
                    link.url.strip(),
                    link.icon.strip().lower(),
                    link.container_name.strip(),
                    1 if link.enabled else 0,
                    link.sort_order if link.sort_order >= 0 else index,
                    link.source,
                ),
            )
    return {"links": get_webui_links()}


def icon_slugs() -> list[str]:
    icons = set()
    for icon_dir in (BUNDLED_ICON_DIR, USER_ICON_DIR):
        if icon_dir.is_dir():
            icons.update(path.stem for path in icon_dir.glob("*.svg") if ICON_RE.fullmatch(path.stem))
    return sorted(icons)


def icon_file(icon: str) -> Path | None:
    if not ICON_RE.fullmatch(icon):
        return None
    for icon_dir in (USER_ICON_DIR, BUNDLED_ICON_DIR):
        path = icon_dir / f"{icon}.svg"
        if path.is_file():
            return path
    return None


def download_dashboard_icon(icon: str) -> dict:
    if not ICON_RE.fullmatch(icon):
        raise HTTPException(status_code=422, detail="Use a lowercase Dashboard Icons slug.")
    USER_ICON_DIR.mkdir(parents=True, exist_ok=True)
    request = UrlRequest(f"{DASHBOARD_ICON_CDN}/{icon}.svg", headers={"User-Agent": "Homelab-Hub/1.0"})
    try:
        with urlopen(request, timeout=12) as response:
            content = response.read(1024 * 1024)
    except HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(status_code=404, detail=f"No Dashboard Icons SVG found for '{icon}'.") from exc
        raise HTTPException(status_code=502, detail=f"Dashboard Icons returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach Dashboard Icons: {exc.reason}") from exc
    if b"<svg" not in content[:500].lower():
        raise HTTPException(status_code=502, detail="Downloaded file was not an SVG icon.")
    dest = USER_ICON_DIR / f"{icon}.svg"
    tmp = dest.with_suffix(".svg.tmp")
    tmp.write_bytes(content)
    tmp.replace(dest)
    return {"icon": icon, "icons": icon_slugs()}


def docker_client():
    try:
        return docker.from_env(timeout=5)
    except DockerException as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


def is_authenticated(request: Request) -> bool:
    if not ADMIN_PASSWORD:
        return False
    token = request.cookies.get("hub_session")
    if not token:
        return False
    try:
        data = signer.loads(token)
        return data.get("authenticated") is True
    except BadSignature:
        return False


def require_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Authentication required")


def cpu_percent(stats: dict) -> float:
    cpu = stats.get("cpu_stats", {})
    precpu = stats.get("precpu_stats", {})
    cpu_delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - precpu.get("cpu_usage", {}).get("total_usage", 0)
    system_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
    online_cpus = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage") or []) or 1
    if cpu_delta > 0 and system_delta > 0:
        return round((cpu_delta / system_delta) * online_cpus * 100.0, 2)
    return 0.0


def mem_values(stats: dict) -> tuple[int, int, float]:
    mem = stats.get("memory_stats", {})
    usage = int(mem.get("usage", 0))
    cache = int(mem.get("stats", {}).get("inactive_file", 0))
    actual = max(usage - cache, 0)
    limit = int(mem.get("limit", 0))
    pct = round((actual / limit) * 100.0, 2) if limit else 0.0
    return actual, limit, pct


def collect_container(container, include_stats: bool = True) -> dict:
    attrs = container.attrs
    state = attrs.get("State", {})
    ports = attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
    published_ports = []
    seen_ports = set()
    for internal, bindings in ports.items():
        if not bindings:
            continue
        for binding in bindings:
            host_ip = binding.get("HostIp", "")
            host_port = binding.get("HostPort", "")
            port_key = (internal, host_port)
            if port_key in seen_ports:
                continue
            seen_ports.add(port_key)
            published_ports.append({"internal": internal, "host_ip": host_ip, "host_port": host_port})

    cpu = mem_used = mem_limit = mem_pct = 0
    if include_stats and state.get("Running"):
        try:
            stats = container.stats(stream=False, one_shot=True)
            cpu = cpu_percent(stats)
            mem_used, mem_limit, mem_pct = mem_values(stats)
        except Exception:
            pass

    health = state.get("Health", {}).get("Status")
    labels = attrs.get("Config", {}).get("Labels", {}) or {}
    return {
        "id": container.id,
        "short_id": container.short_id,
        "name": container.name,
        "image": attrs.get("Config", {}).get("Image", ""),
        "status": container.status,
        "health": health,
        "created": attrs.get("Created"),
        "restart_policy": attrs.get("HostConfig", {}).get("RestartPolicy", {}).get("Name", ""),
        "cpu_percent": cpu,
        "memory_used": mem_used,
        "memory_limit": mem_limit,
        "memory_percent": mem_pct,
        "ports": published_ports,
        "project": labels.get("com.docker.compose.project"),
        "service": labels.get("com.docker.compose.service"),
    }


def fmt_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def pct(part: int | float, total: int | float) -> float:
    if not total:
        return 0.0
    return round(min(max((part / total) * 100.0, 0.0), 100.0), 1)


def read_meminfo() -> dict:
    values: dict[str, int] = {}
    try:
        with Path("/proc/meminfo").open("r", encoding="utf-8") as handle:
            for line in handle:
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return {}

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = max(total - available, 0)
    return {
        "total": total,
        "used": used,
        "available": available,
        "percent": pct(used, total),
        "total_human": fmt_bytes(total),
        "used_human": fmt_bytes(used),
        "available_human": fmt_bytes(available),
    }


def read_cpu_sample() -> dict[str, tuple[int, int]]:
    sample: dict[str, tuple[int, int]] = {}
    try:
        with Path("/proc/stat").open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.startswith("cpu"):
                    break
                parts = line.split()
                name = parts[0]
                if name != "cpu" and not name[3:].isdigit():
                    continue
                values = [int(value) for value in parts[1:]]
                idle = values[3] + (values[4] if len(values) > 4 else 0)
                total = sum(values)
                sample[name] = (total, idle)
    except (OSError, ValueError):
        return {}
    return sample


def cpu_usage() -> dict:
    global LAST_CPU_SAMPLE
    sample = read_cpu_sample()
    if not sample:
        return {"total_percent": 0.0, "cores": []}

    with CPU_SAMPLE_LOCK:
        previous = LAST_CPU_SAMPLE
        LAST_CPU_SAMPLE = sample

    def usage_for(name: str) -> float:
        if not previous or name not in previous:
            return 0.0
        total, idle = sample[name]
        prev_total, prev_idle = previous[name]
        total_delta = total - prev_total
        idle_delta = idle - prev_idle
        if total_delta <= 0:
            return 0.0
        return round(min(max((1 - idle_delta / total_delta) * 100.0, 0.0), 100.0), 1)

    cores = [
        {"name": f"CPU {name[3:]}", "percent": usage_for(name)}
        for name in sorted((key for key in sample if key != "cpu"), key=lambda value: int(value[3:]))
    ]
    return {"total_percent": usage_for("cpu"), "cores": cores}


def disk_usage(path: Path) -> dict:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return {}
    used = usage.total - usage.free
    return {
        "path": str(path),
        "total": usage.total,
        "used": used,
        "free": usage.free,
        "percent": pct(used, usage.total),
        "total_human": fmt_bytes(usage.total),
        "used_human": fmt_bytes(used),
        "free_human": fmt_bytes(usage.free),
    }


def network_usage() -> dict:
    rx = tx = 0
    try:
        with Path("/proc/net/dev").open("r", encoding="utf-8") as handle:
            for line in handle.readlines()[2:]:
                name, raw = line.split(":", 1)
                iface = name.strip()
                if iface == "lo":
                    continue
                parts = raw.split()
                rx += int(parts[0])
                tx += int(parts[8])
    except (OSError, ValueError, IndexError):
        return {}

    global LAST_NETWORK_SAMPLE
    now = time.time()
    with NETWORK_SAMPLE_LOCK:
        previous = LAST_NETWORK_SAMPLE
        LAST_NETWORK_SAMPLE = (now, rx, tx)

    rx_rate = tx_rate = 0
    if previous:
        then, prev_rx, prev_tx = previous
        elapsed = max(now - then, 0.001)
        rx_rate = max(int((rx - prev_rx) / elapsed), 0)
        tx_rate = max(int((tx - prev_tx) / elapsed), 0)

    return {
        "rx": rx,
        "tx": tx,
        "rx_human": fmt_bytes(rx),
        "tx_human": fmt_bytes(tx),
        "rx_rate": rx_rate,
        "tx_rate": tx_rate,
        "rx_rate_human": f"{fmt_bytes(rx_rate)}/s",
        "tx_rate_human": f"{fmt_bytes(tx_rate)}/s",
    }


def process_rows(memory_total: int) -> tuple[int, dict[str, tuple[int, int]], list[dict]]:
    sample: dict[str, tuple[int, int]] = {}
    rows = []
    cpu_sample = read_cpu_sample()
    total_cpu = cpu_sample.get("cpu", (0, 0))[0]
    page_size = os.sysconf("SC_PAGE_SIZE")
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            stat = (proc / "stat").read_text(encoding="utf-8")
            status = (proc / "status").read_text(encoding="utf-8")
            end = stat.rfind(")")
            name = stat[stat.find("(") + 1 : end]
            parts = stat[end + 2 :].split()
            utime = int(parts[11])
            stime = int(parts[12])
            start_time = int(parts[19])
            rss_pages = int(parts[21])
            uid = "0"
            for line in status.splitlines():
                if line.startswith("Uid:"):
                    uid = line.split()[1]
                    break
            user = pwd.getpwuid(int(uid)).pw_name
        except (OSError, ValueError, KeyError, IndexError):
            continue
        key = f"{proc.name}:{start_time}"
        cpu_ticks = utime + stime
        sample[key] = (cpu_ticks, start_time)
        rss = max(rss_pages, 0) * page_size
        rows.append(
            {
                "key": key,
                "name": name[:42],
                "user": user[:32],
                "cpu_ticks": cpu_ticks,
                "memory_percent": pct(rss, memory_total),
                "memory_human": fmt_bytes(rss),
            }
        )
    return total_cpu, sample, rows


def top_processes() -> dict:
    global LAST_PROC_SAMPLE, LAST_PROC_TOTAL
    memory_total = read_meminfo().get("total", 0)
    total_cpu, sample, rows = process_rows(memory_total)
    with PROC_SAMPLE_LOCK:
        previous = LAST_PROC_SAMPLE
        previous_total = LAST_PROC_TOTAL
        LAST_PROC_SAMPLE = sample
        LAST_PROC_TOTAL = total_cpu

    total_delta = total_cpu - previous_total if previous_total else 0
    for row in rows:
        previous_ticks = previous.get(row["key"], (row["cpu_ticks"], 0))[0] if previous else row["cpu_ticks"]
        row["cpu_percent"] = round(pct(max(row["cpu_ticks"] - previous_ticks, 0), total_delta), 1)
    return {
        "cpu": sorted(rows, key=lambda row: row["cpu_percent"], reverse=True)[:5],
        "memory": sorted(rows, key=lambda row: row["memory_percent"], reverse=True)[:5],
    }


def host_metrics(info: dict) -> dict:
    return {
        "cpu": cpu_usage(),
        "memory": read_meminfo(),
        "data_mount": disk_usage(DATA_DIR),
        "network": network_usage(),
        "top_processes": top_processes(),
    }


INTEGRATION_ENV = {
    "jellyfin_url": "HUB_JELLYFIN_URL",
    "jellyfin_public_url": "HUB_JELLYFIN_PUBLIC_URL",
    "jellyfin_api_key": "HUB_JELLYFIN_API_KEY",
    "nextcloud_calendar_url": "HUB_NEXTCLOUD_CALENDAR_URL",
    "nextcloud_url": "HUB_NEXTCLOUD_URL",
    "nextcloud_username": "HUB_NEXTCLOUD_USERNAME",
    "nextcloud_app_password": "HUB_NEXTCLOUD_APP_PASSWORD",
    "nextcloud_calendar_name": "HUB_NEXTCLOUD_CALENDAR_NAME",
    "home_assistant_url": "HUB_HOME_ASSISTANT_URL",
    "home_assistant_token": "HUB_HOME_ASSISTANT_TOKEN",
    "home_assistant_entities": "HUB_HOME_ASSISTANT_ENTITIES",
}
SECRET_INTEGRATION_KEYS = {"jellyfin_api_key", "nextcloud_app_password", "home_assistant_token"}


def env_value(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def get_integration_values() -> dict[str, str]:
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM integration_settings").fetchall()
    stored = {row["key"]: row["value"] for row in rows}
    return {
        key: stored[key] if key in stored else env_value(env_name)
        for key, env_name in INTEGRATION_ENV.items()
    }


def public_integration_settings() -> dict:
    values = get_integration_values()
    return {
        "jellyfin_url": values["jellyfin_url"],
        "jellyfin_public_url": values["jellyfin_public_url"],
        "jellyfin_api_key_configured": bool(values["jellyfin_api_key"]),
        "nextcloud_calendar_url": values["nextcloud_calendar_url"],
        "nextcloud_url": values["nextcloud_url"],
        "nextcloud_username": values["nextcloud_username"],
        "nextcloud_app_password_configured": bool(values["nextcloud_app_password"]),
        "nextcloud_calendar_name": values["nextcloud_calendar_name"],
        "home_assistant_url": values["home_assistant_url"],
        "home_assistant_token_configured": bool(values["home_assistant_token"]),
        "home_assistant_entities": values["home_assistant_entities"],
    }


def save_integration_settings(payload: IntegrationSettingsPayload) -> dict:
    values = {
        "jellyfin_url": payload.jellyfin_url.strip().rstrip("/"),
        "jellyfin_public_url": payload.jellyfin_public_url.strip().rstrip("/"),
        "nextcloud_calendar_url": payload.nextcloud_calendar_url.strip(),
        "nextcloud_url": payload.nextcloud_url.strip().rstrip("/"),
        "nextcloud_username": payload.nextcloud_username.strip(),
        "nextcloud_calendar_name": payload.nextcloud_calendar_name.strip(),
        "home_assistant_url": payload.home_assistant_url.strip().rstrip("/"),
        "home_assistant_entities": ",".join(
            item.strip() for item in payload.home_assistant_entities.split(",") if item.strip()
        ),
    }
    secrets_to_write = {}
    if payload.jellyfin_api_key_clear:
        secrets_to_write["jellyfin_api_key"] = ""
    elif payload.jellyfin_api_key.strip():
        secrets_to_write["jellyfin_api_key"] = payload.jellyfin_api_key.strip()
    if payload.nextcloud_app_password_clear:
        secrets_to_write["nextcloud_app_password"] = ""
    elif payload.nextcloud_app_password.strip():
        secrets_to_write["nextcloud_app_password"] = payload.nextcloud_app_password.strip()
    if payload.home_assistant_token_clear:
        secrets_to_write["home_assistant_token"] = ""
    elif payload.home_assistant_token.strip():
        secrets_to_write["home_assistant_token"] = payload.home_assistant_token.strip()

    with db() as conn:
        for key, value in {**values, **secrets_to_write}.items():
            conn.execute(
                """
                INSERT INTO integration_settings(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
    return public_integration_settings()


def integration_config() -> dict:
    values = get_integration_values()
    return {
        "jellyfin_url": values["jellyfin_url"].rstrip("/"),
        "jellyfin_public_url": values["jellyfin_public_url"].rstrip("/"),
        "jellyfin_api_key": values["jellyfin_api_key"],
        "nextcloud_calendar_url": values["nextcloud_calendar_url"],
        "nextcloud_url": values["nextcloud_url"].rstrip("/"),
        "nextcloud_username": values["nextcloud_username"],
        "nextcloud_app_password": values["nextcloud_app_password"],
        "nextcloud_calendar_name": values["nextcloud_calendar_name"],
        "home_assistant_url": values["home_assistant_url"].rstrip("/"),
        "home_assistant_token": values["home_assistant_token"],
        "home_assistant_entities": [
            item.strip()
            for item in values["home_assistant_entities"].split(",")
            if item.strip()
        ],
    }


def http_request(url: str, headers: dict | None = None, data: bytes | None = None, timeout: int = 7, method: str | None = None):
    request = UrlRequest(url, data=data, headers={"User-Agent": "Homelab-Hub/1.0", **(headers or {})}, method=method)
    return urlopen(request, timeout=timeout)


def http_json(url: str, headers: dict | None = None, data: bytes | None = None, timeout: int = 7) -> dict | list:
    with http_request(url, headers=headers, data=data, timeout=timeout) as response:
        return json.loads(response.read(1024 * 1024).decode("utf-8", errors="replace"))


def http_text(url: str, headers: dict | None = None, timeout: int = 7) -> str:
    with http_request(url, headers=headers, timeout=timeout) as response:
        return response.read(2 * 1024 * 1024).decode("utf-8", errors="replace")


def basic_auth_header(username: str, password: str) -> str:
    raw = f"{username}:{password}".encode("utf-8")
    return f"Basic {b64encode(raw).decode('ascii')}"


def host_base_url(request: Request) -> str:
    hostname = request.url.hostname or "localhost"
    return hostname


def discover_service_url(client, request: Request, terms: list[str], ports: set[str]) -> str:
    hostname = host_base_url(request)
    for container in client.containers.list(all=True):
        try:
            attrs = container.attrs
            identity = f"{container.name} {attrs.get('Config', {}).get('Image', '')}".lower()
            if not any(term in identity for term in terms):
                continue
            published = attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
            for internal, bindings in published.items():
                internal_port, protocol = StringPort(internal).parts()
                if protocol != "tcp" or internal_port not in ports or not bindings:
                    continue
                host_port = bindings[0].get("HostPort")
                if host_port:
                    return f"http://{hostname}:{host_port}"
        except Exception:
            continue
    return ""


class StringPort:
    def __init__(self, value: str):
        self.value = str(value or "")

    def parts(self) -> tuple[str, str]:
        port, _, protocol = self.value.partition("/")
        return port, protocol or "tcp"


def jellyfin_sessions(client, request: Request, cfg: dict) -> dict:
    configured_url = cfg["jellyfin_url"]
    discovered_url = "" if configured_url else discover_service_url(client, request, ["jellyfin"], {"8096", "8920"})
    base_url = configured_url or discovered_url
    public_url = cfg["jellyfin_public_url"] or base_url
    result = {
        "configured": bool(base_url and cfg["jellyfin_api_key"]),
        "url": public_url,
        "active": [],
        "source": "configured" if configured_url else ("docker" if discovered_url else ""),
    }
    if not base_url or not cfg["jellyfin_api_key"]:
        result["message"] = "Configure Jellyfin in Connectors. The internal URL is optional if Docker exposes port 8096/8920."
        return result
    try:
        sessions = http_json(f"{base_url}/Sessions", headers={"X-Emby-Token": cfg["jellyfin_api_key"]})
    except HTTPError as exc:
        result["error"] = f"Jellyfin returned HTTP {exc.code}."
        return result
    except (OSError, URLError, ValueError) as exc:
        result["error"] = f"Could not reach Jellyfin: {exc}"
        return result
    for session in sessions if isinstance(sessions, list) else []:
        item = session.get("NowPlayingItem")
        if not item:
            continue
        state = session.get("PlayState", {}) or {}
        result["active"].append(
            {
                "user_id": session.get("UserId") or "",
                "avatar_url": f"/api/jellyfin/users/{session.get('UserId')}/avatar" if session.get("UserId") else "",
                "user": session.get("UserName") or "Unknown user",
                "client": session.get("Client") or "",
                "device": session.get("DeviceName") or "",
                "item": item.get("Name") or "Unknown media",
                "series": item.get("SeriesName") or "",
                "type": item.get("Type") or "",
                "paused": bool(state.get("IsPaused")),
                "position_ticks": state.get("PositionTicks") or 0,
                "runtime_ticks": item.get("RunTimeTicks") or 0,
            }
        )
    return result


def unfold_ics_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def split_ics_line(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    parts = head.split(";")
    name = parts[0].upper()
    params = {}
    for part in parts[1:]:
        key, _, param_value = part.partition("=")
        params[key.upper()] = param_value
    return name, params, ics_unescape(value)


def ics_unescape(value: str) -> str:
    return (
        value.replace(r"\n", " ")
        .replace(r"\N", " ")
        .replace(r"\,", ",")
        .replace(r"\;", ";")
        .replace(r"\\", "\\")
    )


def parse_ics_datetime(value: str, params: dict[str, str]) -> datetime | None:
    try:
        if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
            return datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
        clean = value.rstrip("Z")
        fmt = "%Y%m%dT%H%M%S" if len(clean) >= 15 else "%Y%m%dT%H%M"
        dt = datetime.strptime(clean[:15 if fmt.endswith("%S") else 13], fmt)
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_rrule(value: str) -> dict[str, str]:
    rule = {}
    for chunk in value.split(";"):
        key, _, raw = chunk.partition("=")
        if key and raw:
            rule[key.upper()] = raw
    return rule


def recurrence_delta(rule: dict[str, str]) -> timedelta | None:
    try:
        interval = max(int(rule.get("INTERVAL", "1") or "1"), 1)
    except ValueError:
        interval = 1
    freq = rule.get("FREQ", "").upper()
    if freq == "DAILY":
        return timedelta(days=interval)
    if freq == "WEEKLY":
        return timedelta(weeks=interval)
    return None


def parse_calendar_text(text: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=7)
    events = []
    current: dict | None = None
    for line in unfold_ics_lines(text):
        name, params, value = split_ics_line(line)
        if name == "BEGIN" and value == "VEVENT":
            current = {}
        elif name == "END" and value == "VEVENT" and current is not None:
            start = current.get("start")
            if start:
                duration = (current.get("end") or start) - start
                rule = current.get("rrule") or {}
                step = recurrence_delta(rule)
                try:
                    count = int(rule.get("COUNT", "0") or "0")
                except ValueError:
                    count = 0
                occurrence = start
                emitted = 0
                if step and occurrence < now:
                    skip = max(int((now - occurrence) // step) - 1, 0)
                    if count and skip >= count:
                        current = None
                        continue
                    occurrence += step * skip
                    emitted += skip
                while occurrence <= horizon and emitted < 80:
                    if occurrence >= now:
                        events.append({**current, "start": occurrence, "end": occurrence + duration})
                    emitted += 1
                    if not step:
                        break
                    if count and emitted >= count:
                        break
                    occurrence += step
            current = None
        elif current is not None:
            if name == "DTSTART":
                current["start"] = parse_ics_datetime(value, params)
                current["all_day"] = params.get("VALUE") == "DATE"
            elif name == "DTEND":
                current["end"] = parse_ics_datetime(value, params)
            elif name == "SUMMARY":
                current["summary"] = value
            elif name == "LOCATION":
                current["location"] = value
            elif name == "RRULE":
                current["rrule"] = parse_rrule(value)

    return [
        {
            "summary": event.get("summary") or "Untitled event",
            "location": event.get("location") or "",
            "start": event["start"].isoformat(),
            "end": event.get("end").isoformat() if event.get("end") else "",
            "all_day": bool(event.get("all_day")),
        }
        for event in sorted(events, key=lambda item: item["start"])[:12]
    ]


def caldav_headers(cfg: dict) -> dict:
    return {
        "Authorization": basic_auth_header(cfg["nextcloud_username"], cfg["nextcloud_app_password"]),
        "Content-Type": "application/xml; charset=utf-8",
        "Depth": "1",
    }


def caldav_home_url(cfg: dict) -> str:
    base = cfg["nextcloud_url"].rstrip("/") + "/"
    user = quote(cfg["nextcloud_username"].strip("/"), safe="")
    return urljoin(base, f"remote.php/dav/calendars/{user}/")


def caldav_request(url: str, body: str, cfg: dict, method: str = "REPORT") -> str:
    with http_request(
        url,
        headers=caldav_headers(cfg),
        data=body.encode("utf-8"),
        timeout=10,
        method=method,
    ) as response:
        return response.read(4 * 1024 * 1024).decode("utf-8", errors="replace")


def caldav_href_url(base_url: str, href: str) -> str:
    if href.startswith(("http://", "https://")):
        return href
    parsed = urlparse(base_url)
    if href.startswith("/"):
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    return urljoin(base_url.rstrip("/") + "/", href)


def caldav_calendars(cfg: dict) -> list[dict]:
    body = """
<d:propfind xmlns:d="DAV:" xmlns:cs="http://calendarserver.org/ns/" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:displayname />
    <d:resourcetype />
  </d:prop>
</d:propfind>
"""
    xml = caldav_request(caldav_home_url(cfg), body, cfg, method="PROPFIND")
    root = ET.fromstring(xml)
    calendars = []
    ns = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}
    for response in root.findall("d:response", ns):
        href = response.findtext("d:href", default="", namespaces=ns)
        resource = response.find(".//d:resourcetype", ns)
        if resource is None or resource.find("c:calendar", ns) is None:
            continue
        display = response.findtext(".//d:displayname", default="", namespaces=ns)
        calendars.append({"href": href, "name": display or href.strip("/").split("/")[-1]})
    return calendars


def caldav_calendar_events(cfg: dict) -> dict:
    result = {"configured": True, "events": [], "source": "caldav"}
    try:
        calendars = caldav_calendars(cfg)
        if not calendars:
            result["message"] = "No Nextcloud calendars found for this account."
            return result
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=7)
        body = f"""
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag />
    <c:calendar-data />
  </d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{now.strftime('%Y%m%dT%H%M%SZ')}" end="{horizon.strftime('%Y%m%dT%H%M%SZ')}" />
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>
"""
        events = []
        ns = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}
        base = cfg["nextcloud_url"].rstrip("/")
        for calendar in calendars[:8]:
            url = caldav_href_url(base, calendar["href"])
            xml = caldav_request(url, body, cfg)
            root = ET.fromstring(xml)
            for data in root.findall(".//c:calendar-data", ns):
                if data.text:
                    for event in parse_calendar_text(data.text):
                        event["calendar"] = calendar["name"]
                        events.append(event)
        result["events"] = sorted(events, key=lambda item: item["start"])[:12]
        result["calendars"] = [item["name"] for item in calendars]
    except HTTPError as exc:
        result["error"] = f"Nextcloud CalDAV returned HTTP {exc.code}."
    except (OSError, URLError, ValueError, ET.ParseError) as exc:
        result["error"] = f"Could not query Nextcloud CalDAV: {exc}"
    return result


def calendar_events(cfg: dict) -> dict:
    caldav_ready = bool(cfg["nextcloud_url"] and cfg["nextcloud_username"] and cfg["nextcloud_app_password"])
    if caldav_ready:
        return caldav_calendar_events(cfg)

    result = {"configured": bool(cfg["nextcloud_calendar_url"]), "events": [], "source": "public"}
    if not cfg["nextcloud_calendar_url"]:
        result["message"] = "Configure private Nextcloud CalDAV login or a public calendar export link in Connectors."
        return result
    try:
        result["events"] = parse_calendar_text(http_text(cfg["nextcloud_calendar_url"]))
    except HTTPError as exc:
        result["error"] = f"Calendar returned HTTP {exc.code}."
    except (OSError, URLError) as exc:
        result["error"] = f"Could not reach calendar: {exc}"
    return result


def home_assistant_state(cfg: dict) -> dict:
    base_configured = bool(cfg["home_assistant_url"] and cfg["home_assistant_token"])
    result = {
        "configured": base_configured,
        "entities": [],
    }
    if not base_configured:
        result["message"] = "Configure the Home Assistant URL and token in Connectors."
        return result
    headers = {"Authorization": f"Bearer {cfg['home_assistant_token']}"}
    entity_ids = cfg["home_assistant_entities"][:48]
    if not entity_ids:
        try:
            states = http_json(f"{cfg['home_assistant_url']}/api/states", headers=headers)
            domains = {"light", "switch", "sensor", "binary_sensor", "climate", "cover", "fan"}
            entity_ids = [
                item.get("entity_id", "")
                for item in (states if isinstance(states, list) else [])
                if isinstance(item, dict)
                if item.get("entity_id", "").split(".", 1)[0] in domains
            ][:60]
            result["discovered"] = True
        except HTTPError as exc:
            result["error"] = f"Home Assistant returned HTTP {exc.code}."
            return result
        except (OSError, URLError, ValueError) as exc:
            result["error"] = f"Could not query Home Assistant entities: {exc}"
            return result
    for entity_id in entity_ids:
        try:
            state = http_json(f"{cfg['home_assistant_url']}/api/states/{entity_id}", headers=headers)
            attrs = state.get("attributes", {}) if isinstance(state, dict) else {}
            result["entities"].append(
                {
                    "entity_id": entity_id,
                    "state": state.get("state", "unknown") if isinstance(state, dict) else "unknown",
                    "name": attrs.get("friendly_name") or entity_id,
                    "unit": attrs.get("unit_of_measurement") or "",
                    "domain": entity_id.split(".", 1)[0],
                    "rgb_color": attrs.get("rgb_color") or [],
                    "brightness": attrs.get("brightness"),
                    "supported_color_modes": sorted(attrs.get("supported_color_modes") or []),
                }
            )
        except HTTPError as exc:
            result["entities"].append({"entity_id": entity_id, "state": "error", "name": entity_id, "error": f"HTTP {exc.code}"})
        except (OSError, URLError, ValueError) as exc:
            result["entities"].append({"entity_id": entity_id, "state": "error", "name": entity_id, "error": str(exc)})
    return result


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/icons/dashboard/{icon}.svg")
def dashboard_icon(icon: str):
    path = icon_file(icon)
    if path is None:
        raise HTTPException(status_code=404, detail="Icon not found")
    return FileResponse(path, media_type="image/svg+xml")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    html = templates.get_template("login.html").render(password_configured=bool(ADMIN_PASSWORD))
    return HTMLResponse(html)


@app.post("/login")
def login(password: str = Form(...)):
    if not ADMIN_PASSWORD:
        return RedirectResponse("/login?error=missing", status_code=303)
    if not secrets.compare_digest(password, ADMIN_PASSWORD):
        return RedirectResponse("/login?error=invalid", status_code=303)
    token = signer.dumps({"authenticated": True, "iat": int(time.time())})
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "hub_session",
        token,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=60 * 60 * 24 * 30,
    )
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("hub_session")
    return response


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    html = templates.get_template("index.html").render(server_name=SERVER_NAME, settings=get_settings())
    return HTMLResponse(html)


@app.get("/api/overview")
def overview(
    request: Request,
    include_containers: bool = Query(True),
    include_stats: bool = Query(True),
    include_metrics: bool = Query(True),
):
    require_auth(request)
    client = docker_client()
    try:
        info = client.info()
        version = client.version()
        containers = client.containers.list(all=True)
        results = []
        if include_containers:
            workers = min(max(len(containers), 1), 16)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(collect_container, c, include_stats): c.id for c in containers}
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        results.append({"id": futures[future], "name": "unknown", "status": "error", "error": str(exc)})
            results.sort(key=lambda x: x.get("name", "").lower())
            prefs = get_container_prefs()
            for container in results:
                pref = prefs.get(container.get("name"), {})
                container["icon"] = pref.get("icon") or ""
                container["group_name"] = pref.get("group_name") or ""
                container["sort_order"] = pref.get("sort_order", 0)

        running = sum(1 for c in containers if c.status == "running")
        paused = sum(1 for c in containers if c.status == "paused")
        stopped = len(containers) - running - paused
        payload = {
            "server": {
                "name": SERVER_NAME,
                "docker_version": version.get("Version"),
                "api_version": version.get("ApiVersion"),
                "os": info.get("OperatingSystem"),
                "kernel": info.get("KernelVersion"),
                "cpus": info.get("NCPU"),
                "memory_total": info.get("MemTotal", 0),
                "memory_total_human": fmt_bytes(info.get("MemTotal", 0)),
                "containers_total": len(containers),
                "containers_running": running,
                "containers_paused": paused,
                "containers_stopped": stopped,
                "images": info.get("Images"),
            },
            "group_order": get_group_order(),
            "settings": get_settings(),
            "webui_links": get_webui_links(),
        }
        if include_metrics:
            payload["server"]["metrics"] = host_metrics(info)
        if include_containers:
            payload["containers"] = results
        return payload
    except DockerException as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass


@app.get("/api/integrations")
def integrations(request: Request):
    require_auth(request)
    cfg = integration_config()
    client = docker_client()
    try:
        return {
            "jellyfin": jellyfin_sessions(client, request, cfg),
            "calendar": calendar_events(cfg),
            "home_assistant": home_assistant_state(cfg),
        }
    finally:
        try:
            client.close()
        except Exception:
            pass


@app.get("/api/jellyfin/users/{user_id}/avatar")
def jellyfin_user_avatar(user_id: str, request: Request):
    require_auth(request)
    cfg = integration_config()
    base_url = cfg["jellyfin_url"]
    client = None
    if not base_url:
        client = docker_client()
        base_url = discover_service_url(client, request, ["jellyfin"], {"8096", "8920"})
    if not base_url or not cfg["jellyfin_api_key"]:
        raise HTTPException(status_code=404, detail="Jellyfin is not configured.")
    safe_user = re.sub(r"[^A-Za-z0-9_-]", "", user_id)
    if not safe_user:
        raise HTTPException(status_code=404, detail="Invalid Jellyfin user.")
    try:
        with http_request(
            f"{base_url}/Users/{safe_user}/Images/Primary",
            headers={"X-Emby-Token": cfg["jellyfin_api_key"]},
            timeout=8,
        ) as response:
            return Response(content=response.read(1024 * 1024), media_type=response.headers.get("Content-Type", "image/jpeg"))
    except (HTTPError, OSError, URLError) as exc:
        raise HTTPException(status_code=404, detail=f"Jellyfin avatar unavailable: {exc}") from exc
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass


def home_assistant_headers(cfg: dict) -> dict:
    return {
        "Authorization": f"Bearer {cfg['home_assistant_token']}",
        "Content-Type": "application/json",
    }


def home_assistant_service(cfg: dict, domain: str, service: str, payload: dict):
    return http_json(
        f"{cfg['home_assistant_url']}/api/services/{domain}/{service}",
        headers=home_assistant_headers(cfg),
        data=json.dumps(payload).encode("utf-8"),
    )


def light_entities(cfg: dict) -> list[str]:
    configured = [entity for entity in cfg["home_assistant_entities"] if entity.startswith("light.")]
    if configured:
        return configured
    try:
        states = http_json(f"{cfg['home_assistant_url']}/api/states", headers=home_assistant_headers(cfg))
        return [
            item.get("entity_id", "")
            for item in (states if isinstance(states, list) else [])
            if isinstance(item, dict) and item.get("entity_id", "").startswith("light.")
        ][:24]
    except Exception:
        return []


def ensure_home_assistant(cfg: dict) -> None:
    if not cfg["home_assistant_url"] or not cfg["home_assistant_token"]:
        raise HTTPException(status_code=400, detail="Home Assistant URL and token are not configured.")


def hex_to_rgb(color: str) -> list[int]:
    clean = color.lstrip("#")
    return [int(clean[index : index + 2], 16) for index in (0, 2, 4)]


def party_delay(craziness: int) -> float:
    normalized = (max(1, min(craziness, 10)) - 1) / 9
    return round(3.0 - (normalized * 2.75), 2)


def clamp_color_temp(attrs: dict, white_mode: str) -> int:
    value = WHITE_MODE_KELVIN.get(white_mode, WHITE_MODE_KELVIN["auto"])
    minimum = attrs.get("min_color_temp_kelvin")
    maximum = attrs.get("max_color_temp_kelvin")
    if isinstance(minimum, int):
        value = max(value, minimum)
    if isinstance(maximum, int):
        value = min(value, maximum)
    return value


def light_attributes(cfg: dict, entity_id: str) -> dict:
    try:
        state = http_json(
            f"{cfg['home_assistant_url']}/api/states/{entity_id}",
            headers={"Authorization": f"Bearer {cfg['home_assistant_token']}"},
        )
        return state.get("attributes", {}) if isinstance(state, dict) else {}
    except Exception:
        return {}


def white_channel_payload(white_mode: str, supported: set[str]) -> dict | None:
    if "rgbww" in supported:
        if white_mode == "warm":
            return {"rgbww_color": [0, 0, 0, 0, 255]}
        if white_mode == "cold":
            return {"rgbww_color": [0, 0, 0, 255, 0]}
        return {"rgbww_color": [0, 0, 0, 255, 255]}
    if "rgbw" in supported:
        return {"rgbw_color": [0, 0, 0, 255]}
    return None


def restore_light_default(cfg: dict, entity_id: str, white_mode: str) -> None:
    attrs = light_attributes(cfg, entity_id)
    supported = set(attrs.get("supported_color_modes") or [])
    payload = {"entity_id": entity_id, "brightness": 255, "transition": 0}
    channel_payload = white_channel_payload(white_mode, supported)
    if white_mode in {"warm", "cold", "cold_warm"} and channel_payload:
        payload.update(channel_payload)
    elif "color_temp" in supported:
        payload["color_temp_kelvin"] = clamp_color_temp(attrs, white_mode)
    elif channel_payload:
        payload.update(channel_payload)
    try:
        home_assistant_service(cfg, "light", "turn_on", payload)
    except Exception:
        home_assistant_service(cfg, "light", "turn_on", {"entity_id": entity_id, "brightness_pct": 100, "transition": 0})


def party_worker(cfg: dict):
    colors = [[255, 0, 80], [255, 140, 0], [255, 255, 0], [0, 255, 120], [0, 180, 255], [120, 70, 255], [255, 0, 220]]
    while not PARTY_MODE_STOP.is_set():
        for entity_id in light_entities(cfg):
            try:
                home_assistant_service(cfg, "light", "turn_on", {"entity_id": entity_id, "rgb_color": random.choice(colors), "brightness": 255, "transition": 0})
            except Exception:
                pass
        PARTY_MODE_STOP.wait(PARTY_MODE_DELAY)


@app.post("/api/home-assistant/toggle")
def home_assistant_toggle(payload: HomeAssistantTogglePayload, request: Request):
    require_auth(request)
    cfg = integration_config()
    ensure_home_assistant(cfg)
    if not payload.entity_id.startswith("light."):
        raise HTTPException(status_code=400, detail="Only light entities can be toggled from Homelab Hub.")
    try:
        home_assistant_service(cfg, "light", "toggle", {"entity_id": payload.entity_id})
        return {"ok": True, "home_assistant": home_assistant_state(cfg)}
    except HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=f"Home Assistant returned HTTP {exc.code}.") from exc
    except (OSError, URLError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Home Assistant: {exc}") from exc


@app.post("/api/home-assistant/color")
def home_assistant_color(payload: HomeAssistantColorPayload, request: Request):
    require_auth(request)
    cfg = integration_config()
    ensure_home_assistant(cfg)
    if not payload.entity_id.startswith("light."):
        raise HTTPException(status_code=400, detail="Only light entities can receive colors from Homelab Hub.")
    try:
        home_assistant_service(cfg, "light", "turn_on", {"entity_id": payload.entity_id, "rgb_color": hex_to_rgb(payload.color), "brightness": 255, "transition": 0})
        return {"ok": True, "home_assistant": home_assistant_state(cfg)}
    except HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=f"Home Assistant returned HTTP {exc.code}.") from exc
    except (OSError, URLError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Home Assistant: {exc}") from exc


@app.post("/api/home-assistant/white")
def home_assistant_white(payload: HomeAssistantWhitePayload, request: Request):
    require_auth(request)
    cfg = integration_config()
    ensure_home_assistant(cfg)
    if not payload.entity_id.startswith("light."):
        raise HTTPException(status_code=400, detail="Only light entities can receive white channel commands from Homelab Hub.")
    try:
        restore_light_default(cfg, payload.entity_id, payload.mode)
        return {"ok": True, "home_assistant": home_assistant_state(cfg)}
    except HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail=f"Home Assistant returned HTTP {exc.code}.") from exc
    except (OSError, URLError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Home Assistant: {exc}") from exc


@app.post("/api/home-assistant/party")
def home_assistant_party(payload: HomeAssistantPartyPayload, request: Request):
    require_auth(request)
    cfg = integration_config()
    ensure_home_assistant(cfg)
    global PARTY_MODE_DELAY, PARTY_MODE_THREAD
    PARTY_MODE_DELAY = party_delay(payload.craziness)
    if payload.enabled:
        if PARTY_MODE_THREAD and PARTY_MODE_THREAD.is_alive():
            return {"ok": True, "enabled": True, "delay_seconds": PARTY_MODE_DELAY}
        PARTY_MODE_STOP.clear()
        PARTY_MODE_THREAD = threading.Thread(target=party_worker, args=(cfg,), daemon=True)
        PARTY_MODE_THREAD.start()
        return {"ok": True, "enabled": True, "delay_seconds": PARTY_MODE_DELAY}
    PARTY_MODE_STOP.set()
    lights = light_entities(cfg)
    for entity_id in lights:
        try:
            restore_light_default(cfg, entity_id, "auto")
        except Exception:
            pass
    time.sleep(0.35)
    for entity_id in lights:
        try:
            home_assistant_service(cfg, "light", "turn_off", {"entity_id": entity_id, "transition": 0})
        except Exception:
            pass
    return {"ok": True, "enabled": False, "delay_seconds": PARTY_MODE_DELAY}


@app.get("/api/integration-settings")
def integration_settings_get(request: Request):
    require_auth(request)
    return public_integration_settings()


@app.put("/api/integration-settings")
def integration_settings_put(payload: IntegrationSettingsPayload, request: Request):
    require_auth(request)
    return save_integration_settings(payload)


Action = Literal["start", "stop", "restart", "pause", "unpause"]


@app.get("/api/icons")
def icons(request: Request):
    require_auth(request)
    return {"icons": icon_slugs()}


@app.post("/api/icons/download")
def icon_download(payload: IconDownloadPayload, request: Request):
    require_auth(request)
    return download_dashboard_icon(payload.icon)


@app.put("/api/order")
def order_put(payload: OrderPayload, request: Request):
    require_auth(request)
    return save_order(payload)


@app.put("/api/webui-links")
def webui_links_put(payload: WebuiLinksPayload, request: Request):
    require_auth(request)
    return save_webui_links(payload)


@app.put("/api/containers/{container_id}/prefs")
def container_prefs(container_id: str, payload: ContainerPrefsPayload, request: Request):
    require_auth(request)
    client = docker_client()
    try:
        container = client.containers.get(container_id)
        return save_container_prefs(container.name, payload)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Container not found") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass


@app.post("/api/containers/{container_id}/{action}")
def container_action(container_id: str, action: Action, request: Request):
    require_auth(request)
    client = docker_client()
    try:
        container = client.containers.get(container_id)
        if action == "start":
            container.start()
        elif action == "stop":
            container.stop(timeout=15)
        elif action == "restart":
            container.restart(timeout=15)
        elif action == "pause":
            container.pause()
        elif action == "unpause":
            container.unpause()
        container.reload()
        return {"ok": True, "id": container.id, "name": container.name, "status": container.status}
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Container not found") from exc
    except APIError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        try:
            client.close()
        except Exception:
            pass


@app.get("/api/containers/{container_id}/logs")
def container_logs(container_id: str, request: Request, tail: int = 250):
    require_auth(request)
    tail = max(20, min(tail, 2000))
    client = docker_client()
    try:
        container = client.containers.get(container_id)
        logs = container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
        return JSONResponse({"name": container.name, "logs": logs})
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Container not found") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass


@app.get("/api/settings")
def settings_get(request: Request):
    require_auth(request)
    return get_settings()


@app.put("/api/settings")
def settings_put(payload: SettingsPayload, request: Request):
    require_auth(request)
    values = {
        "title": payload.title,
        "refresh_seconds": str(payload.refresh_seconds),
        "confirm_actions": json.dumps(payload.confirm_actions),
    }
    with db() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
    return get_settings()
