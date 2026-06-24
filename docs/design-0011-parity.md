# Design 0011 Parity Checklist

Source of truth: [sketches/011-landscape-hermes-agent/index.html](../sketches/011-landscape-hermes-agent/index.html)

## Current gaps

- Typography: firmware `font_ui_*` used Segoe-derived assets; `0011` is Inter-based.
- Card treatment: firmware approximates the `0011` chrome, but it still lacks the softer border/glow balance and rotating sheen layer.
- Flow strip: firmware uses a canvas-rendered line instead of the mockup's animated centered fill treatment.
- Pairing hero: firmware uses a ring-stack pulse, not the mockup's three delayed expanding rings.
- Idle state: sprite alpha is now correct, but glow plate, cursor styling, and breathing cadence still need tuning.
- Header polish: provider badge, BLE emphasis, and agent badge spacing still need screenshot-based calibration after font migration.

## Implementation order

1. Swap all `font_ui_*` assets to Inter while keeping symbol names stable.
2. Re-tune landscape `compute_layout()` metrics for the new font widths and line heights.
3. Tighten header parity: title/provider spacing, BLE badge placement, agent badge size, battery coexistence.
4. Match usage cards: spacing, pill sizing, meta widths, bar thickness, and glow levels.
5. Match motion: flow strip, pair ring cadence, idle glow, idle breathe, idle cursor.
6. Verify on-device with framebuffer screenshots after each iteration.

## Screenshot review points

- Title and provider badge share the same baseline relationship as `0011`.
- Both cards sit at the same vertical rhythm and optical weight as the mockup.
- Pairing state reads left-to-right with the same balance between hero and steps.
- Idle hero feels centered with the same glow footprint and breathing range.
- Nothing clips at 320x240 landscape or the AMOLED rounded corners.
