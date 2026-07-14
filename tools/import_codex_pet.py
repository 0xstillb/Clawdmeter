#!/usr/bin/env python3
"""Import a Codex pet pack into Clawdmeter's petdex pool.

Expected input layout:
  <pet-dir>/pet.json
  <pet-dir>/spritesheet.webp

The standard Codex pet sheet is 8 columns by 9 rows:
  idle, running-right, running-left, waving, jumping, failed, waiting,
  running, review

This script splits the sheet into the Clawdmeter pool layout:
  daemon/petdex/pool/<slug>/<state>/*.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from daemon.petdex.petdex_engine import STANDARD_STATE_ORDER


def _read_pet_meta(pet_dir: Path) -> dict:
    meta_path = pet_dir / "pet.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"missing pet.json: {meta_path}")
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"pet.json must contain an object: {meta_path}")
    pet_id = data.get("id")
    if not isinstance(pet_id, str) or not pet_id.strip():
        raise ValueError(f"pet.json missing id: {meta_path}")
    spritesheet = data.get("spritesheetPath", "spritesheet.webp")
    if not isinstance(spritesheet, str) or not spritesheet.strip():
        raise ValueError(f"pet.json missing spritesheetPath: {meta_path}")
    return data


def import_pet(source_dir: Path, output_root: Path) -> Path:
    meta = _read_pet_meta(source_dir)
    pet_id = meta["id"].strip()
    sheet_path = source_dir / str(meta.get("spritesheetPath", "spritesheet.webp"))
    if not sheet_path.is_file():
        raise FileNotFoundError(f"missing spritesheet: {sheet_path}")

    img = Image.open(sheet_path).convert("RGBA")
    width, height = img.size
    cols = 8
    rows = len(STANDARD_STATE_ORDER)
    if width % cols or height % rows:
        raise ValueError(f"unexpected sheet size {width}x{height}; expected a {cols}x{rows} grid")
    cell_w = width // cols
    cell_h = height // rows

    target_dir = output_root / pet_id
    target_dir.mkdir(parents=True, exist_ok=True)

    # Keep the original pet metadata alongside the Clawdmeter pool assets.
    (target_dir / "pet.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for row_index, state_name in enumerate(STANDARD_STATE_ORDER):
        state_dir = target_dir / state_name
        state_dir.mkdir(parents=True, exist_ok=True)
        for stale in state_dir.glob("*.png"):
            stale.unlink()
        top = row_index * cell_h
        for col_index in range(cols):
            left = col_index * cell_w
            frame = img.crop((left, top, left + cell_w, top + cell_h))
            # Petdex rows have eight slots, but shorter animations leave the
            # trailing slots fully transparent. Do not send those as blank
            # frames to the ESP.
            if frame.getchannel("A").getextrema()[1] < 128:
                continue
            frame.save(state_dir / f"{col_index + 1:03d}.png")

    return target_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path, help="Codex pet directory (contains pet.json and spritesheet.webp)")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "daemon" / "petdex" / "pool",
        help="Clawdmeter petdex pool root",
    )
    args = parser.parse_args()

    target = import_pet(args.source_dir, args.output_root)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
