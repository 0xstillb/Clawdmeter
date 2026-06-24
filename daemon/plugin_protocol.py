"""Plugin protocol types for Clawdmeter provider plugins.

Every plugin is a standalone executable under daemon/plugins/ that
follows the JSON/stdio protocol defined in DAEMON_PLUGIN_PROTOCOL.md.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import json
import sys


@dataclass
class PluginRequest:
    version: int = 1
    action: str = "poll"
    prev_payload: dict[str, Any] | None = None
    last_error: str | None = None

    @classmethod
    def from_stdin(cls) -> PluginRequest:
        line = sys.stdin.readline()
        if not line:
            return cls()
        data = json.loads(line)
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps({
            "version": self.version,
            "action": self.action,
            "prev_payload": self.prev_payload,
            "last_error": self.last_error,
        })


@dataclass
class PluginResponse:
    ok: bool
    payload: dict[str, Any] | None = None
    error: str | None = None
    retry: bool = True

    def to_json(self) -> str:
        return json.dumps({
            "ok": self.ok,
            "payload": self.payload,
            "error": self.error,
            "retry": self.retry,
        })

    @classmethod
    def success(cls, payload: dict) -> PluginResponse:
        return cls(ok=True, payload=payload)

    @classmethod
    def failure(cls, error: str, retry: bool = True) -> PluginResponse:
        return cls(ok=False, error=error, retry=retry)
