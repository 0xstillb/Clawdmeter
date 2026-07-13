from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path


def _plugin_module():
    path = Path(__file__).parents[1] / "plugins" / "minimax"
    loader = importlib.machinery.SourceFileLoader("test_minimax_plugin", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_minimax_uses_coding_plan_remains_endpoints() -> None:
    plugin = _plugin_module()

    urls = plugin._remains_urls()

    assert urls[0] == "https://api.minimax.io/v1/token_plan/remains"
    assert all("token_plan/remains" in url for url in urls)
    assert "text/chatcompletion" not in " ".join(urls)
