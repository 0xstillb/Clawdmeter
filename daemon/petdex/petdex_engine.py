#!/usr/bin/env python3
"""
Petdex -> Clawdmeter converter.

Converts petdex PNG sprite sequences to the ESP32 binary BLE payload format:

  [hold_ms:u16][frame_count:u16][palette:10xuint16][N*400 bytes]

Clawdmeter-local pool directory structure:
  daemon/petdex/pool/<slug>/<state>/*.png
"""

import struct
from pathlib import Path
from PIL import Image

GRID = 20
PAL_MAX = 16
PET_MAX_FRAMES = 48
POOL_DIR = Path(__file__).resolve().parent / "pool"


class PetdexEngine:
    def __init__(self):
        self.pets = {}        # slug -> {states: {name: [png_paths]}}
        self.active_slug = None
        self._frame_cache: dict[tuple[str, str, int], list[bytes]] = {}  # (slug, state, hold_ms) -> [payload_bytes]
        POOL_DIR.mkdir(parents=True, exist_ok=True)

    def discover(self) -> dict:
        """Scan pool/ for installed pets and their states."""
        self.pets.clear()
        self._frame_cache.clear()
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

    def _convert_single(self, path: str, palette_rgb565: list[int] | None) -> tuple[bytes, list[int]] | None:
        """Load one PNG, quantize, return (palette_idx_bytes, palette_rgb565)."""
        img = Image.open(path).convert("RGB").resize((GRID, GRID), Image.Resampling.NEAREST)
        img = img.quantize(colors=PAL_MAX)

        pal_raw = img.getpalette()
        if pal_raw is None:
            return None

        rgb565 = []
        for i in range(0, min(len(pal_raw), PAL_MAX * 3), 3):
            r, g, b = pal_raw[i], pal_raw[i + 1], pal_raw[i + 2]
            rgb565.append(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
        while len(rgb565) < PAL_MAX:
            rgb565.append(0)

        if palette_rgb565 is not None:
            # Use the established palette (first frame's palette)
            rgb565 = palette_rgb565

        indices = bytes(list(img.getdata()))  # 400 bytes, values 0..PAL_MAX-1
        return indices, rgb565

    def convert(self, png_paths: list[str], hold_ms: int = 200, max_frames: int | None = None) -> bytes | None:
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

        # Limit frames if max_frames specified (avoids BLE long write failures)
        paths = sorted(png_paths)
        if max_frames is not None:
            paths = paths[:max_frames]

        frames_bytes = []
        palette_rgb565 = None

        for path in paths:
            result = self._convert_single(path, palette_rgb565)
            if result is None:
                continue
            indices, pal = result
            if palette_rgb565 is None:
                palette_rgb565 = pal
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
                    hold_ms: int = 200, max_frames: int | None = None) -> bytes | None:
        """Get BLE-ready payload for a pet state."""
        if slug not in self.pets:
            return None
        pngs = self.pets[slug].get(state)
        if not pngs:
            return None
        return self.convert(pngs, hold_ms, max_frames=max_frames)

    def get_frame_count(self, slug: str, state: str) -> int:
        """Return number of frames available for a pet state."""
        if slug not in self.pets:
            return 0
        pngs = self.pets[slug].get(state)
        if not pngs:
            return 0
        return len(pngs)

    def _build_cache(self, slug: str, state: str, hold_ms: int) -> list[bytes] | None:
        """
        Convert all frames for (slug, state, hold_ms) and cache individual
        frame payloads. Each payload has frame_count=total in the header so
        the firmware knows the animation length.
        """
        if slug not in self.pets:
            return None
        pngs = self.pets[slug].get(state)
        if not pngs:
            return None

        frames: list[bytes] = []
        palette_rgb565 = None

        for path in pngs:
            result = self._convert_single(path, palette_rgb565)
            if result is None:
                continue
            indices, pal = result
            if palette_rgb565 is None:
                palette_rgb565 = pal
            frames.append(indices)

        if not frames or palette_rgb565 is None:
            return None

        total = len(frames)
        cached: list[bytes] = []
        for idx in range(total):
            payload = bytearray()
            payload += struct.pack('<HH', hold_ms, total)  # frame_count = total (all frames exist)
            for c in palette_rgb565:
                payload += struct.pack('<H', c)
            payload += frames[idx]
            cached.append(bytes(payload))

        self._frame_cache[(slug, state, hold_ms)] = cached
        return cached

    def get_frame_payload(self, slug: str, state: str, hold_ms: int,
                          frame_index: int, total_frames: int) -> bytes | None:
        """
        Get BLE payload for a single frame at given index.

        The header carries frame_count=total_frames so the firmware knows how
        many frames exist (even though only one frame is in this write).
        Converts on first access and caches results.
        """
        cache_key = (slug, state, hold_ms)
        cached = self._frame_cache.get(cache_key)
        if cached is None:
            cached = self._build_cache(slug, state, hold_ms)
            if cached is None:
                return None

        if frame_index < 0 or frame_index >= len(cached):
            return None

        # If the caller's total_frames differs from cache, rebuild with a
        # single-frame header so the firmware sees frame_count=total_frames.
        if total_frames != len(cached):
            # Rebuild header for this specific frame with the given total_frames
            raw = cached[frame_index]
            payload = bytearray()
            payload += struct.pack('<HH', hold_ms, total_frames)
            # palette is at bytes 4..23 in the cached payload
            payload += raw[4:24]
            # frame data at bytes 24..
            payload += raw[24:]
            return bytes(payload)

        return cached[frame_index]
