from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

from daemon.petdex.petdex_engine import (
    GRID,
    PAL_MAX,
    PET_BLE_HEADER,
    PetdexEngine,
)


def _write_frame(path: Path, body_color: tuple[int, int, int]) -> None:
    image = Image.new("RGBA", (GRID, GRID), (255, 0, 255, 0))
    image.putpixel((4, 5), (*body_color, 255))
    image.putpixel((5, 5), (255, 255, 255, 127))
    image.save(path)


def test_convert_reserves_palette_zero_for_transparency(tmp_path: Path) -> None:
    frame = tmp_path / "frame.png"
    _write_frame(frame, (255, 128, 0))

    payload = PetdexEngine().convert([str(frame)])

    assert payload is not None
    assert len(payload) == PET_BLE_HEADER + GRID * GRID
    palette = struct.unpack_from(f"<{PAL_MAX}H", payload, 4)
    pixels = payload[PET_BLE_HEADER:]
    assert palette[0] == 0
    assert pixels[0] == 0
    assert pixels[5 * GRID + 4] != 0
    assert pixels[5 * GRID + 5] == 0


def test_downsample_removes_transparent_magenta_matte(tmp_path: Path) -> None:
    frame = tmp_path / "large-frame.png"
    image = Image.new("RGBA", (40, 40), (255, 0, 255, 0))
    for y in range(12, 28):
        for x in range(12, 28):
            image.putpixel((x, y), (255, 255, 255, 255))
    for y in range(40):
        image.putpixel((0, y), (255, 0, 255, 160))
    image.save(frame)

    colors, visible = PetdexEngine._prepare_frame(str(frame))

    assert any(visible)
    assert not any(
        is_visible and color[0] > 100 and color[2] > 80 and color[1] < 80
        for color, is_visible in zip(colors, visible)
    )


def test_convert_uses_one_palette_for_all_frames(tmp_path: Path) -> None:
    first = tmp_path / "001.png"
    second = tmp_path / "002.png"
    _write_frame(first, (255, 0, 0))
    _write_frame(second, (0, 255, 0))

    payload = PetdexEngine().convert([str(first), str(second)])

    assert payload is not None
    frame_size = GRID * GRID
    first_index = payload[PET_BLE_HEADER + 5 * GRID + 4]
    second_index = payload[PET_BLE_HEADER + frame_size + 5 * GRID + 4]
    palette = struct.unpack_from(f"<{PAL_MAX}H", payload, 4)
    assert first_index != 0
    assert second_index != 0
    assert palette[first_index] != palette[second_index]


def test_frame_payload_keeps_the_full_16_color_header(tmp_path: Path) -> None:
    pet_dir = tmp_path / "pet" / "idle"
    pet_dir.mkdir(parents=True)
    first = pet_dir / "001.png"
    second = pet_dir / "002.png"
    _write_frame(first, (255, 0, 0))
    _write_frame(second, (0, 255, 0))

    engine = PetdexEngine()
    engine.pets = {"pet": {"idle": [str(first), str(second)]}}
    cached = engine._build_cache("pet", "idle", 200)
    assert cached is not None

    payload = engine.get_frame_payload("pet", "idle", 200, 0, total_frames=3)

    assert payload is not None
    assert len(payload) == PET_BLE_HEADER + GRID * GRID
    assert payload[4:PET_BLE_HEADER] == cached[0][4:PET_BLE_HEADER]
    assert payload[PET_BLE_HEADER:] == cached[0][PET_BLE_HEADER:]
