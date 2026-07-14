from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path


def _plugin_module():
    path = Path(__file__).parents[1] / "plugins" / "deepseek"
    loader = importlib.machinery.SourceFileLoader("test_deepseek_plugin", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_deepseek_accepts_short_environment_key(monkeypatch) -> None:
    plugin = _plugin_module()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_KEY", "deepseek-test-key")

    assert plugin._read_credentials() == {"api_key": "deepseek-test-key"}


def test_deepseek_remaining_bar_uses_high_water_balance(monkeypatch) -> None:
    plugin = _plugin_module()
    state: dict = {}
    monkeypatch.setattr(plugin, "_read_state", lambda: state.copy() or None)
    monkeypatch.setattr(plugin, "_write_state", lambda value: state.update(value))

    first = plugin._compute_balance_progress(50.0)
    spent = plugin._compute_balance_progress(40.0)
    topped_up = plugin._compute_balance_progress(55.0)

    assert first["baseline"] == 50.0
    assert first["spent"] == 0.0
    assert spent["baseline"] == 50.0
    assert spent["spent"] == 10.0
    assert topped_up["baseline"] == 55.0
    assert topped_up["spent"] == 0.0
