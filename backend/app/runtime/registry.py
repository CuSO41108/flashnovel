from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any
from uuid import uuid4


@dataclass
class RunTask:
    run_id: str
    op: str
    payload: dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "queued"
    error: str = ""


class RunRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._tasks: list[RunTask] = []
        self._busy: set[str] = set()
        self._abort_flags: set[str] = set()

    def enqueue(self, task: RunTask) -> RunTask:
        with self._lock:
            self._tasks.append(task)
            return task

    def claim_next(self) -> RunTask | None:
        with self._lock:
            for task in self._tasks:
                if task.status != "queued" or task.run_id in self._busy:
                    continue
                task.status = "running"
                self._busy.add(task.run_id)
                return task
            return None

    def finish(self, task: RunTask, error: str = "") -> None:
        with self._lock:
            task.error = error
            task.status = "failed" if error else "completed"
            self._busy.discard(task.run_id)

    def is_busy(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._busy or any(t.run_id == run_id and t.status == "queued" for t in self._tasks)

    def request_abort(self, run_id: str) -> None:
        with self._lock:
            self._abort_flags.add(run_id)

    def clear_abort(self, run_id: str) -> None:
        with self._lock:
            self._abort_flags.discard(run_id)

    def should_abort(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._abort_flags
