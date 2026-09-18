"""Small single-flight cache: requests never wait for external collectors."""
from copy import deepcopy
from datetime import datetime, timezone
import threading
import time


class Snapshot:
    def __init__(self, loader, ttl=10, error_message="Data source unavailable"):
        self.loader = loader
        self.ttl = ttl
        self.error_message = error_message
        self.lock = threading.Lock()
        self.data = None
        self.updated_at = None
        self.attempted = None
        self.error = None
        self.loading = False
        self.generation = 0

    def invalidate(self):
        with self.lock:
            self.attempted = None
            self.generation += 1

    def read(self):
        with self.lock:
            if not self.loading and (self.attempted is None or time.monotonic() - self.attempted >= self.ttl):
                self.loading = True
                self.attempted = time.monotonic()
                threading.Thread(target=self._refresh, args=(self.generation,), daemon=True).start()
            return {"data": deepcopy(self.data), "updated_at": self.updated_at,
                    "loading": self.loading, "error": self.error}

    def _refresh(self, generation):
        try:
            data = self.loader()
            with self.lock:
                if generation == self.generation:
                    self.data = data
                    self.updated_at = datetime.now(timezone.utc).isoformat()
                    self.error = None
        except Exception:
            with self.lock:
                if generation == self.generation:
                    self.error = self.error_message
        finally:
            with self.lock:
                self.loading = False
