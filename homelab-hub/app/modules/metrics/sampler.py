"""Independent Linux host counters for background history collection."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import time


class HistorySampler:
    def __init__(self, data_dir, docker_factory, collect_container, proc_root=Path("/proc")):
        self.data_dir = data_dir
        self.docker_factory = docker_factory
        self.collect_container = collect_container
        self.proc_root = proc_root
        self.previous_cpu = {}
        self.previous_network = None

    def cpu(self):
        current = {}
        for line in (self.proc_root / "stat").read_text().splitlines():
            parts = line.split()
            if not parts or not parts[0].startswith("cpu"):
                continue
            # guest/guest_nice are already included in user/nice; don't double count.
            ticks = [int(v) for v in parts[1:9]]
            current[parts[0]] = (sum(ticks), ticks[3] + ticks[4])
        result = {}
        for key, (total, idle) in current.items():
            previous = self.previous_cpu.get(key)
            result[key] = None
            if previous and total > previous[0]:
                result[key] = round(max(0, min(100, 100 * (1 - (idle - previous[1]) / (total - previous[0])))), 2)
        self.previous_cpu = current
        return result

    def network(self):
        rx = tx = 0
        for line in (self.proc_root / "net/dev").read_text().splitlines()[2:]:
            name, raw = line.split(":", 1)
            if name.strip() == "lo":
                continue
            parts = raw.split()
            rx += int(parts[0])
            tx += int(parts[8])
        now = time.monotonic()
        previous = self.previous_network
        self.previous_network = (now, rx, tx)
        if previous and now > previous[0] and rx >= previous[1] and tx >= previous[2]:
            return (rx - previous[1]) / (now - previous[0]), (tx - previous[2]) / (now - previous[0])
        return None, None

    def sample(self, include_containers):
        result = {}
        try:
            cores = self.cpu()
            result.update(cpu_percent=cores.pop("cpu", None), cores=cores)
        except (OSError, ValueError, IndexError):
            result.update(cpu_percent=None, cores={})
        try:
            memory = {}
            for line in (self.proc_root / "meminfo").read_text().splitlines():
                key, raw = line.split(":", 1)
                memory[key] = int(raw.split()[0]) * 1024
            total, available = memory["MemTotal"], memory["MemAvailable"]
            result.update(memory_percent=100 * (total - available) / total,
                          memory_used=total - available, memory_available=available, memory_total=total)
        except (OSError, ValueError, KeyError, ZeroDivisionError):
            result.update(memory_percent=None, memory_used=None, memory_available=None, memory_total=None)
        try:
            disk = shutil.disk_usage(self.data_dir)
            result.update(storage_percent=100 * disk.used / disk.total, storage_used=disk.used,
                          storage_free=disk.free, storage_total=disk.total)
        except (OSError, ZeroDivisionError):
            result.update(storage_percent=None, storage_used=None, storage_free=None, storage_total=None)
        try:
            result["rx_rate"], result["tx_rate"] = self.network()
        except (OSError, ValueError, IndexError):
            result.update(rx_rate=None, tx_rate=None)
        result.update(containers=[], container_cpu=None, container_memory=None, containers_available=False)
        if include_containers:
            client = None
            try:
                client = self.docker_factory()
                containers = client.containers.list(all=True)
                with ThreadPoolExecutor(max_workers=8) as pool:
                    rows = list(pool.map(self.collect_container, containers))
                for row in rows:
                    if not row.get("stats_available", True):
                        row["cpu_percent"] = row["memory_used"] = None
                result["containers"] = [{key: row.get(key) for key in ("id", "name", "status", "cpu_percent", "memory_used", "memory_limit")} for row in rows]
                complete = all(row.get("stats_available", True) for row in rows)
                result.update(container_cpu=sum(row.get("cpu_percent", 0) for row in rows) if complete else None,
                              container_memory=sum(row.get("memory_used", 0) for row in rows) if complete else None, containers_available=complete)
            except Exception:
                # Host samples remain useful during Docker outages.
                pass
            finally:
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
        return result
