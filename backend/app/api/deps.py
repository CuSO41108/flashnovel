from __future__ import annotations

import os

from app.runtime.service import FlashNovelService
from app.runtime.worker import WorkerManager


_service: FlashNovelService | None = None
_worker: WorkerManager | None = None


def get_service() -> FlashNovelService:
    global _service
    if _service is None:
        data_dir = os.environ.get("FLASHNOVEL_DATA_DIR", "data")
        _service = FlashNovelService(data_dir=data_dir)
    return _service


def start_worker() -> None:
    global _worker
    service = get_service()
    if _worker is None:
        _worker = WorkerManager(service.registry, service.execute_task)
    _worker.start()


def stop_worker() -> None:
    if _worker is not None:
        _worker.stop()
