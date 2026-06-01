from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    out: list[str] = []
    for char in value:
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\":
            out.append(char)
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            break
        out.append(char)
    return "".join(out).strip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_env_lines(lines: Iterable[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _unquote(_strip_inline_comment(value.strip()))
    return values


def load_env_file(path: str | os.PathLike[str], *, override: bool = False) -> bool:
    env_path = Path(path).expanduser().resolve()
    if not env_path.is_file():
        return False
    values = _parse_env_lines(env_path.read_text(encoding="utf-8").splitlines())
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value
    load_env_file.loaded_paths.add(env_path)
    return True


load_env_file.loaded_paths: set[Path] = set()


def load_env(*, override: bool = False) -> list[Path]:
    candidates: list[Path] = []
    explicit = os.environ.get("FLASHNOVEL_ENV_FILE")
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend([Path.cwd() / ".env", _project_root() / ".env"])

    loaded: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        env_path = candidate.expanduser().resolve()
        if env_path in seen:
            continue
        seen.add(env_path)
        if load_env_file(env_path, override=override):
            loaded.append(env_path)
    return loaded
