from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


CORE_MODULES = [
    "app.api.app",
    "app.api.dto",
    "app.api.routes.health",
    "app.api.routes.runs",
    "app.api.routes.stories",
    "app.api.routes.workspaces",
    "app.domain.models",
    "app.graph.nodes",
    "app.graph.state",
    "app.graph.workflow",
    "app.runtime.events",
    "app.runtime.registry",
    "app.runtime.service",
    "app.runtime.worker",
]


CORE_PATHS = [
    "backend/app/api/app.py",
    "backend/app/api/deps.py",
    "backend/app/api/dto.py",
    "backend/app/graph/nodes.py",
    "backend/app/graph/state.py",
    "backend/app/graph/workflow.py",
    "backend/app/runtime/events.py",
    "backend/app/runtime/host.py",
    "backend/app/runtime/registry.py",
    "backend/app/runtime/service.py",
    "backend/app/runtime/worker.py",
    "backend/app/domain/models.py",
]


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_core_modules_import_without_external_services(module_name: str) -> None:
    module = importlib.import_module(module_name)

    assert module is not None


def test_api_app_factory_registers_expected_routes_without_lifespan() -> None:
    from fastapi import FastAPI

    from app.api.app import create_app

    api = create_app()
    route_paths = {getattr(route, "path", "") for route in api.routes}

    assert isinstance(api, FastAPI)
    assert "/health" in route_paths
    assert "/stories" in route_paths
    assert "/stories/{story_id}" in route_paths
    assert "/workspaces/{story_id}/memory" in route_paths
    assert "/runs" in route_paths
    assert "/runs/{run_id}/events/stream" in route_paths


def test_core_source_paths_exist() -> None:
    missing = [path for path in CORE_PATHS if not (PROJECT_ROOT / path).is_file()]

    assert missing == []
