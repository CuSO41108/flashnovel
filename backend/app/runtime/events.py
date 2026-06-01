from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RuntimeEvent:
    run_id: str
    type: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "run_id": self.run_id,
            "type": self.type,
            "message": self.message,
            "payload": self.payload,
            "created_at": self.created_at,
        }
