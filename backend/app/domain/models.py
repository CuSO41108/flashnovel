"""Dataclass domain objects used by the memory store."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Story:
    id: str
    title: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class Workspace:
    id: str
    story_id: str
    name: str
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class Run:
    id: str
    story_id: str
    workspace_id: str
    status: str = "queued"
    current_chapter: int = 1
    node: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class Event:
    id: str
    run_id: str
    seq: int
    type: str
    node: str = ""
    chapter: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(slots=True)
class Checkpoint:
    id: str
    run_id: str
    story_id: str
    workspace_id: str
    chapter: int
    state: dict[str, Any] = field(default_factory=dict)
    pending: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(slots=True)
class Artifact:
    id: str
    story_id: str
    workspace_id: str | None
    run_id: str | None
    kind: str
    path: str
    chapter: int | None = None
    content_type: str = "text/plain"
    size: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(slots=True)
class Character:
    story_id: str
    workspace_id: str
    name: str
    id: str = ""
    role: str = ""
    description: str = ""
    status: str = "active"
    traits: list[str] = field(default_factory=list)
    first_chapter: int | None = None
    last_chapter: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class WorldRule:
    story_id: str
    workspace_id: str
    category: str
    rule: str
    id: str = ""
    source_chapter: int | None = None
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class Location:
    story_id: str
    workspace_id: str
    name: str
    id: str = ""
    description: str = ""
    status: str = "active"
    first_chapter: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class ChapterPlan:
    story_id: str
    workspace_id: str
    chapter: int
    id: str = ""
    title: str = ""
    summary: str = ""
    beats: list[str] = field(default_factory=list)
    status: str = "draft"
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class ChapterSummary:
    story_id: str
    workspace_id: str
    chapter: int
    id: str = ""
    title: str = ""
    summary: str = ""
    key_events: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class TimelineEvent:
    story_id: str
    workspace_id: str
    chapter: int
    event: str
    id: str = ""
    sequence: int = 0
    participants: list[str] = field(default_factory=list)
    location: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class Relationship:
    story_id: str
    workspace_id: str
    source: str
    target: str
    relationship: str
    id: str = ""
    status: str = "active"
    since_chapter: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class Foreshadow:
    story_id: str
    workspace_id: str
    key: str
    description: str
    id: str = ""
    setup_chapter: int | None = None
    payoff_chapter: int | None = None
    status: str = "open"
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class StateChange:
    story_id: str
    workspace_id: str
    chapter: int
    entity: str
    attribute: str
    after: str
    id: str = ""
    before: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class ReviewReport:
    story_id: str
    workspace_id: str
    chapter: int
    id: str = ""
    score: int | None = None
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class ReviewIssue:
    story_id: str
    workspace_id: str
    chapter: int
    description: str
    id: str = ""
    report_id: str | None = None
    severity: str = "medium"
    category: str = ""
    status: str = "open"
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


@dataclass(slots=True)
class ChapterContext:
    story: Story
    workspace: Workspace
    chapter: int
    plan: ChapterPlan | None = None
    characters: list[Character] = field(default_factory=list)
    world_rules: list[WorldRule] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    recent_summaries: list[ChapterSummary] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    foreshadows: list[Foreshadow] = field(default_factory=list)
    state_changes: list[StateChange] = field(default_factory=list)
    review_reports: list[ReviewReport] = field(default_factory=list)
    review_issues: list[ReviewIssue] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
