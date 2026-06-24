# Clawdmeter Provider Plugins

Each executable file in this directory is a provider plugin. The daemon
discovers them at startup and calls the one matching the user's provider
preference.

## How to add a new provider

1. Create an executable file in this directory named after your provider
   (e.g. `my_provider` — no extension on POSIX)
2. Implement the JSON/stdio protocol (see [`DAEMON_PLUGIN_PROTOCOL.md`](../../DAEMON_PLUGIN_PROTOCOL.md))
3. The plugin must be executable (`chmod +x`)
4. Restart the daemon — it auto-discovers the new plugin

## Existing plugins

| File | Provider | Language | Dependencies |
|------|----------|----------|-------------|
| `claude` | Anthropic Claude | Python | httpx |
| `codex` | OpenAI Codex | Python | httpx |
| `go` | OpenCode Go | Python | httpx |

## Protocol overview

```
Plugin ← stdin: {"version":1,"action":"poll","prev_payload":...,"last_error":...}
Plugin → stdout: {"ok":true,"payload":{...}}
Plugin → exit 0
```

See `DAEMON_PLUGIN_PROTOCOL.md` for the full specification.
