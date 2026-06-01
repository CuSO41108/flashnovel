from __future__ import annotations

import threading
import time
from typing import Callable

from app.runtime.registry import RunRegistry, RunTask


class WorkerManager:
    def __init__(self, registry: RunRegistry, execute: Callable[[RunTask], None]) -> None:
        self.registry = registry
        self.execute = execute
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="flashnovel-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            task = self.registry.claim_next()
            if task is None:
                time.sleep(0.15)
                continue
            error = ""
            try:
                self.execute(task)
            except Exception as exc:
                error = str(exc)
            finally:
                self.registry.finish(task, error=error)
