# Daemon Plugin Protocol v1

A plugin is any executable file inside `daemon/plugins/` that follows this protocol.

## Invocation

```
$ ./daemon/plugins/<name> [--debug]
```

The daemon sets these env vars before spawning:

| Env var | Description |
|---------|-------------|
| `CLAWDMETER_PLUGIN_DIR` | Absolute path to the plugins directory |
| `CLAWDMETER_DATA_DIR` | Persistent data directory (e.g. `~/.config/clawdmeter/`) |
| `CLAWDMETER_POLL_INTERVAL` | Daemon poll interval in seconds (int) |

## Input (stdin)

Every invocation, the daemon writes ONE JSON line to stdin:

```json
{
  "version": 1,
  "action": "poll",
  "prev_payload": { ... } | null,
  "last_error": "..." | null
}
```

`prev_payload` is the daemon's last known BLE payload (if any). `last_error` is the
last error message from this plugin's previous run (if any).

## Output (stdout)

The plugin writes EXACTLY ONE JSON line to stdout, then exits.

### Success

```json
{
  "ok": true,
  "payload": {
    "p": "claude",
    "mode": "window",
    "top": { "label": "Current", "kind": "window_short", "pct": 45, "reset_mins": 120, "has_reset": true },
    "bottom": { "label": "Weekly", "kind": "window_long", "pct": 28, "reset_mins": 7200, "has_reset": true },
    "st": "allowed",
    "ok": true
  }
}
```

Payload must include at minimum `p` (provider id), `mode`, `top`, `bottom`, `st`, and `ok`.
Include legacy flat fields (`s`, `sr`, `w`, `wr`) for backward BLE compatibility.

### Transient failure (retry next poll)

```json
{
  "ok": false,
  "error": "Network timeout",
  "retry": true
}
```

The daemon will retry the same plugin on the next poll tick.

### Permanent failure (credential expired — show toast)

```json
{
  "ok": false,
  "error": "token expired — run claude login",
  "retry": false
}
```

The daemon shows this error to the user (toast/tooltip) and keeps retrying the
plugin each poll cycle. Set `retry: false` only for credential/auth errors so
the user knows they need to take action.

## Exit code

Always 0. Errors are communicated via the JSON output. A non-zero exit code
is treated as a crash — the daemon logs the stderr and treats it as a
transient failure (retries next poll).

## Language

Any language. The executable must be self-contained or its dependencies must
be documented in a comment header. For Python plugins, add the repo root to
`sys.path` so they can import from `daemon.payloads` or `daemon.plugin_protocol`:

```python
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
```

## Debugging

Pass `--debug` to get verbose stderr logging. The flag is optional; plugins
should default to silent operation.
