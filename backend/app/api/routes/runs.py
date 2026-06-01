from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_service
from app.api.dto import ConfirmRunRequest, CreateRunRequest, ResumeRunRequest, ok
from app.runtime.service import FlashNovelService

router = APIRouter(prefix="/runs")


@router.post("")
def create_run(req: CreateRunRequest, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok(service.create_run(req))


@router.get("")
def list_runs(service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok({"items": service.list_runs()})


@router.get("/{run_id}")
def get_run(run_id: str, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok(service.get_run(run_id))


@router.post("/{run_id}/pause")
def pause_run(run_id: str, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok(service.pause_run(run_id))


@router.post("/{run_id}/resume")
def resume_run(run_id: str, req: ResumeRunRequest, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok(service.resume_run(run_id, prompt=req.prompt))


@router.post("/{run_id}/confirm")
def confirm_run(run_id: str, req: ConfirmRunRequest, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    _ = req
    return ok(service.confirm_run(run_id))


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok(service.cancel_run(run_id))


@router.get("/{run_id}/events")
def get_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    service: FlashNovelService = Depends(get_service),
) -> dict[str, object]:
    return ok({"items": service.get_run_events(run_id, after_seq=after_seq, limit=limit)})


@router.get("/{run_id}/events/stream")
def stream_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    service: FlashNovelService = Depends(get_service),
) -> StreamingResponse:
    async def _events():
        current = after_seq
        while True:
            items = service.get_run_events(run_id, after_seq=current, limit=200)
            for item in items:
                current = max(current, int(item.get("seq", current) or current))
                event_type = str(item.get("type", "runtime.event") or "runtime.event")
                yield f"event: {event_type}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
            run = service.get_run(run_id)
            if str(run.get("status", "")) in {"completed", "failed", "canceled", "paused", "awaiting_confirmation"} and not items:
                break
            await asyncio.sleep(0.35)

    return StreamingResponse(_events(), media_type="text/event-stream")
