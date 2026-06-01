from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_service
from app.api.dto import CreateStoryRequest, ok
from app.runtime.service import FlashNovelService

router = APIRouter(prefix="/stories")


@router.post("")
def create_story(req: CreateStoryRequest, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok(service.create_story(req))


@router.get("")
def list_stories(service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok({"items": service.list_stories()})


@router.get("/{story_id}")
def get_story(story_id: str, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok(service.get_story(story_id))


@router.get("/{story_id}/chapters/{chapter}")
def get_chapter(story_id: str, chapter: int, service: FlashNovelService = Depends(get_service)) -> dict[str, object]:
    return ok(service.get_chapter(story_id, chapter))
