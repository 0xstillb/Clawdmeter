"""Shared Windows daemon configuration.

The tray writes this file and the daemon reads it every poll, so provider
switches take effect without restarting the process.  Provider metadata lives
here so adding a future provider updates the tray menu and daemon preference
normalization from one place.

Plugins are auto-discovered from ``daemon/plugins/`` at runtime; the hardcoded
``PROVIDERS`` tuple acts as a fallback when the plugins directory is absent
(e.g. during unit tests or source distributions).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from daemon.plugin_runner import PluginRunner


CONFIG_ENV_PROVIDER = "CLAWDMETER_PROVIDER"
CONFIG_DIR_NAME = "Clawdmeter"
CONFIG_FILE_NAME = "config.json"
PROVIDER_AUTO = "auto"


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    aliases: tuple[str, ...] = ()
    auto_probe: bool = True


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(PROVIDER_AUTO, "Auto", auto_probe=False),
    ProviderSpec("codex", "Codex", aliases=("openai", "opencode")),
    ProviderSpec("claude", "Claude"),
    ProviderSpec("go", "OpenCode Go", aliases=("opencode-go",)),
    ProviderSpec("deepseek", "DeepSeek"),
    ProviderSpec("minimax", "MiniMax"),
    ProviderSpec("openrouter", "OpenRouter", aliases=("or",)),
    ProviderSpec("zen", "OpenCode Zen"),
)


def _provider_map() -> dict[str, ProviderSpec]:
    result: dict[str, ProviderSpec] = {}
    for provider in PROVIDERS:
        result[provider.id] = provider
        for alias in provider.aliases:
            result[alias] = provider
    return result


def normalize_provider(value: object) -> str:
    if not isinstance(value, str):
        return PROVIDER_AUTO
    raw = value.strip().lower()
    if not raw:
        return PROVIDER_AUTO
    provider = _provider_map().get(raw)
    return provider.id if provider else PROVIDER_AUTO


def provider_choices() -> tuple[ProviderSpec, ...]:
    """Return available provider choices, discovered from plugins.

    Falls back to the hardcoded ``PROVIDERS`` tuple when no plugins are found.
    """
    return discover_providers()


def auto_provider_ids() -> tuple[str, ...]:
    return tuple(provider.id for provider in PROVIDERS if provider.auto_probe)


# ── Plugin-based provider discovery ──────────────────────────────────────


def _plugins_dir() -> Path:
    """Return the expected plugins directory relative to this file."""
    return Path(__file__).resolve().parent / "plugins"


def discover_providers(plugins_dir: str | Path | None = None) -> tuple[ProviderSpec, ...]:
    """Return provider choices based on plugin discovery.

    Falls back to the hardcoded ``PROVIDERS`` tuple when no plugins
    directory is found (e.g. unit tests, source distribution).
    """
    if plugins_dir is None:
        plugins_dir = _plugins_dir()
    try:
        from daemon.plugin_runner import PluginRunner  # noqa: F811

        runner = PluginRunner(plugins_dir)
        names = runner.available_providers()
    except ImportError:
        names = []

    if not names:
        return PROVIDERS

    return (ProviderSpec(PROVIDER_AUTO, "Auto", auto_probe=False),) + tuple(
        ProviderSpec(name, name.replace("-", " ").title()) for name in names
    )


def config_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / CONFIG_DIR_NAME


def config_path() -> Path:
    return config_dir() / CONFIG_FILE_NAME


def load_config() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: dict) -> bool:
    try:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except OSError:
        return False
    return True


def configured_provider() -> str | None:
    data = load_config()
    if "provider" not in data:
        return None
    return normalize_provider(data.get("provider"))


def set_provider(provider_id: str) -> bool:
    data = load_config()
    data["provider"] = normalize_provider(provider_id)
    return save_config(data)


def provider_preference() -> str:
    """Return the effective provider preference.

    The tray config wins because it is the interactive control surface.  The
    environment variable remains as a script-friendly fallback when no config
    file has been written yet.
    """
    configured = configured_provider()
    if configured is not None:
        return configured
    return normalize_provider(os.environ.get(CONFIG_ENV_PROVIDER, PROVIDER_AUTO))
