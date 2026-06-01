from __future__ import annotations

import sys
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_load_env_file_sets_values_without_overriding_existing(tmp_path, monkeypatch) -> None:
    from app.config.env import load_env_file

    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# local model configuration",
                "FLASHNOVEL_PROVIDER=dashscope",
                'FLASHNOVEL_MODEL="qwen3.6-plus"',
                "export FLASHNOVEL_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1'",
                "FLASHNOVEL_API_KEY=from-file",
                "FLASHNOVEL_CONTEXT_BUDGET=20000 # inline comment",
            ]
        ),
        encoding="utf-8",
    )
    for key in [
        "FLASHNOVEL_PROVIDER",
        "FLASHNOVEL_MODEL",
        "FLASHNOVEL_BASE_URL",
        "FLASHNOVEL_CONTEXT_BUDGET",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FLASHNOVEL_API_KEY", "already-set")

    loaded = load_env_file(env_path)

    assert loaded is True
    assert env_path in load_env_file.loaded_paths
    assert os.environ["FLASHNOVEL_PROVIDER"] == "dashscope"
    assert os.environ["FLASHNOVEL_MODEL"] == "qwen3.6-plus"
    assert os.environ["FLASHNOVEL_BASE_URL"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert os.environ["FLASHNOVEL_API_KEY"] == "already-set"
    assert os.environ["FLASHNOVEL_CONTEXT_BUDGET"] == "20000"


def test_load_env_file_can_override_existing_values(tmp_path, monkeypatch) -> None:
    from app.config.env import load_env_file

    env_path = tmp_path / ".env"
    env_path.write_text("FLASHNOVEL_MODEL=qwen3.6-plus\n", encoding="utf-8")
    monkeypatch.setenv("FLASHNOVEL_MODEL", "old-model")

    assert load_env_file(env_path, override=True) is True
    assert os.environ["FLASHNOVEL_MODEL"] == "qwen3.6-plus"
