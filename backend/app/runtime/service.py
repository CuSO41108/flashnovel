from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.api.dto import CreateRunRequest, CreateStoryRequest
from app.domain import Character, WorldRule
from app.runtime.host import RuntimeHost
from app.runtime.registry import RunRegistry, RunTask


class FlashNovelService:
    def __init__(self, data_dir: str = "data") -> None:
        from app.memory.store import FlashNovelStore

        root = Path(data_dir)
        self.store = FlashNovelStore(db_path=root / "flashnovel.sqlite3", artifact_root=root / "artifacts")
        self.store.initialize()
        self.registry = RunRegistry()
        self.host = RuntimeHost(self.store, self.registry)
        self.recover_pending_runs()

    def create_story(self, req: CreateStoryRequest) -> dict[str, object]:
        story_id = str(uuid4())
        metadata = {
            "genre": req.genre,
            "style": req.style or "default",
            "word_count": req.word_count.model_dump(),
        }
        self.store.create_story(
            title=req.title,
            description=req.premise,
            metadata=metadata,
            story_id=story_id,
        )
        workspace = self.store.create_workspace(story_id=story_id, workspace_id=story_id)
        self.store.save_world_rule(
            WorldRule(
                story_id=story_id,
                workspace_id=workspace.id,
                category="premise",
                rule=req.premise,
                metadata={"source": "story.create"},
            )
        )
        for item in req.characters:
            self.store.save_character(
                Character(
                    story_id=story_id,
                    workspace_id=workspace.id,
                    name=item.name,
                    role=item.role,
                    description=item.description,
                    metadata={"source": "story.create"},
                )
            )
        return self.store.get_story_dict(story_id)

    def list_stories(self) -> list[dict[str, object]]:
        return self.store.list_story_dicts()

    def get_story(self, story_id: str) -> dict[str, object]:
        return self.store.get_story_dict(story_id)

    def get_workspace(self, story_id: str) -> dict[str, object]:
        return self.store.get_workspace_snapshot(story_id)

    def get_memory(self, story_id: str) -> dict[str, object]:
        return self.store.get_memory_view(story_id)

    def get_artifacts(self, story_id: str) -> list[dict[str, object]]:
        return [asdict(item) for item in self.store.list_artifacts(story_id=story_id)]

    def create_run(self, req: CreateRunRequest) -> dict[str, object]:
        if self._story_has_busy_run(req.story_id):
            raise ValueError("story is busy")
        run_id = str(uuid4())
        workspace = self._workspace_for_story(req.story_id)
        max_chapters = max(1, int(req.max_chapters or 5))
        context_budget = self._resolve_context_budget(req.context_budget)
        self.store.create_run(
            story_id=req.story_id,
            workspace_id=workspace.id,
            status="queued",
            current_chapter=self.store.next_chapter(req.story_id),
            input_data={
                "prompt": req.prompt,
                "provider": req.provider,
                "base_url": req.base_url,
                "model": req.model,
                "max_chapters": max_chapters,
                "context_budget": context_budget,
            },
            run_id=run_id,
        )
        self.registry.enqueue(
            RunTask(
                run_id=run_id,
                op="start",
                payload={
                    "prompt": req.prompt,
                    "story_id": req.story_id,
                    "max_chapters": max_chapters,
                    "context_budget": context_budget,
                },
            )
        )
        return self.store.run_dict(run_id)

    def execute_task(self, task: RunTask) -> None:
        run = self.store.run_dict(task.run_id)
        story_id = str(run["story_id"])
        prompt = str(task.payload.get("prompt") or run.get("prompt") or "")
        max_chapters = int(task.payload.get("max_chapters") or run.get("max_chapters") or 5)
        context_budget = int(task.payload.get("context_budget") or run.get("context_budget") or 0)
        try:
            self.host.run(
                task.run_id,
                story_id,
                prompt,
                max_chapters=max_chapters,
                context_budget=context_budget,
            )
        except Exception as exc:
            self.store.update_run(task.run_id, status="failed")
            self.store.append_event(
                run_id=task.run_id,
                event_type="run.failed",
                payload={"message": "run failed", "error": str(exc)},
            )
            raise

    def list_runs(self) -> list[dict[str, object]]:
        return [self.store.run_dict(item.id) for item in self.store.list_runs()]

    def get_run(self, run_id: str) -> dict[str, object]:
        return self.store.run_dict(run_id)

    def pause_run(self, run_id: str) -> dict[str, object]:
        self.registry.request_abort(run_id)
        self.store.update_run_status(run_id, "paused")
        return self.store.get_run(run_id)

    def resume_run(self, run_id: str, prompt: str = "") -> dict[str, object]:
        run = self.store.run_dict(run_id)
        if self.registry.is_busy(run_id):
            raise ValueError("run is busy")
        payload = {
            "prompt": prompt or str(run.get("prompt", "")),
            "story_id": run["story_id"],
            "max_chapters": run.get("max_chapters", 5),
            "context_budget": run.get("context_budget", 0),
        }
        self.store.update_run_status(run_id, "queued")
        self.registry.enqueue(RunTask(run_id=run_id, op="resume", payload=payload))
        return self.store.get_run(run_id)

    def recover_pending_runs(self) -> list[str]:
        recovered: list[str] = []
        for run in self.store.list_runs():
            if run.status not in {"queued", "running"}:
                continue
            checkpoint = self.store.get_latest_checkpoint(run.id)
            pending_status = ""
            if checkpoint is not None:
                pending_status = str(
                    checkpoint.pending.get("status")
                    or checkpoint.state.get("status")
                    or ""
                )
            if pending_status in {"awaiting_confirmation", "paused"}:
                self.store.update_run_status(run.id, pending_status)
                self.store.append_event(
                    run_id=run.id,
                    event_type="run.recovered",
                    payload={
                        "message": f"run recovered as {pending_status}",
                        "status": pending_status,
                        "checkpoint": checkpoint.chapter if checkpoint else None,
                    },
                )
                recovered.append(run.id)
                continue

            self.store.update_run_status(run.id, "queued")
            payload = {
                "prompt": str(run.input.get("prompt", "") or ""),
                "story_id": run.story_id,
                "max_chapters": int(run.input.get("max_chapters") or 5),
                "context_budget": int(run.input.get("context_budget") or 0),
            }
            if not self.registry.is_busy(run.id):
                self.registry.enqueue(RunTask(run_id=run.id, op="resume", payload=payload))
            self.store.append_event(
                run_id=run.id,
                event_type="run.recovered",
                payload={"message": "run recovered and requeued", "status": "queued"},
            )
            recovered.append(run.id)
        return recovered

    def confirm_run(self, run_id: str) -> dict[str, object]:
        run = self.store.run_dict(run_id)
        status = str(run.get("status", ""))
        if status != "awaiting_confirmation":
            raise ValueError("run is not awaiting confirmation")
        return self.resume_run(run_id)

    def cancel_run(self, run_id: str) -> dict[str, object]:
        self.registry.request_abort(run_id)
        self.store.update_run_status(run_id, "canceled")
        return self.store.get_run(run_id)

    def get_run_events(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[dict[str, object]]:
        return self.store.list_event_dicts(run_id=run_id, after_seq=after_seq, limit=limit)

    def get_chapter(self, story_id: str, chapter: int) -> dict[str, object]:
        return self.store.get_chapter(story_id=story_id, chapter=chapter)

    def _workspace_for_story(self, story_id: str) -> Any:
        workspaces = self.store.list_workspaces(story_id)
        if workspaces:
            return workspaces[0]
        return self.store.create_workspace(story_id=story_id, workspace_id=story_id)

    def _story_has_busy_run(self, story_id: str) -> bool:
        for run in self.store.list_runs(story_id=story_id):
            if self.registry.is_busy(run.id):
                return True
            if run.status in {"queued", "running"}:
                return True
        return False

    @staticmethod
    def _resolve_context_budget(value: int | None = None) -> int:
        raw = value if value and value > 0 else os.environ.get("FLASHNOVEL_CONTEXT_BUDGET", "")
        try:
            return max(0, int(raw or 0))
        except (TypeError, ValueError):
            return 0
