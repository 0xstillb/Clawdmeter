"""PluginRunner — subprocess manager for Clawdmeter provider plugins.

Discovers executable files in a designated plugins directory and runs them
as child processes following the JSON/stdio protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
import sys
from pathlib import Path
from typing import Any

from daemon.plugin_protocol import PluginRequest, PluginResponse


log = logging.getLogger("clawdmeter.plugin_runner")


class PluginNotFoundError(Exception):
    """Raised when the requested plugin does not exist or is not executable."""


class PluginCrashedError(Exception):
    """Raised when a plugin exits non-zero, times out, or returns invalid JSON."""


def _is_executable(path: Path) -> bool:
    """Return True if *path* is a regular file with at least one execute bit set."""
    try:
        if not path.is_file():
            return False
        if os.name == "nt":
            suffix = path.suffix.lower()
            if suffix in {".exe", ".bat", ".cmd", ".com", ".ps1", ".py", ".pyw"}:
                return True
            if suffix == "":
                try:
                    first_line = path.open("r", encoding="utf-8", errors="ignore").readline()
                except OSError:
                    return False
                return first_line.startswith("#!")
            return False
        return bool(path.stat().st_mode & stat.S_IXUSR)
    except OSError:
        return False


def _plugin_name(path: Path) -> str:
    """Return the stem (filename without extension) as the plugin identifier."""
    return path.stem


def _preferred_python(path: Path) -> str:
    """Return the best Python interpreter for plugin subprocesses."""
    override = os.environ.get("CLAWDMETER_PYTHON", "").strip()
    if override:
        return override

    repo_python = path.resolve().parent.parent.parent / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt" and repo_python.is_file():
        return str(repo_python)

    return sys.executable


def _plugin_command(path: Path) -> list[str]:
    """Return the subprocess command used to launch *path* on this platform."""
    if os.name == "nt":
        suffix = path.suffix.lower()
        if suffix in {".py", ".pyw"} or suffix == "":
            return [_preferred_python(path), str(path)]
        if suffix == ".ps1":
            return [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(path),
            ]
    return [str(path)]


class PluginRunner:
    """Discovers and invokes provider plugins.

    Plugins live in a designated *plugins_dir* (e.g. ``daemon/plugins/``).
    Each plugin is an executable file whose basename (without extension) is
    the provider ID (``claude``, ``codex``, ``go``, etc.).

    Results are cached until ``clear_cache()`` is called.
    """

    def __init__(self, plugins_dir: str | Path) -> None:
        self._plugins_dir = Path(plugins_dir)
        self._cache: dict[str, Path] | None = None

    # ── discovery ────────────────────────────────────────────────────────────

    def discover(self) -> dict[str, Path]:
        """Scan *plugins_dir* for executable files and return ``{name: path}``.

        Results are cached; call ``clear_cache()`` to re-scan.
        """
        if self._cache is not None:
            return self._cache

        if not self._plugins_dir.is_dir():
            self._cache = {}
            return self._cache

        result: dict[str, Path] = {}
        for entry in sorted(self._plugins_dir.iterdir()):
            if _is_executable(entry):
                name = _plugin_name(entry)
                result[name] = entry

        self._cache = result
        return result

    def clear_cache(self) -> None:
        """Invalidate the plugin discovery cache so the next ``discover()`` rescans."""
        self._cache = None

    def available_providers(self) -> list[str]:
        """Return sorted list of available provider IDs."""
        return sorted(self.discover().keys())

    def has_plugin(self, provider_id: str) -> bool:
        """Return True if *provider_id* is a known plugin."""
        return provider_id in self.discover()

    # ── execution ────────────────────────────────────────────────────────────

    async def run(
        self,
        provider_id: str,
        *,
        prev_payload: dict[str, Any] | None = None,
        last_error: str | None = None,
        timeout: float = 25.0,
    ) -> PluginResponse:
        """Run the named provider plugin and return its response.

        Args:
            provider_id: Plugin name (basename without extension).
            prev_payload: The last known BLE payload from this provider.
            last_error: The error from the previous invocation (if any).
            timeout: Maximum seconds to wait for the subprocess.

        Returns:
            A ``PluginResponse`` parsed from the plugin's stdout.

        Raises:
            PluginNotFoundError: The plugin doesn't exist in the discovery set.
            PluginCrashedError: Non-zero exit, timeout, or invalid JSON output.
        """
        plugins = self.discover()
        path = plugins.get(provider_id)
        if path is None:
            raise PluginNotFoundError(
                f"Plugin not found: {provider_id}"
                f" (available: {', '.join(self.available_providers())})"
            )

        request = PluginRequest(
            prev_payload=prev_payload,
            last_error=last_error,
        )

        # Build the subprocess environment
        plugin_env = {
            **os.environ,
            "CLAWDMETER_PLUGIN_DIR": str(self._plugins_dir),
            "CLAWDMETER_DATA_DIR": os.environ.get(
                "CLAWDMETER_DATA_DIR",
                str(Path.home() / ".config" / "clawdmeter"),
            ),
            "CLAWDMETER_POLL_INTERVAL": os.environ.get(
                "CLAWDMETER_POLL_INTERVAL", "60"
            ),
        }

        try:
            cmd = _plugin_command(path)
            if log.isEnabledFor(logging.DEBUG):
                cmd.append("--debug")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=plugin_env,
            )
        except OSError as e:
            raise PluginCrashedError(
                f"Failed to spawn plugin {provider_id}: {e}"
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(request.to_json().encode()),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise PluginCrashedError(
                f"Plugin {provider_id} timed out after {timeout}s"
            )

        # Capture stderr for diagnostics (forward if the plugin said --debug)
        stderr_text = stderr_bytes.decode().strip()
        if stderr_text:
            for line in stderr_text.splitlines():
                log.debug("[plugin %s] %s", provider_id, line)

        if proc.returncode != 0:
            raise PluginCrashedError(
                f"Plugin {provider_id} crashed (exit {proc.returncode}): "
                + (stderr_text or "no stderr")
            )

        try:
            data = json.loads(stdout_bytes.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise PluginCrashedError(
                f"Plugin {provider_id} returned invalid JSON: {e}"
            )

        return PluginResponse(
            ok=bool(data.get("ok", False)),
            payload=data.get("payload"),
            error=data.get("error"),
            retry=bool(data.get("retry", True)),
        )
