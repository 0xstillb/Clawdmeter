#!/usr/bin/env python3
"""
Petdex -> Clawdmeter converter.

Converts petdex PNG sprite sequences to the ESP32 binary BLE payload format:

  [hold_ms:u16][frame_count:u16][palette:16xuint16][N*400 bytes]

Palette index 0 is reserved for transparency. Visible pixels use indices 1-15.

Clawdmeter-local pool directory structure:
  daemon/petdex/pool/<slug>/pet.json
  daemon/petdex/pool/<slug>/<state>/*.png
"""

import json
import struct
from pathlib import Path
from PIL import Image, ImageChops

GRID = 20
PET_CELLS = GRID * GRID
PAL_MAX = 16
VISIBLE_COLORS = PAL_MAX - 1
ALPHA_THRESHOLD = 128
MATTE_ALPHA_CUTOFF = 192
PET_MAX_FRAMES = 48
PET_BLE_HEADER = 4 + PAL_MAX * 2
POOL_DIR = Path(__file__).resolve().parent / "pool"
STANDARD_STATE_ORDER = (
    "idle",
    "running-right",
    "running-left",
    "waving",
    "jumping",
    "failed",
    "waiting",
    "running",
    "review",
)


class PetdexEngine:
    def __init__(self):
        self.pets = {}        # slug -> {states: {name: [png_paths]}}
        self.pet_meta = {}    # slug -> pet.json metadata (best-effort)
        self.active_slug = None
        self._frame_cache: dict[tuple[str, str, int], list[bytes]] = {}  # (slug, state, hold_ms) -> [payload_bytes]
        POOL_DIR.mkdir(parents=True, exist_ok=True)

    def discover(self) -> dict:
        """Scan pool/ for installed pets and their states."""
        self.pets.clear()
        self.pet_meta.clear()
        self._frame_cache.clear()
        for pet_dir in sorted(POOL_DIR.iterdir()):
            if not pet_dir.is_dir() or pet_dir.name.startswith("."):
                continue
            meta = {"id": pet_dir.name, "displayName": pet_dir.name}
            meta_path = pet_dir / "pet.json"
            if meta_path.is_file():
                try:
                    raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raw_meta = None
                if isinstance(raw_meta, dict):
                    pet_id = raw_meta.get("id")
                    if isinstance(pet_id, str) and pet_id.strip():
                        meta["id"] = pet_id.strip()
                    display_name = raw_meta.get("displayName")
                    if isinstance(display_name, str) and display_name.strip():
                        meta["displayName"] = display_name.strip()
            states = {}
            seen = set()
            for state_name in STANDARD_STATE_ORDER:
                state_dir = pet_dir / state_name
                if not state_dir.is_dir():
                    continue
                pngs = sorted(state_dir.glob("*.png"))
                if pngs:
                    states[state_dir.name] = [str(p) for p in pngs]
                    seen.add(state_dir.name)
            for state_dir in sorted(pet_dir.iterdir()):
                if not state_dir.is_dir() or state_dir.name in seen or state_dir.name.startswith("."):
                    continue
                pngs = sorted(state_dir.glob("*.png"))
                if pngs:
                    states[state_dir.name] = [str(p) for p in pngs]
            if states:
                self.pets[pet_dir.name] = states
                self.pet_meta[pet_dir.name] = meta
        return self.pets

    def get_display_name(self, slug: str) -> str:
        meta = self.pet_meta.get(slug)
        if isinstance(meta, dict):
            display_name = meta.get("displayName")
            if isinstance(display_name, str) and display_name.strip():
                return display_name
        return slug.capitalize()

    @staticmethod
    def _rgb565(rgb: tuple[int, int, int]) -> int:
        r, g, b = rgb
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

    @staticmethod
    def _prepare_frame(path: str) -> tuple[list[tuple[int, int, int]], list[bool]]:
        """Downsample one frame without pulling hidden atlas colors into edges."""
        with Image.open(path) as source:
            image = source.convert("RGBA")

        alpha = image.getchannel("A")
        # Discard very faint atlas matte pixels before downsampling. The Codex
        # sheets contain magenta RGB values behind transparent pixels.
        mask = alpha.point(lambda value: value if value >= ALPHA_THRESHOLD else 0)
        channels = image.getchannel("R"), image.getchannel("G"), image.getchannel("B")
        premultiplied = [
            ImageChops.multiply(channel, mask).resize(
                (GRID, GRID), Image.Resampling.BOX
            )
            for channel in channels
        ]
        resized_alpha = mask.resize((GRID, GRID), Image.Resampling.BOX)
        alpha_values = list(resized_alpha.getdata())
        color_values = [list(channel.getdata()) for channel in premultiplied]

        colors: list[tuple[int, int, int]] = []
        visible: list[bool] = []
        for pixel, coverage in enumerate(alpha_values):
            is_visible = coverage >= ALPHA_THRESHOLD
            if is_visible:
                color = tuple(
                    min(255, (color_values[channel][pixel] * 255 + coverage // 2) // coverage)
                    for channel in range(3)
                )
                r, g, b = color
                # Remove semi-transparent magenta matte remnants at the
                # silhouette edge while retaining opaque red/purple artwork.
                is_matte = (
                    coverage < MATTE_ALPHA_CUTOFF
                    and r > g
                    and b > g
                    and max(color) - min(color) >= 8
                    and abs(r - b) < 90
                )
                if is_matte:
                    is_visible = False
            visible.append(is_visible)
            if is_visible:
                colors.append(color)
            else:
                colors.append((0, 0, 0))
        return colors, visible

    def _convert_frames(self, paths: list[str]) -> tuple[list[bytes], list[int]] | None:
        """Quantize frames against one shared palette with index 0 transparent."""
        prepared = [self._prepare_frame(path) for path in paths]
        visible_colors = [
            color
            for colors, visible in prepared
            for color, is_visible in zip(colors, visible)
            if is_visible
        ]
        if not visible_colors:
            return None

        palette_source = Image.new("RGB", (len(visible_colors), 1))
        palette_source.putdata(visible_colors)
        quantized = palette_source.quantize(
            colors=VISIBLE_COLORS,
            # MAXCOVERAGE keeps rare accent colors instead of spending most
            # slots on nearly identical whites from the pet's body.
            method=Image.Quantize.MAXCOVERAGE,
            dither=Image.Dither.NONE,
        )
        raw_palette = quantized.getpalette()
        if raw_palette is None:
            return None

        used_colors = quantized.getcolors(maxcolors=len(visible_colors)) or []
        palette_size = max((index for _, index in used_colors), default=-1) + 1
        palette_size = min(palette_size, VISIBLE_COLORS)
        palette_rgb = [
            tuple(raw_palette[index * 3:index * 3 + 3])
            for index in range(palette_size)
        ]
        if not palette_rgb:
            return None

        def nearest_palette_index(color: tuple[int, int, int]) -> int:
            r, g, b = color
            return min(
                range(len(palette_rgb)),
                key=lambda index: (
                    (r - palette_rgb[index][0]) ** 2
                    + (g - palette_rgb[index][1]) ** 2
                    + (b - palette_rgb[index][2]) ** 2
                ),
            )

        frames: list[bytes] = []
        for colors, visible in prepared:
            # Shift visible colors by one because palette index 0 means clear.
            indices = bytearray(PET_CELLS)
            for pixel, (color, is_visible) in enumerate(zip(colors, visible)):
                if is_visible:
                    indices[pixel] = nearest_palette_index(color) + 1
            frames.append(bytes(indices))

        palette_rgb565 = [0]
        palette_rgb565.extend(self._rgb565(color) for color in palette_rgb)
        palette_rgb565.extend([0] * (PAL_MAX - len(palette_rgb565)))
        return frames, palette_rgb565

    def convert(self, png_paths: list[str], hold_ms: int = 200, max_frames: int | None = None) -> bytes | None:
        """
        Convert sorted PNG list to binary BLE payload.

        Payload:
          0..1     hold_ms (u16 LE)
          2..3     frame_count (u16 LE)
          4..35    palette (16 x u16 RGB565 LE; index 0 transparent)
          36..     N x 400 byte frame data
        """
        if not png_paths:
            return None

        # Limit frames if max_frames specified (avoids BLE long write failures)
        paths = sorted(png_paths)
        if max_frames is not None:
            paths = paths[:max_frames]

        result = self._convert_frames(paths)
        if result is None:
            return None
        frames_bytes, palette_rgb565 = result

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

        result = self._convert_frames(pngs)
        if result is None:
            return None
        frames, palette_rgb565 = result

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
            payload += raw[4:PET_BLE_HEADER]
            payload += raw[PET_BLE_HEADER:]
            return bytes(payload)

        return cached[frame_index]
