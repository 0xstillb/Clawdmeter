## Variant: Codex activity

### Design stance
Drop quota/budget language entirely and reframe the screen as session activity telemetry.

### Key choices
- Primary: current session duration
- Secondary: tool call count since attach
- Weekly: 7d activity trend in hours/sessions
- Keep the same Hermes-style layout and motion language

### Why this works for Codex
Codex does not naturally map to a visible budget/headroom model, so showing remaining quota would feel invented. Session time, tool calls, and weekly activity are truthful and still feel alive on-device.

### Trade-offs
- Strong at: truthful model-agnostic telemetry
- Weak at: less immediate if the user specifically wants spend/quota info
