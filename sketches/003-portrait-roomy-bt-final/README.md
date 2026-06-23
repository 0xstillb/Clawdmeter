## Variant: portrait-roomy-bt-final

### Design stance
Freeze the refined portrait mockup that keeps the firmware semantics but adds the approved polish pass: calmer spacing, aligned chips, larger idle character, and a firmware-style Bluetooth status icon.

### Key choices
- Layout: 240×320 portrait frame with two stacked usage cards and the same three states (usage / pairing / idle)
- Header: optically centered `Usage` title with a right-side pixel Bluetooth indicator instead of a fake battery or placeholder label
- Typography: neutral sentence-case `Current` / `Weekly` chips aligned to the metric baseline
- Character: enlarged idle mascot with tightened surrounding spacing so it reads correctly on the tiny TFT

### Trade-offs
- Strong at: preserving the approved look as a locked reference for the next design round
- Weak at: slightly more polished than the raw firmware geometry, so it is a design reference rather than a literal dump of LVGL coordinates

### Best for
- Serving as the kept baseline while a new alternative design direction is explored next
