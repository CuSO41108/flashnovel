"""SQLite persistence and file-backed artifact storage."""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from app.memory.schema import SCHEMA_SQL

from app.domain import (
    Artifact,
    ChapterContext,
    ChapterPlan,
    ChapterSummary,
    Character,
    Checkpoint,
    Event,
    Foreshadow,
    Location,
    Relationship,
    ReviewIssue,
    ReviewReport,
    Run,
    StateChange,
    Story,
    TimelineEvent,
    Workspace,
    WorldRule,
)


def _to_json(value: Any) -> str:
    if value is None:
        value = {}
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_json(value: str | None, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    return json.loads(value)


def _safe_segment(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)
    return cleaned or "item"


def _safe_extension(value: str | None, content_type: str) -> str:
    if value:
        raw = value[1:] if value.startswith(".") else value
    elif content_type == "application/json":
        raw = "json"
    elif content_type.startswith("text/"):
        raw = "txt"
    else:
        raw = "bin"
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)
    return "." + (cleaned or "bin")


@dataclass
class FlashNovelStore:
    """Store API for SQLite state plus file-backed artifacts."""

    db_path: str | Path
    artifact_root: str | Path | None = None

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        if self.artifact_root is None:
            self.artifact_root = self.db_path.parent / "artifacts"
        else:
            self.artifact_root = Path(self.artifact_root)

    def initialize(self) -> None:
        """Create database tables and the artifact root if they do not exist."""
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        Path(self.artifact_root).mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def create_story(
        self,
        title: str,
        description: str = "",
        metadata: Mapping[str, Any] | None = None,
        story_id: str | None = None,
    ) -> Story:
        conn = self._connect()
        try:
            item_id = story_id or self._new_id(conn, "story_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO stories(id, title, description, metadata_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item_id, title, description, _to_json(dict(metadata or {}))),
                )
            story = self.get_story(item_id)
            if story is None:
                raise ValueError("story was not created")
            return story
        finally:
            conn.close()

    def get_story(self, story_id: str) -> Story | None:
        row = self._fetch_one("SELECT * FROM stories WHERE id = ?", (story_id,))
        return self._story_from_row(row) if row is not None else None

    def list_stories(self) -> list[Story]:
        rows = self._fetch_all("SELECT * FROM stories ORDER BY created_at DESC, id DESC", ())
        return [self._story_from_row(row) for row in rows]

    def create_workspace(
        self,
        story_id: str,
        name: str = "default",
        status: str = "active",
        metadata: Mapping[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> Workspace:
        conn = self._connect()
        try:
            item_id = workspace_id or self._new_id(conn, "workspace_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO workspaces(id, story_id, name, status, metadata_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (item_id, story_id, name, status, _to_json(dict(metadata or {}))),
                )
            workspace = self.get_workspace(item_id)
            if workspace is None:
                raise ValueError("workspace was not created")
            return workspace
        finally:
            conn.close()

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        row = self._fetch_one("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        return self._workspace_from_row(row) if row is not None else None

    def list_workspaces(self, story_id: str) -> list[Workspace]:
        rows = self._fetch_all(
            "SELECT * FROM workspaces WHERE story_id = ? ORDER BY created_at DESC, id DESC",
            (story_id,),
        )
        return [self._workspace_from_row(row) for row in rows]

    def create_run(
        self,
        story_id: str,
        workspace_id: str,
        status: str = "queued",
        current_chapter: int = 1,
        node: str = "",
        input_data: Mapping[str, Any] | None = None,
        run_id: str | None = None,
    ) -> Run:
        conn = self._connect()
        try:
            item_id = run_id or self._new_id(conn, "run_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO runs(id, story_id, workspace_id, status, current_chapter, node, input_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        story_id,
                        workspace_id,
                        status,
                        current_chapter,
                        node,
                        _to_json(dict(input_data or {})),
                    ),
                )
            run = self.get_run(item_id)
            if run is None:
                raise ValueError("run was not created")
            return run
        finally:
            conn.close()

    def get_run(self, run_id: str) -> Run | None:
        row = self._fetch_one("SELECT * FROM runs WHERE id = ?", (run_id,))
        return self._run_from_row(row) if row is not None else None

    def list_runs(
        self,
        story_id: str | None = None,
        workspace_id: str | None = None,
        status: str | None = None,
    ) -> list[Run]:
        sql = "SELECT * FROM runs WHERE 1 = 1"
        params: list[Any] = []
        if story_id is not None:
            sql += " AND story_id = ?"
            params.append(story_id)
        if workspace_id is not None:
            sql += " AND workspace_id = ?"
            params.append(workspace_id)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC, id DESC"
        rows = self._fetch_all(sql, params)
        return [self._run_from_row(row) for row in rows]

    def update_run(
        self,
        run_id: str,
        status: str | None = None,
        current_chapter: int | None = None,
        node: str | None = None,
    ) -> Run:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"run not found: {run_id}")
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE runs
                    SET status = ?,
                        current_chapter = ?,
                        node = ?,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (
                        status if status is not None else run.status,
                        current_chapter if current_chapter is not None else run.current_chapter,
                        node if node is not None else run.node,
                        run_id,
                    ),
                )
        finally:
            conn.close()
        updated = self.get_run(run_id)
        if updated is None:
            raise ValueError(f"run not found: {run_id}")
        return updated

    def append_event(
        self,
        run_id: str,
        event_type: str,
        node: str = "",
        chapter: int | None = None,
        payload: Mapping[str, Any] | None = None,
        event_id: str | None = None,
    ) -> Event:
        conn = self._connect()
        try:
            run_row = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run_row is None:
                raise ValueError(f"run not found: {run_id}")
            item_id = event_id or self._new_id(conn, "event_")
            with conn:
                seq = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO events(id, run_id, seq, type, node, chapter, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        run_id,
                        seq,
                        event_type,
                        node,
                        chapter,
                        _to_json(dict(payload or {})),
                    ),
                )
            event = self._fetch_one("SELECT * FROM events WHERE id = ?", (item_id,))
            if event is None:
                raise ValueError("event was not created")
            return self._event_from_row(event)
        finally:
            conn.close()

    def list_events(
        self,
        run_id: str,
        after_seq: int | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        sql = "SELECT * FROM events WHERE run_id = ?"
        params: list[Any] = [run_id]
        if after_seq is not None:
            sql += " AND seq > ?"
            params.append(after_seq)
        sql += " ORDER BY seq ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._fetch_all(sql, params)
        return [self._event_from_row(row) for row in rows]

    def save_checkpoint(
        self,
        run_id: str,
        chapter: int,
        state: Mapping[str, Any],
        pending: Mapping[str, Any] | None = None,
        checkpoint_id: str | None = None,
    ) -> Checkpoint:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"run not found: {run_id}")
        conn = self._connect()
        try:
            item_id = checkpoint_id or self._new_id(conn, "checkpoint_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO checkpoints(id, run_id, story_id, workspace_id, chapter, state_json, pending_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        run_id,
                        run.story_id,
                        run.workspace_id,
                        chapter,
                        _to_json(dict(state)),
                        _to_json(dict(pending or {})),
                    ),
                )
            checkpoint = self._fetch_one("SELECT * FROM checkpoints WHERE id = ?", (item_id,))
            if checkpoint is None:
                raise ValueError("checkpoint was not created")
            return self._checkpoint_from_row(checkpoint)
        finally:
            conn.close()

    def get_latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        row = self._fetch_one(
            """
            SELECT * FROM checkpoints
            WHERE run_id = ?
            ORDER BY chapter DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (run_id,),
        )
        return self._checkpoint_from_row(row) if row is not None else None

    def list_checkpoints(self, run_id: str) -> list[Checkpoint]:
        rows = self._fetch_all(
            """
            SELECT * FROM checkpoints
            WHERE run_id = ?
            ORDER BY chapter ASC, created_at ASC, id ASC
            """,
            (run_id,),
        )
        return [self._checkpoint_from_row(row) for row in rows]

    def save_artifact(
        self,
        story_id: str,
        kind: str,
        content: str | bytes | Mapping[str, Any] | Sequence[Any],
        workspace_id: str | None = None,
        run_id: str | None = None,
        chapter: int | None = None,
        content_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        artifact_id: str | None = None,
        extension: str | None = None,
    ) -> Artifact:
        run = self.get_run(run_id) if run_id is not None else None
        if run is not None and workspace_id is None:
            workspace_id = run.workspace_id
        if content_type is None:
            content_type = "application/json" if isinstance(content, (dict, list, tuple)) else "text/plain"
        conn = self._connect()
        try:
            item_id = artifact_id or self._new_id(conn, "artifact_")
            suffix = _safe_extension(extension, content_type)
            relative_path = Path("stories") / _safe_segment(story_id) / f"{_safe_segment(item_id)}{suffix}"
            full_path = Path(self.artifact_root) / relative_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                full_path.write_bytes(content)
                size = len(content)
            elif isinstance(content, str):
                full_path.write_text(content, encoding="utf-8")
                size = len(content.encode("utf-8"))
            else:
                text = json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True)
                full_path.write_text(text, encoding="utf-8")
                size = len(text.encode("utf-8"))
            with conn:
                conn.execute(
                    """
                    INSERT INTO artifacts(
                        id, story_id, workspace_id, run_id, kind, chapter, path,
                        content_type, size, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        story_id,
                        workspace_id,
                        run_id,
                        kind,
                        chapter,
                        relative_path.as_posix(),
                        content_type,
                        size,
                        _to_json(dict(metadata or {})),
                    ),
                )
            artifact = self.get_artifact(item_id)
            if artifact is None:
                raise ValueError("artifact was not created")
            return artifact
        finally:
            conn.close()

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        row = self._fetch_one("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
        return self._artifact_from_row(row) if row is not None else None

    def list_artifacts(
        self,
        story_id: str,
        workspace_id: str | None = None,
        run_id: str | None = None,
        kind: str | None = None,
        chapter: int | None = None,
        limit: int | None = None,
    ) -> list[Artifact]:
        sql = "SELECT * FROM artifacts WHERE story_id = ?"
        params: list[Any] = [story_id]
        if workspace_id is not None:
            sql += " AND workspace_id = ?"
            params.append(workspace_id)
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        if chapter is not None:
            sql += " AND chapter = ?"
            params.append(chapter)
        sql += " ORDER BY created_at DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._fetch_all(sql, params)
        return [self._artifact_from_row(row) for row in rows]

    def read_artifact_text(self, artifact_id: str) -> str:
        artifact = self.get_artifact(artifact_id)
        if artifact is None:
            raise ValueError(f"artifact not found: {artifact_id}")
        return (Path(self.artifact_root) / artifact.path).read_text(encoding="utf-8")

    def read_artifact_json(self, artifact_id: str) -> Any:
        return json.loads(self.read_artifact_text(artifact_id))

    def save_character(self, item: Character) -> Character:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "character_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO characters(
                        id, story_id, workspace_id, name, role, description, status,
                        traits_json, first_chapter, last_chapter, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(story_id, workspace_id, name) DO UPDATE SET
                        role = excluded.role,
                        description = excluded.description,
                        status = excluded.status,
                        traits_json = excluded.traits_json,
                        first_chapter = excluded.first_chapter,
                        last_chapter = excluded.last_chapter,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.name,
                        item.role,
                        item.description,
                        item.status,
                        _to_json(item.traits),
                        item.first_chapter,
                        item.last_chapter,
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_character(item.story_id, item.workspace_id, item.name)
        if saved is None:
            raise ValueError("character was not saved")
        return saved

    def get_character(self, story_id: str, workspace_id: str, name: str) -> Character | None:
        row = self._fetch_one(
            "SELECT * FROM characters WHERE story_id = ? AND workspace_id = ? AND name = ?",
            (story_id, workspace_id, name),
        )
        return self._character_from_row(row) if row is not None else None

    def list_characters(
        self,
        story_id: str,
        workspace_id: str,
        status: str | None = None,
    ) -> list[Character]:
        sql = "SELECT * FROM characters WHERE story_id = ? AND workspace_id = ?"
        params: list[Any] = [story_id, workspace_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY name ASC"
        rows = self._fetch_all(sql, params)
        return [self._character_from_row(row) for row in rows]

    def save_world_rule(self, item: WorldRule) -> WorldRule:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "world_rule_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO world_rules(
                        id, story_id, workspace_id, category, rule, source_chapter,
                        status, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(story_id, workspace_id, category, rule) DO UPDATE SET
                        source_chapter = excluded.source_chapter,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.category,
                        item.rule,
                        item.source_chapter,
                        item.status,
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_world_rule(item.story_id, item.workspace_id, item.category, item.rule)
        if saved is None:
            raise ValueError("world rule was not saved")
        return saved

    def get_world_rule(
        self,
        story_id: str,
        workspace_id: str,
        category: str,
        rule: str,
    ) -> WorldRule | None:
        row = self._fetch_one(
            """
            SELECT * FROM world_rules
            WHERE story_id = ? AND workspace_id = ? AND category = ? AND rule = ?
            """,
            (story_id, workspace_id, category, rule),
        )
        return self._world_rule_from_row(row) if row is not None else None

    def list_world_rules(
        self,
        story_id: str,
        workspace_id: str,
        status: str | None = None,
    ) -> list[WorldRule]:
        sql = "SELECT * FROM world_rules WHERE story_id = ? AND workspace_id = ?"
        params: list[Any] = [story_id, workspace_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY category ASC, source_chapter ASC, id ASC"
        rows = self._fetch_all(sql, params)
        return [self._world_rule_from_row(row) for row in rows]

    def save_location(self, item: Location) -> Location:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "location_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO locations(
                        id, story_id, workspace_id, name, description, status,
                        first_chapter, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(story_id, workspace_id, name) DO UPDATE SET
                        description = excluded.description,
                        status = excluded.status,
                        first_chapter = excluded.first_chapter,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.name,
                        item.description,
                        item.status,
                        item.first_chapter,
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_location(item.story_id, item.workspace_id, item.name)
        if saved is None:
            raise ValueError("location was not saved")
        return saved

    def get_location(self, story_id: str, workspace_id: str, name: str) -> Location | None:
        row = self._fetch_one(
            "SELECT * FROM locations WHERE story_id = ? AND workspace_id = ? AND name = ?",
            (story_id, workspace_id, name),
        )
        return self._location_from_row(row) if row is not None else None

    def list_locations(
        self,
        story_id: str,
        workspace_id: str,
        status: str | None = None,
    ) -> list[Location]:
        sql = "SELECT * FROM locations WHERE story_id = ? AND workspace_id = ?"
        params: list[Any] = [story_id, workspace_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY name ASC"
        rows = self._fetch_all(sql, params)
        return [self._location_from_row(row) for row in rows]

    def save_chapter_plan(self, item: ChapterPlan) -> ChapterPlan:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "chapter_plan_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO chapter_plans(
                        id, story_id, workspace_id, chapter, title, summary, beats_json,
                        status, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(story_id, workspace_id, chapter) DO UPDATE SET
                        title = excluded.title,
                        summary = excluded.summary,
                        beats_json = excluded.beats_json,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.chapter,
                        item.title,
                        item.summary,
                        _to_json(item.beats),
                        item.status,
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_chapter_plan(item.story_id, item.workspace_id, item.chapter)
        if saved is None:
            raise ValueError("chapter plan was not saved")
        return saved

    def get_chapter_plan(
        self,
        story_id: str,
        workspace_id: str,
        chapter: int,
    ) -> ChapterPlan | None:
        row = self._fetch_one(
            """
            SELECT * FROM chapter_plans
            WHERE story_id = ? AND workspace_id = ? AND chapter = ?
            """,
            (story_id, workspace_id, chapter),
        )
        return self._chapter_plan_from_row(row) if row is not None else None

    def list_chapter_plans(self, story_id: str, workspace_id: str) -> list[ChapterPlan]:
        rows = self._fetch_all(
            """
            SELECT * FROM chapter_plans
            WHERE story_id = ? AND workspace_id = ?
            ORDER BY chapter ASC
            """,
            (story_id, workspace_id),
        )
        return [self._chapter_plan_from_row(row) for row in rows]

    def save_chapter_summary(self, item: ChapterSummary) -> ChapterSummary:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "chapter_summary_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO chapter_summaries(
                        id, story_id, workspace_id, chapter, title, summary,
                        key_events_json, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(story_id, workspace_id, chapter) DO UPDATE SET
                        title = excluded.title,
                        summary = excluded.summary,
                        key_events_json = excluded.key_events_json,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.chapter,
                        item.title,
                        item.summary,
                        _to_json(item.key_events),
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_chapter_summary(item.story_id, item.workspace_id, item.chapter)
        if saved is None:
            raise ValueError("chapter summary was not saved")
        return saved

    def get_chapter_summary(
        self,
        story_id: str,
        workspace_id: str,
        chapter: int,
    ) -> ChapterSummary | None:
        row = self._fetch_one(
            """
            SELECT * FROM chapter_summaries
            WHERE story_id = ? AND workspace_id = ? AND chapter = ?
            """,
            (story_id, workspace_id, chapter),
        )
        return self._chapter_summary_from_row(row) if row is not None else None

    def list_chapter_summaries(
        self,
        story_id: str,
        workspace_id: str,
        before_chapter: int | None = None,
        through_chapter: int | None = None,
        limit: int | None = None,
    ) -> list[ChapterSummary]:
        sql = "SELECT * FROM chapter_summaries WHERE story_id = ? AND workspace_id = ?"
        params: list[Any] = [story_id, workspace_id]
        if before_chapter is not None:
            sql += " AND chapter < ?"
            params.append(before_chapter)
        if through_chapter is not None:
            sql += " AND chapter <= ?"
            params.append(through_chapter)
        sql += " ORDER BY chapter DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._fetch_all(sql, params)
        return [self._chapter_summary_from_row(row) for row in rows]

    def save_timeline_event(self, item: TimelineEvent) -> TimelineEvent:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "timeline_event_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO timeline_events(
                        id, story_id, workspace_id, chapter, sequence, event,
                        participants_json, location, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        chapter = excluded.chapter,
                        sequence = excluded.sequence,
                        event = excluded.event,
                        participants_json = excluded.participants_json,
                        location = excluded.location,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.chapter,
                        item.sequence,
                        item.event,
                        _to_json(item.participants),
                        item.location,
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_timeline_event(item_id)
        if saved is None:
            raise ValueError("timeline event was not saved")
        return saved

    def get_timeline_event(self, event_id: str) -> TimelineEvent | None:
        row = self._fetch_one("SELECT * FROM timeline_events WHERE id = ?", (event_id,))
        return self._timeline_event_from_row(row) if row is not None else None

    def list_timeline_events(
        self,
        story_id: str,
        workspace_id: str,
        from_chapter: int | None = None,
        through_chapter: int | None = None,
        limit: int | None = None,
    ) -> list[TimelineEvent]:
        sql = "SELECT * FROM timeline_events WHERE story_id = ? AND workspace_id = ?"
        params: list[Any] = [story_id, workspace_id]
        if from_chapter is not None:
            sql += " AND chapter >= ?"
            params.append(from_chapter)
        if through_chapter is not None:
            sql += " AND chapter <= ?"
            params.append(through_chapter)
        sql += " ORDER BY chapter ASC, sequence ASC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._fetch_all(sql, params)
        return [self._timeline_event_from_row(row) for row in rows]

    def save_relationship(self, item: Relationship) -> Relationship:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "relationship_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO relationships(
                        id, story_id, workspace_id, source, target, relationship,
                        status, since_chapter, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(story_id, workspace_id, source, target, relationship) DO UPDATE SET
                        status = excluded.status,
                        since_chapter = excluded.since_chapter,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.source,
                        item.target,
                        item.relationship,
                        item.status,
                        item.since_chapter,
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_relationship(
            item.story_id,
            item.workspace_id,
            item.source,
            item.target,
            item.relationship,
        )
        if saved is None:
            raise ValueError("relationship was not saved")
        return saved

    def get_relationship(
        self,
        story_id: str,
        workspace_id: str,
        source: str,
        target: str,
        relationship: str,
    ) -> Relationship | None:
        row = self._fetch_one(
            """
            SELECT * FROM relationships
            WHERE story_id = ? AND workspace_id = ? AND source = ? AND target = ? AND relationship = ?
            """,
            (story_id, workspace_id, source, target, relationship),
        )
        return self._relationship_from_row(row) if row is not None else None

    def list_relationships(
        self,
        story_id: str,
        workspace_id: str,
        status: str | None = None,
    ) -> list[Relationship]:
        sql = "SELECT * FROM relationships WHERE story_id = ? AND workspace_id = ?"
        params: list[Any] = [story_id, workspace_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY source ASC, target ASC, relationship ASC"
        rows = self._fetch_all(sql, params)
        return [self._relationship_from_row(row) for row in rows]

    def save_foreshadow(self, item: Foreshadow) -> Foreshadow:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "foreshadow_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO foreshadows(
                        id, story_id, workspace_id, key, setup_chapter, payoff_chapter,
                        description, status, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(story_id, workspace_id, key) DO UPDATE SET
                        setup_chapter = excluded.setup_chapter,
                        payoff_chapter = excluded.payoff_chapter,
                        description = excluded.description,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.key,
                        item.setup_chapter,
                        item.payoff_chapter,
                        item.description,
                        item.status,
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_foreshadow(item.story_id, item.workspace_id, item.key)
        if saved is None:
            raise ValueError("foreshadow was not saved")
        return saved

    def get_foreshadow(self, story_id: str, workspace_id: str, key: str) -> Foreshadow | None:
        row = self._fetch_one(
            "SELECT * FROM foreshadows WHERE story_id = ? AND workspace_id = ? AND key = ?",
            (story_id, workspace_id, key),
        )
        return self._foreshadow_from_row(row) if row is not None else None

    def list_foreshadows(
        self,
        story_id: str,
        workspace_id: str,
        status: str | None = None,
    ) -> list[Foreshadow]:
        sql = "SELECT * FROM foreshadows WHERE story_id = ? AND workspace_id = ?"
        params: list[Any] = [story_id, workspace_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY setup_chapter ASC, key ASC"
        rows = self._fetch_all(sql, params)
        return [self._foreshadow_from_row(row) for row in rows]

    def save_state_change(self, item: StateChange) -> StateChange:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "state_change_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO state_changes(
                        id, story_id, workspace_id, chapter, entity, attribute,
                        before, after, reason, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        chapter = excluded.chapter,
                        entity = excluded.entity,
                        attribute = excluded.attribute,
                        before = excluded.before,
                        after = excluded.after,
                        reason = excluded.reason,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.chapter,
                        item.entity,
                        item.attribute,
                        item.before,
                        item.after,
                        item.reason,
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_state_change(item_id)
        if saved is None:
            raise ValueError("state change was not saved")
        return saved

    def get_state_change(self, change_id: str) -> StateChange | None:
        row = self._fetch_one("SELECT * FROM state_changes WHERE id = ?", (change_id,))
        return self._state_change_from_row(row) if row is not None else None

    def list_state_changes(
        self,
        story_id: str,
        workspace_id: str,
        through_chapter: int | None = None,
        limit: int | None = None,
    ) -> list[StateChange]:
        sql = "SELECT * FROM state_changes WHERE story_id = ? AND workspace_id = ?"
        params: list[Any] = [story_id, workspace_id]
        if through_chapter is not None:
            sql += " AND chapter <= ?"
            params.append(through_chapter)
        sql += " ORDER BY chapter DESC, updated_at DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._fetch_all(sql, params)
        return [self._state_change_from_row(row) for row in rows]

    def save_review_report(self, item: ReviewReport) -> ReviewReport:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "review_report_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO review_reports(
                        id, story_id, workspace_id, chapter, score, summary, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(story_id, workspace_id, chapter) DO UPDATE SET
                        score = excluded.score,
                        summary = excluded.summary,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.chapter,
                        item.score,
                        item.summary,
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_review_report(item.story_id, item.workspace_id, item.chapter)
        if saved is None:
            raise ValueError("review report was not saved")
        return saved

    def get_review_report(
        self,
        story_id: str,
        workspace_id: str,
        chapter: int,
    ) -> ReviewReport | None:
        row = self._fetch_one(
            """
            SELECT * FROM review_reports
            WHERE story_id = ? AND workspace_id = ? AND chapter = ?
            """,
            (story_id, workspace_id, chapter),
        )
        return self._review_report_from_row(row) if row is not None else None

    def list_review_reports(
        self,
        story_id: str,
        workspace_id: str,
        through_chapter: int | None = None,
        limit: int | None = None,
    ) -> list[ReviewReport]:
        sql = "SELECT * FROM review_reports WHERE story_id = ? AND workspace_id = ?"
        params: list[Any] = [story_id, workspace_id]
        if through_chapter is not None:
            sql += " AND chapter <= ?"
            params.append(through_chapter)
        sql += " ORDER BY chapter DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._fetch_all(sql, params)
        return [self._review_report_from_row(row) for row in rows]

    def save_review_issue(self, item: ReviewIssue) -> ReviewIssue:
        conn = self._connect()
        try:
            item_id = item.id or self._new_id(conn, "review_issue_")
            with conn:
                conn.execute(
                    """
                    INSERT INTO review_issues(
                        id, story_id, workspace_id, report_id, chapter, severity,
                        category, description, status, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        report_id = excluded.report_id,
                        chapter = excluded.chapter,
                        severity = excluded.severity,
                        category = excluded.category,
                        description = excluded.description,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        item_id,
                        item.story_id,
                        item.workspace_id,
                        item.report_id,
                        item.chapter,
                        item.severity,
                        item.category,
                        item.description,
                        item.status,
                        _to_json(item.metadata),
                    ),
                )
        finally:
            conn.close()
        saved = self.get_review_issue(item_id)
        if saved is None:
            raise ValueError("review issue was not saved")
        return saved

    def get_review_issue(self, issue_id: str) -> ReviewIssue | None:
        row = self._fetch_one("SELECT * FROM review_issues WHERE id = ?", (issue_id,))
        return self._review_issue_from_row(row) if row is not None else None

    def list_review_issues(
        self,
        story_id: str,
        workspace_id: str,
        status: str | None = None,
        through_chapter: int | None = None,
        limit: int | None = None,
    ) -> list[ReviewIssue]:
        sql = "SELECT * FROM review_issues WHERE story_id = ? AND workspace_id = ?"
        params: list[Any] = [story_id, workspace_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        if through_chapter is not None:
            sql += " AND chapter <= ?"
            params.append(through_chapter)
        sql += " ORDER BY chapter DESC, severity DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._fetch_all(sql, params)
        return [self._review_issue_from_row(row) for row in rows]

    def build_chapter_context(
        self,
        story_id: str,
        chapter: int,
        workspace_id: str | None = None,
        summary_limit: int = 5,
        timeline_limit: int | None = None,
        state_change_limit: int = 50,
        review_limit: int = 10,
        artifact_limit: int = 25,
    ) -> ChapterContext:
        story = self.get_story(story_id)
        if story is None:
            raise ValueError(f"story not found: {story_id}")
        workspace = self._resolve_workspace(story_id, workspace_id)
        return ChapterContext(
            story=story,
            workspace=workspace,
            chapter=chapter,
            plan=self.get_chapter_plan(story.id, workspace.id, chapter),
            characters=self.list_characters(story.id, workspace.id),
            world_rules=self.list_world_rules(story.id, workspace.id, status="active"),
            locations=self.list_locations(story.id, workspace.id),
            recent_summaries=self.list_chapter_summaries(
                story.id,
                workspace.id,
                before_chapter=chapter,
                limit=summary_limit,
            ),
            timeline=self.list_timeline_events(
                story.id,
                workspace.id,
                through_chapter=chapter,
                limit=timeline_limit,
            ),
            relationships=self.list_relationships(story.id, workspace.id, status="active"),
            foreshadows=self.list_foreshadows(story.id, workspace.id, status="open"),
            state_changes=self.list_state_changes(
                story.id,
                workspace.id,
                through_chapter=chapter,
                limit=state_change_limit,
            ),
            review_reports=self.list_review_reports(
                story.id,
                workspace.id,
                through_chapter=chapter - 1,
                limit=summary_limit,
            ),
            review_issues=self.list_review_issues(
                story.id,
                workspace.id,
                status="open",
                through_chapter=chapter,
                limit=review_limit,
            ),
            artifacts=self.list_artifacts(
                story.id,
                workspace_id=workspace.id,
                chapter=chapter,
                limit=artifact_limit,
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _new_id(self, conn: sqlite3.Connection, prefix: str) -> str:
        token = conn.execute("SELECT lower(hex(randomblob(16)))").fetchone()[0]
        return f"{prefix}{token}"

    def _fetch_one(self, sql: str, params: Iterable[Any]) -> sqlite3.Row | None:
        conn = self._connect()
        try:
            return conn.execute(sql, tuple(params)).fetchone()
        finally:
            conn.close()

    def _fetch_all(self, sql: str, params: Iterable[Any]) -> list[sqlite3.Row]:
        conn = self._connect()
        try:
            return list(conn.execute(sql, tuple(params)).fetchall())
        finally:
            conn.close()

    def _resolve_workspace(self, story_id: str, workspace_id: str | None) -> Workspace:
        if workspace_id is not None:
            workspace = self.get_workspace(workspace_id)
            if workspace is None or workspace.story_id != story_id:
                raise ValueError(f"workspace not found for story {story_id}: {workspace_id}")
            return workspace
        workspaces = self.list_workspaces(story_id)
        if not workspaces:
            raise ValueError(f"story has no workspace: {story_id}")
        return workspaces[0]

    def _story_from_row(self, row: sqlite3.Row) -> Story:
        return Story(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            metadata=_from_json(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _workspace_from_row(self, row: sqlite3.Row) -> Workspace:
        return Workspace(
            id=row["id"],
            story_id=row["story_id"],
            name=row["name"],
            status=row["status"],
            metadata=_from_json(row["metadata_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _run_from_row(self, row: sqlite3.Row) -> Run:
        return Run(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            status=row["status"],
            current_chapter=row["current_chapter"],
            node=row["node"],
            input=_from_json(row["input_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _event_from_row(self, row: sqlite3.Row) -> Event:
        return Event(
            id=row["id"],
            run_id=row["run_id"],
            seq=row["seq"],
            type=row["type"],
            node=row["node"],
            chapter=row["chapter"],
            payload=_from_json(row["payload_json"], {}),
            created_at=row["created_at"],
        )

    def _checkpoint_from_row(self, row: sqlite3.Row) -> Checkpoint:
        return Checkpoint(
            id=row["id"],
            run_id=row["run_id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            chapter=row["chapter"],
            state=_from_json(row["state_json"], {}),
            pending=_from_json(row["pending_json"], {}),
            created_at=row["created_at"],
        )

    def _artifact_from_row(self, row: sqlite3.Row) -> Artifact:
        return Artifact(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            run_id=row["run_id"],
            kind=row["kind"],
            chapter=row["chapter"],
            path=row["path"],
            content_type=row["content_type"],
            size=row["size"],
            metadata=_from_json(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def _character_from_row(self, row: sqlite3.Row) -> Character:
        return Character(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            role=row["role"],
            description=row["description"],
            status=row["status"],
            traits=_from_json(row["traits_json"], []),
            first_chapter=row["first_chapter"],
            last_chapter=row["last_chapter"],
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )

    def _world_rule_from_row(self, row: sqlite3.Row) -> WorldRule:
        return WorldRule(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            category=row["category"],
            rule=row["rule"],
            source_chapter=row["source_chapter"],
            status=row["status"],
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )

    def _location_from_row(self, row: sqlite3.Row) -> Location:
        return Location(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            description=row["description"],
            status=row["status"],
            first_chapter=row["first_chapter"],
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )

    def _chapter_plan_from_row(self, row: sqlite3.Row) -> ChapterPlan:
        return ChapterPlan(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            chapter=row["chapter"],
            title=row["title"],
            summary=row["summary"],
            beats=_from_json(row["beats_json"], []),
            status=row["status"],
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )

    def _chapter_summary_from_row(self, row: sqlite3.Row) -> ChapterSummary:
        return ChapterSummary(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            chapter=row["chapter"],
            title=row["title"],
            summary=row["summary"],
            key_events=_from_json(row["key_events_json"], []),
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )

    def _timeline_event_from_row(self, row: sqlite3.Row) -> TimelineEvent:
        return TimelineEvent(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            chapter=row["chapter"],
            sequence=row["sequence"],
            event=row["event"],
            participants=_from_json(row["participants_json"], []),
            location=row["location"],
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )

    def _relationship_from_row(self, row: sqlite3.Row) -> Relationship:
        return Relationship(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            source=row["source"],
            target=row["target"],
            relationship=row["relationship"],
            status=row["status"],
            since_chapter=row["since_chapter"],
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )

    def _foreshadow_from_row(self, row: sqlite3.Row) -> Foreshadow:
        return Foreshadow(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            key=row["key"],
            setup_chapter=row["setup_chapter"],
            payoff_chapter=row["payoff_chapter"],
            description=row["description"],
            status=row["status"],
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )

    def _state_change_from_row(self, row: sqlite3.Row) -> StateChange:
        return StateChange(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            chapter=row["chapter"],
            entity=row["entity"],
            attribute=row["attribute"],
            before=row["before"],
            after=row["after"],
            reason=row["reason"],
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )

    def _review_report_from_row(self, row: sqlite3.Row) -> ReviewReport:
        return ReviewReport(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            chapter=row["chapter"],
            score=row["score"],
            summary=row["summary"],
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )

    def _review_issue_from_row(self, row: sqlite3.Row) -> ReviewIssue:
        return ReviewIssue(
            id=row["id"],
            story_id=row["story_id"],
            workspace_id=row["workspace_id"],
            report_id=row["report_id"],
            chapter=row["chapter"],
            severity=row["severity"],
            category=row["category"],
            description=row["description"],
            status=row["status"],
            metadata=_from_json(row["metadata_json"], {}),
            updated_at=row["updated_at"],
        )


def open_store(db_path: str | Path, artifact_root: str | Path | None = None) -> FlashNovelStore:
    """Create a store and initialize its SQLite schema."""
    store = FlashNovelStore(db_path=db_path, artifact_root=artifact_root)
    store.initialize()
    return store


from app.memory.compat import install_compat

install_compat(FlashNovelStore)
