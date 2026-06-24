# Plugin System Architecture

The Clawdmeter daemon now uses a **plugin system** for provider integration.
Each provider (Claude, Codex, OpenCode Go, etc.) is a standalone executable
(`daemon/plugins/<provider_id>`) that communicates with the daemon via a
simple JSON-over-stdio protocol.

## Why plugins?

- **Any language**: plugins can be Python, Go, Rust, shell scripts, etc.
- **Isolation**: a plugin crash doesn't take down the daemon; it retries next poll
- **Self-contained credentials**: each plugin manages its own auth — no shared state
- **Easy to add**: drop a new executable in `daemon/plugins/` and restart

## Architecture

```
┌─────────────────────┐         JSON/stdio          ┌──────────────────┐
│  Daemon (asyncio)   │  ────────────────────────→  │  Plugin (any      │
│                     │  {"version":1,"action":"poll"│   language)       │
│  BLE connect/write  │  ←────────────────────────│                   │
│  Tray state bridge   │  {"ok":true,"payload":{...}}│                   │
│  PluginRunner        │                             └──────────────────┘
└─────────────────────┘
```

### Key components

| Component | File | Purpose |
|-----------|------|---------|
| `PluginRequest` | `daemon/plugin_protocol.py` | Input dataclass sent to plugins |
| `PluginResponse` | `daemon/plugin_protocol.py` | Output dataclass returned by plugins |
| `PluginRunner` | `daemon/plugin_runner.py` | Discovers plugins, spawns subprocesses, parses responses |
| Provider plugins | `daemon/plugins/` | Executable files implementing the protocol |

## Protocol

See [`DAEMON_PLUGIN_PROTOCOL.md`](../DAEMON_PLUGIN_PROTOCOL.md) for the full spec.

**Quick summary:**
1. Daemon spawns the plugin as a child process
2. Daemon writes one JSON line to stdin (request)
3. Plugin writes one JSON line to stdout (response)
4. Plugin exits with code 0

## Adding a new provider

1. Create an executable file in `daemon/plugins/<your_provider>`:
   ```bash
   touch daemon/plugins/my_provider
   chmod +x daemon/plugins/my_provider
   ```
2. Implement the JSON/stdio protocol
3. Add your credential dialog to `daemon/tray_windows.py` (optional, Windows only)
4. Restart the daemon

### Python plugin template

```python
#!/usr/bin/env python3
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from daemon.plugin_protocol import PluginRequest, PluginResponse
import asyncio

async def main():
    req = PluginRequest.from_stdin()
    # ... fetch usage data ...
    payload = {"p": "my_provider", "mode": "window", ...}
    print(PluginResponse.success(payload).to_json())

if __name__ == "__main__":
    asyncio.run(main())
```

## Migration status

| Provider | Before | After |
|----------|--------|-------|
| Claude | Inline in both daemon files | `daemon/plugins/claude` |
| Codex | Inline in Windows daemon | `daemon/plugins/codex` |
| OpenCode Go | Inline in both daemon files | `daemon/plugins/go` |

Both `claude_usage_daemon.py` (macOS) and `claude_usage_daemon_windows.py`
(Windows) now use `PluginRunner` for provider dispatch — no inline provider logic remains.
