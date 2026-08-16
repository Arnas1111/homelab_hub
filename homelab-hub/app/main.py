import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

import docker
from docker.errors import APIError, DockerException, NotFound
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
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
    refresh_seconds: int = Field(ge=2, le=60)
    confirm_actions: bool


class ContainerPrefsPayload(BaseModel):
    icon: str = Field(default="", max_length=90, pattern=r"^[a-z0-9-]*$")
    group_name: str = Field(default="", max_length=80)


class IconDownloadPayload(BaseModel):
    icon: str = Field(max_length=90, pattern=r"^[a-z0-9-]+$")


class OrderPayload(BaseModel):
    groups: list[str] = Field(default_factory=list)
    containers: dict[str, list[str]] = Field(default_factory=dict)


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
    for internal, bindings in ports.items():
        if not bindings:
            continue
        for binding in bindings:
            host_ip = binding.get("HostIp", "")
            host_port = binding.get("HostPort", "")
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


def host_metrics(info: dict) -> dict:
    cpus = int(info.get("NCPU") or os.cpu_count() or 1)
    load_one, load_five, load_fifteen = os.getloadavg()
    return {
        "load": {
            "one": round(load_one, 2),
            "five": round(load_five, 2),
            "fifteen": round(load_fifteen, 2),
            "one_percent": pct(load_one, cpus),
            "five_percent": pct(load_five, cpus),
            "fifteen_percent": pct(load_fifteen, cpus),
        },
        "cpu": cpu_usage(),
        "memory": read_meminfo(),
        "data_mount": disk_usage(DATA_DIR),
    }


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
