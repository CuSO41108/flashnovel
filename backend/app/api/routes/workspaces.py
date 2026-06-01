from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_service
from app.api.dto import ok
from app.runtime.service import FlashNovelService

router = APIRouter(prefix="/workspaces")


@router.get("/{story_id}")
def get_workspace(story_id: str, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok(service.get_workspace(story_id))


@router.get("/{story_id}/memory")
def get_workspace_memory(story_id: str, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok(service.get_memory(story_id))


@router.get("/{story_id}/artifacts")
def get_workspace_artifacts(story_id: str, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok({"items": service.get_artifacts(story_id)})
