#!/usr/bin/env python3
"""
Petdex -> Clawdmeter converter.

Converts petdex PNG sprite sequences to the ESP32 binary BLE payload format:

  [hold_ms:u16][frame_count:u16][palette:10xuint16][N*400 bytes]

Pool directory structure:
  daemon/petdex/pool/<slug>/<state>/*.png
"""

import struct
from pathlib import Path
from PIL import Image

GRID = 20
PAL_MAX = 10
PET_MAX_FRAMES = 48
POOL_DIR = Path(__file__).resolve().parent / "pool"


class PetdexEngine:
    def __init__(self):
        self.pets = {}        # slug -> {states: {name: [png_paths]}}
        self.active_slug = None
        POOL_DIR.mkdir(parents=True, exist_ok=True)

    def discover(self) -> dict:
        """Scan pool/ for installed pets and their states."""
        self.pets.clear()
        for pet_dir in sorted(POOL_DIR.iterdir()):
            if not pet_dir.is_dir() or pet_dir.name.startswith("."):
                continue
            states = {}
            for state_dir in sorted(pet_dir.iterdir()):
                if not state_dir.is_dir():
                    continue
                pngs = sorted(state_dir.glob("*.png"))
                if pngs:
                    states[state_dir.name] = [str(p) for p in pngs]
            if states:
                self.pets[pet_dir.name] = states
        return self.pets

    def convert(self, png_paths: list[str], hold_ms: int = 200) -> bytes | None:
        """
        Convert sorted PNG list to binary BLE payload.

        Payload:
          0..1     hold_ms (u16 LE)
          2..3     frame_count (u16 LE)
          4..23    palette (10 x u16 RGB565 LE)
          24..     N x 400 byte frame data
        """
        if not png_paths:
            return None

        frames_bytes = []
        palette_rgb565 = None

        for path in sorted(png_paths):
            img = Image.open(path).convert("RGB").resize((GRID, GRID), Image.Resampling.NEAREST)
            # Quantize to PAL_MAX colors
            img = img.quantize(colors=PAL_MAX)

            # Extract palette -> RGB565
            pal_raw = img.getpalette()
            if pal_raw is None:
                continue
            rgb565 = []
            for i in range(0, min(len(pal_raw), PAL_MAX * 3), 3):
                r, g, b = pal_raw[i], pal_raw[i + 1], pal_raw[i + 2]
                rgb565.append(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
            while len(rgb565) < PAL_MAX:
                rgb565.append(0)  # pad

            if palette_rgb565 is None:
                palette_rgb565 = rgb565

            # Frame indices (PIL quantize stores palette indices directly)
            indices = bytes(list(img.getdata()))  # 400 bytes, values 0..PAL_MAX-1
            frames_bytes.append(indices)

        if not frames_bytes or palette_rgb565 is None:
            return None

        # Build binary payload
        n_frames = min(len(frames_bytes), PET_MAX_FRAMES)
        payload = bytearray()
        payload += struct.pack('<HH', hold_ms, n_frames)
        for c in palette_rgb565:
            payload += struct.pack('<H', c)
        for i in range(n_frames):
            payload += frames_bytes[i]

        return bytes(payload)

    def get_payload(self, slug: str, state: str = "idle",
                    hold_ms: int = 200) -> bytes | None:
        """Get BLE-ready payload for a pet state."""
        if slug not in self.pets:
            return None
        pngs = self.pets[slug].get(state)
        if not pngs:
            return None
        return self.convert(pngs, hold_ms)

    def seed_from_hermes(self, slug: str) -> bool:
        """Copy pet from ~/.hermes/pets/<slug>/ if available."""
        import shutil
        src = Path.home() / ".hermes" / "pets" / slug
        if not src.exists():
            return False
        dest = POOL_DIR / slug
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        self.discover()
        return True
