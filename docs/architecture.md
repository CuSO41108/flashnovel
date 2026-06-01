# flashnovel Architecture

## Purpose

`flashnovel` is an Agent Runtime for long-form fiction and screenplay creation. The project goal is to generate chapters through an observable, resumable workflow while preserving story continuity in structured memory instead of repeatedly sending the full manuscript to the model.

The intended chapter loop is:

```text
context -> plan -> draft -> extract -> check -> review -> rewrite -> commit -> checkpoint
```

The runtime is designed around three product promises:

- chapter-level orchestration with pause, resume, cancel, and confirmation points;
- structured story memory for canon, timeline, characters, foreshadowing, state changes, review issues, and artifacts;
- event visibility through persisted runtime events and Server-Sent Events.

## Current Code Layout

```text
backend/app/
  api/        FastAPI app factory, dependency wiring, DTOs, and HTTP routes
  domain/     Dataclass domain model definitions for stories, runs, memory, and artifacts
  graph/      Chapter workflow state, node functions, and LangGraph/fallback orchestration
  llm/        OpenAI-compatible chat client and reusable prompt templates
  memory/     SQLite state store plus file-backed artifact storage
  runtime/    Run queue, worker loop, runtime host, service facade, and event objects
  tools/      Workflow tool registry for context, planning, drafting, review, rewrite, and commit
```

The Python package is rooted at `backend`, as configured in `pyproject.toml`.

## API Layer

`app.api.app.create_app()` builds the FastAPI application, installs permissive CORS, and includes the health, story, workspace, and run routers.

The API surface currently covers:

- `GET /health`
- story creation, listing, lookup, and chapter lookup under `/stories`
- workspace, memory, and artifact views under `/workspaces`
- run creation, listing, lookup, pause, resume, cancel, confirm, event polling, and SSE streaming under `/runs`

Routes depend on `app.api.deps.get_service()`. The service is lazy-created from `FLASHNOVEL_DATA_DIR`, and worker startup/shutdown is attached to FastAPI lifecycle events. A smoke test should create the app object without entering lifespan so it does not start the worker or require persistence backends.

## Runtime Layer

`FlashNovelService` is the facade used by routes. It owns:

- a persistent store, expected as `app.memory.store.FlashNovelStore`;
- a `RunRegistry` queue for queued/running tasks and abort flags;
- a `RuntimeHost` that executes the chapter workflow.

`RunRegistry` is an in-process task registry. It tracks queued tasks, busy run IDs, task completion state, and abort requests.

`WorkerManager` is a lightweight daemon thread that repeatedly claims queued tasks and calls the service executor. Errors are captured on the task rather than raised through the worker loop.

`RuntimeHost` bridges workflow nodes to tools. It emits runtime events, creates checkpoints, checks abort state, and delegates actual content/memory operations through a tool registry expected as `app.tools`. LLM access is expected behind `app.llm.client`.

## Graph Layer

`NovelWorkflow` compiles a LangGraph state machine when `langgraph` is available. If graph construction fails, it falls back to an explicit sequential runner with the same node order and conditional decisions.

The workflow state is a `TypedDict` named `GraphState`. Nodes mutate and return this state. Key transitions are:

- `review` routes to `rewrite` when the review verdict asks for `rewrite` or `polish` and the rewrite count is below the limit;
- `review` routes to `commit` otherwise;
- `checkpoint` either continues with the next chapter or finishes in `awaiting_confirmation`/`paused` state.

Checkpoints are batch-oriented. The README describes a five-chapter confirmation cadence; the implementation generalizes this through `max_chapters`, defaulting to `5`.

## Memory And Artifacts

The memory store is intentionally concrete rather than abstract-heavy:

- SQLite stores structured state: story, workspace, run, event, checkpoint, character, world rule, location, chapter plan, chapter summary, timeline event, relationship, foreshadow, state change, review report, and review issue records.
- The file artifact store keeps large or inspectable text: drafts, committed chapters, prompt snapshots, raw LLM output, and review artifacts.
- `build_chapter_context()` / `get_writer_context()` assemble a chapter context from recent summaries, canon, timeline, relationships, foreshadows, state changes, review reminders, and relevant artifacts.

The four memory layers are a conceptual and API grouping, not four duplicate physical tables:

- Artifact: chapter files, drafts, prompt snapshots, raw outputs, and review artifacts.
- Canon: characters, world rules, locations, and other stable story facts.
- Episodic: chapter summaries and timeline events.
- Continuity: relationships, foreshadows, state changes, and unresolved review issues.

Candidate memory is extracted after drafting, but it is only promoted into long-term memory during `commit_chapter`. That prevents rejected or rewritten drafts from polluting the story state.

## Event Flow

Runtime nodes emit events for:

- node start/completion;
- chapter planning, drafting, review, rewrite, and commit;
- tool calls and LLM deltas;
- checkpoint creation;
- run start, pause, awaiting confirmation, and completion.

`GET /runs/{run_id}/events` returns persisted events. `GET /runs/{run_id}/events/stream` streams the same event model as SSE until the run reaches a terminal or waiting state and no newer events remain.

## External Boundaries

External integrations are concentrated in small boundary modules:

- `app.llm.client` is a dependency-free OpenAI-compatible `/chat/completions` client configured by `FLASHNOVEL_BASE_URL`, `FLASHNOVEL_API_KEY`, and `FLASHNOVEL_MODEL`, with `OPENAI_*` fallbacks.
- `app.tools.sync_tools` provides the runtime-facing tool registry used by `RuntimeHost`.
- `app.memory.store` keeps all SQLite/file side effects behind a Store API so workflow nodes stay side-effect-light.

## Verification Strategy

Lightweight design smoke tests should stay intentionally cheap:

- import core API, runtime, graph, and domain modules;
- create the FastAPI app through `create_app()` without entering lifespan;
- assert expected route paths are registered;
- assert core source files exist on disk.

These tests should not require a real LLM key, network access, a running database, or an external worker process.

An additional fake-LLM end-to-end smoke path should instantiate `FlashNovelService`, swap the runtime tool registry to a fake LLM, create a story, run a five-chapter batch, and assert:

- the run stops in `awaiting_confirmation`;
- `current_chapter` and workspace `next_chapter` advance to chapter 6;
- SSE/pollable events are persisted;
- chapter artifacts are readable from the file store;
- summaries, timeline, relationships, foreshadows, and state changes are written to SQLite.
