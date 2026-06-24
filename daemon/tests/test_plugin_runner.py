"""Tests for PluginRunner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from daemon.plugin_runner import PluginRunner, PluginNotFoundError, PluginCrashedError
from daemon.plugin_protocol import PluginResponse


# ── helpers ────────────────────────────────────────────────────────────────


def _make_plugin(plugins_dir: Path, name: str, script: str) -> Path:
    """Create an executable plugin script and return its path."""
    path = plugins_dir / name
    path.write_text(script)
    path.chmod(0o755)
    return path


_GOOD_PLUGIN = """#!/usr/bin/env python3
import json, sys
line = sys.stdin.readline()
print(json.dumps({"ok": True, "payload": {"p": "test", "st": "ok", "ok": True}}))
"""

_BAD_PLUGIN = """#!/usr/bin/env python3
import json, sys
line = sys.stdin.readline()
print(json.dumps({"ok": False, "error": "something broke", "retry": True}))
"""

_CRASH_PLUGIN = """#!/usr/bin/env python3
import sys
sys.stderr.write("oh no\\n")
sys.exit(1)
"""

_NON_JSON_PLUGIN = """#!/usr/bin/env python3
print("not json")
"""


# ── discover ───────────────────────────────────────────────────────────────


def test_discover_finds_executable_plugins(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    _make_plugin(d, "claude", _GOOD_PLUGIN)
    _make_plugin(d, "codex", _GOOD_PLUGIN)

    runner = PluginRunner(d)
    discovered = runner.discover()
    assert set(discovered.keys()) == {"claude", "codex"}


def test_discover_skips_non_executable(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    p = d / "claude"
    p.write_text(_GOOD_PLUGIN)
    # deliberately not chmod +x

    runner = PluginRunner(d)
    discovered = runner.discover()
    assert "claude" not in discovered


def test_discover_empty_dir(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    runner = PluginRunner(d)
    assert runner.discover() == {}


def test_discover_missing_dir(tmp_path: Path) -> None:
    d = tmp_path / "plugins"  # doesn't exist
    runner = PluginRunner(d)
    assert runner.discover() == {}


def test_available_providers_order(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    _make_plugin(d, "zulu", _GOOD_PLUGIN)
    _make_plugin(d, "alpha", _GOOD_PLUGIN)

    runner = PluginRunner(d)
    assert runner.available_providers() == ["alpha", "zulu"]


def test_has_plugin(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    _make_plugin(d, "claude", _GOOD_PLUGIN)

    runner = PluginRunner(d)
    assert runner.has_plugin("claude") is True
    assert runner.has_plugin("codex") is False


def test_clear_cache(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    _make_plugin(d, "claude", _GOOD_PLUGIN)

    runner = PluginRunner(d)
    assert "claude" in runner.discover()

    # Add a new plugin without clearing cache
    _make_plugin(d, "codex", _GOOD_PLUGIN)
    assert "codex" not in runner.discover()  # cached

    runner.clear_cache()
    assert "codex" in runner.discover()  # fresh scan


# ── run ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_success(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    _make_plugin(d, "ok", _GOOD_PLUGIN)

    runner = PluginRunner(d)
    resp = await runner.run("ok")
    assert resp.ok is True
    assert resp.payload is not None
    assert resp.payload["p"] == "test"


@pytest.mark.asyncio
async def test_run_failure(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    _make_plugin(d, "bad", _BAD_PLUGIN)

    runner = PluginRunner(d)
    resp = await runner.run("bad")
    assert resp.ok is False
    assert resp.error == "something broke"
    assert resp.retry is True


@pytest.mark.asyncio
async def test_run_crash_nonzero_exit(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    _make_plugin(d, "crash", _CRASH_PLUGIN)

    runner = PluginRunner(d)
    with pytest.raises(PluginCrashedError, match="crash"):
        await runner.run("crash")


@pytest.mark.asyncio
async def test_run_crash_invalid_json(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    _make_plugin(d, "badjson", _NON_JSON_PLUGIN)

    runner = PluginRunner(d)
    with pytest.raises(PluginCrashedError, match="invalid JSON"):
        await runner.run("badjson")


@pytest.mark.asyncio
async def test_run_not_found(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()

    runner = PluginRunner(d)
    with pytest.raises(PluginNotFoundError, match="nonexistent"):
        await runner.run("nonexistent")


@pytest.mark.asyncio
async def test_run_timeout(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    sleep_plugin = """#!/usr/bin/env python3
import time
time.sleep(30)
print('{}')
"""
    _make_plugin(d, "slow", sleep_plugin)

    runner = PluginRunner(d)
    with pytest.raises(PluginCrashedError, match="timed out"):
        await runner.run("slow", timeout=0.5)


@pytest.mark.asyncio
async def test_run_passes_request_via_stdin(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    echo_plugin = """#!/usr/bin/env python3
import json, sys
line = sys.stdin.readline()
data = json.loads(line)
# Echo back what we received
print(json.dumps({"ok": True, "payload": {"version_received": data["version"]}}))
"""
    _make_plugin(d, "echo", echo_plugin)

    runner = PluginRunner(d)
    resp = await runner.run("echo", prev_payload={"p": "test"}, last_error="prev err")
    assert resp.ok is True
    assert resp.payload["version_received"] == 1


@pytest.mark.asyncio
async def test_run_sets_env_vars(tmp_path: Path) -> None:
    d = tmp_path / "plugins"
    d.mkdir()
    env_plugin = """#!/usr/bin/env python3
import json, os
print(json.dumps({
    "ok": True,
    "payload": {
        "plugin_dir": os.environ.get("CLAWDMETER_PLUGIN_DIR", ""),
        "data_dir": os.environ.get("CLAWDMETER_DATA_DIR", ""),
    }
}))
"""
    _make_plugin(d, "envcheck", env_plugin)

    runner = PluginRunner(d)
    resp = await runner.run("envcheck")
    assert resp.ok is True
    assert str(d) in resp.payload["plugin_dir"]
