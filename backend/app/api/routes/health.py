from __future__ import annotations

from fastapi import APIRouter

from app.api.dto import ok

router = APIRouter()


@router.get("/health")
def health() -> dict[str, object]:
    return ok({"status": "ok"})
