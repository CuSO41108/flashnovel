"""SQLite schema for FlashNovelStore."""

SCHEMA_SQL = """
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS stories (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(story_id, name)
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'queued',
                    current_chapter INTEGER NOT NULL DEFAULT 1,
                    node TEXT NOT NULL DEFAULT '',
                    input_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    node TEXT NOT NULL DEFAULT '',
                    chapter INTEGER,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(run_id, seq)
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    chapter INTEGER NOT NULL,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    pending_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
                    run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
                    kind TEXT NOT NULL,
                    chapter INTEGER,
                    path TEXT NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'text/plain',
                    size INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );

                CREATE TABLE IF NOT EXISTS characters (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    traits_json TEXT NOT NULL DEFAULT '[]',
                    first_chapter INTEGER,
                    last_chapter INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(story_id, workspace_id, name)
                );

                CREATE TABLE IF NOT EXISTS world_rules (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    category TEXT NOT NULL,
                    rule TEXT NOT NULL,
                    source_chapter INTEGER,
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(story_id, workspace_id, category, rule)
                );

                CREATE TABLE IF NOT EXISTS locations (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    first_chapter INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(story_id, workspace_id, name)
                );

                CREATE TABLE IF NOT EXISTS chapter_plans (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    chapter INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    beats_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'draft',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(story_id, workspace_id, chapter)
                );

                CREATE TABLE IF NOT EXISTS chapter_summaries (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    chapter INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    key_events_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(story_id, workspace_id, chapter)
                );

                CREATE TABLE IF NOT EXISTS timeline_events (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    chapter INTEGER NOT NULL,
                    sequence INTEGER NOT NULL DEFAULT 0,
                    event TEXT NOT NULL,
                    participants_json TEXT NOT NULL DEFAULT '[]',
                    location TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );

                CREATE TABLE IF NOT EXISTS relationships (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    relationship TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    since_chapter INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(story_id, workspace_id, source, target, relationship)
                );

                CREATE TABLE IF NOT EXISTS foreshadows (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    key TEXT NOT NULL,
                    setup_chapter INTEGER,
                    payoff_chapter INTEGER,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(story_id, workspace_id, key)
                );

                CREATE TABLE IF NOT EXISTS state_changes (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    chapter INTEGER NOT NULL,
                    entity TEXT NOT NULL,
                    attribute TEXT NOT NULL,
                    before TEXT NOT NULL DEFAULT '',
                    after TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );

                CREATE TABLE IF NOT EXISTS review_reports (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    chapter INTEGER NOT NULL,
                    score INTEGER,
                    summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(story_id, workspace_id, chapter)
                );

                CREATE TABLE IF NOT EXISTS review_issues (
                    id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    report_id TEXT REFERENCES review_reports(id) ON DELETE SET NULL,
                    chapter INTEGER NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'medium',
                    category TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );

                CREATE INDEX IF NOT EXISTS idx_workspaces_story ON workspaces(story_id);
                CREATE INDEX IF NOT EXISTS idx_runs_story_workspace ON runs(story_id, workspace_id);
                CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);
                CREATE INDEX IF NOT EXISTS idx_checkpoints_run_chapter ON checkpoints(run_id, chapter);
                CREATE INDEX IF NOT EXISTS idx_artifacts_story_workspace ON artifacts(story_id, workspace_id, chapter, kind);
                CREATE INDEX IF NOT EXISTS idx_timeline_story_chapter ON timeline_events(story_id, workspace_id, chapter, sequence);
                CREATE INDEX IF NOT EXISTS idx_state_changes_story_chapter ON state_changes(story_id, workspace_id, chapter);
                CREATE INDEX IF NOT EXISTS idx_review_issues_story_status ON review_issues(story_id, workspace_id, status, chapter);
"""
