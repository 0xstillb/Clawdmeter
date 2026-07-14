from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from tools.import_codex_pet import import_pet


def test_import_skips_empty_animation_slots(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pet.json").write_text(
        json.dumps({"id": "test-pet", "spritesheetPath": "spritesheet.webp"}),
        encoding="utf-8",
    )

    sheet = Image.new("RGBA", (80, 90), (0, 0, 0, 0))
    for row in range(9):
        sheet.putpixel((5, row * 10 + 5), (255, 255, 255, 255))
    sheet.save(source / "spritesheet.webp", lossless=True)

    target = import_pet(source, tmp_path / "pool")

    assert [path.name for path in (target / "idle").glob("*.png")] == ["001.png"]
    assert [path.name for path in (target / "review").glob("*.png")] == ["001.png"]
