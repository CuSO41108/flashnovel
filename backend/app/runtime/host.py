from __future__ import annotations

from typing import Any

from app.graph.workflow import NovelWorkflow

class RuntimeHost:
    def __init__(self, store, registry) -> None:
        self.store = store
        self.registry = registry
        self.tools = self._build_tools()
        self.workflow = NovelWorkflow(self)

    def _build_tools(self) -> dict[str, Any]:
        from app.llm.client import OpenAICompatibleClient
        from app.tools import build_tool_registry

        client = OpenAICompatibleClient.from_env()
        return build_tool_registry(self.store, client, emit_delta=self.emit_delta)

    def run(
        self,
        run_id: str,
        story_id: str,
        prompt: str,
        max_chapters: int = 5,
        context_budget: int = 0,
    ) -> dict[str, Any]:
        self.registry.clear_abort(run_id)
        self.store.update_run_status(run_id, "running")
        self.emit(
            run_id,
            "run.started",
            "run started",
            {"story_id": story_id, "max_chapters": max_chapters, "context_budget": context_budget},
        )
        state = self.workflow.invoke(
            {
                "run_id": run_id,
                "story_id": story_id,
                "seed_prompt": prompt,
                "chapter": self.next_chapter(story_id),
                "chapters_done_in_batch": 0,
                "max_chapters": max(1, int(max_chapters or 5)),
                "context_budget": max(0, int(context_budget or 0)),
                "rewrite_count": 0,
            }
        )
        status = str(state.get("status", "completed") or "completed")
        self.store.update_run_status(run_id, status)
        if status == "awaiting_confirmation":
            self.emit(run_id, "run.paused", "run awaiting confirmation", {"status": status})
        elif status == "paused":
            self.emit(run_id, "run.paused", "run paused", {"status": status})
        else:
            self.emit(run_id, "run.completed", "run completed", {"status": status})
        return state

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError(f"tool not found: {name}")
        self.emit(str(args.get("run_id", "")) or self._run_id_from_story(str(args.get("story_id", ""))), "tool.called", name, {"tool": name})
        return tool.execute(args)

    def next_chapter(self, story_id: str) -> int:
        return int(self.store.next_chapter(story_id))

    def create_checkpoint(self, run_id: str, story_id: str, chapter: int, status: str) -> None:
        _ = story_id
        self.store.save_checkpoint(
            run_id=run_id,
            chapter=chapter,
            state={"status": status, "completed_chapter": chapter, "next_chapter": chapter + 1},
            pending={"status": status, "next_action": "confirm" if status == "awaiting_confirmation" else "resume"},
        )
        self.emit(run_id, "checkpoint.created", f"checkpoint: {status}", {"chapter": chapter, "status": status})

    def emit(self, run_id: str, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        if not run_id:
            return
        self.store.append_event(run_id=run_id, event_type=event_type, payload={"message": message, **(payload or {})})

    def emit_delta(self, run_id: str, delta: str, channel: str = "content") -> None:
        if delta:
            self.emit(run_id, "llm.delta", delta, {"channel": channel, "delta": delta})

    def should_abort(self, run_id: str) -> bool:
        return self.registry.should_abort(run_id)

    def _run_id_from_story(self, story_id: str) -> str:
        run = self.store.latest_run_for_story(story_id)
        return str(run.get("run_id", "") if isinstance(run, dict) else "")
