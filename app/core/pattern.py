"""
Repeating wallpaper patterns.

A tile is repeated across the wall at a real repeat size, with a straight,
half-drop, brick or mirror match. Tiles can be made seamless. Rendering works
on any region in metres, so very large walls are produced panel by panel.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageOps

from app.core import imaging as im

REPEATS = {
    "straight": "Straight match",
    "half_drop": "Half drop",
    "brick": "Brick (half across)",
    "mirror": "Mirror",
}


@dataclass
class PatternSpec:
    tile: str = ""             # tile image path (relative to the job folder)
    repeat_w: float = 0.53     # width of one repeat (m)
    repeat_type: str = "straight"
    seamless: bool = False
    blend: float = 0.25
    offset_x: float = 0.0      # shift of the pattern (m)
    offset_y: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PatternSpec":
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


def make_seamless(tile: Image.Image, blend: float = 0.25) -> Image.Image:
    """Hide the edges of a tile so it repeats without visible joins.

    The tile is blended with a copy shifted by half its size; near the edges
    the shifted copy (whose edges are the continuous middle of the tile) wins.
    """
    blend = min(max(blend, 0.05), 0.5)
    mode = "RGBA" if tile.mode == "RGBA" else "RGB"
    a = np.asarray(tile.convert(mode), dtype=np.float32)
    h, w = a.shape[:2]
    shifted = np.roll(np.roll(a, h // 2, axis=0), w // 2, axis=1)
    x = np.minimum(np.arange(w), w - 1 - np.arange(w)) / max(1.0, w * blend)
    y = np.minimum(np.arange(h), h - 1 - np.arange(h)) / max(1.0, h * blend)
    wx = np.clip(x, 0, 1)
    wy = np.clip(y, 0, 1)
    # smoothstep
    wx = wx * wx * (3 - 2 * wx)
    wy = wy * wy * (3 - 2 * wy)
    m = (wy[:, None] * wx[None, :])[..., None]
    out = a * m + shifted * (1 - m)
    return Image.fromarray(np.clip(out, 0, 255).astype("uint8"), mode)


def unit_tile(tile: Image.Image, spec: PatternSpec) -> Image.Image:
    """The tile actually repeated (mirror = 2 × 2 block)."""
    t = make_seamless(tile, spec.blend) if spec.seamless else tile.convert("RGB")
    if spec.repeat_type == "mirror":
        w, h = t.size
        block = Image.new(t.mode, (w * 2, h * 2))
        block.paste(t, (0, 0))
        block.paste(ImageOps.mirror(t), (w, 0))
        block.paste(ImageOps.flip(t), (0, h))
        block.paste(ImageOps.flip(ImageOps.mirror(t)), (w, h))
        return block
    return t


class PatternSource:
    """Renders any wall region (metres) of a repeating pattern."""

    def __init__(self, tile: Image.Image, spec: PatternSpec, background=(255, 255, 255)):
        self.spec = spec
        self.tile = unit_tile(tile, spec)
        base_w = spec.repeat_w * (2 if spec.repeat_type == "mirror" else 1)
        self.rw = max(0.01, base_w)
        self.rh = self.rw * self.tile.height / self.tile.width
        self.bg = background
        self._cache_key = None
        self._cache: Optional[Image.Image] = None

    @property
    def size_px(self) -> Tuple[int, int]:
        return self.tile.size

    @property
    def ppi(self) -> float:
        return self.tile.width / self.rw * 0.0254

    def _scaled(self, tw: int, th: int, fast: bool) -> Image.Image:
        key = (tw, th, fast)
        if key != self._cache_key:
            if fast or (tw <= self.tile.width and th <= self.tile.height):
                self._cache = self.tile.resize((tw, th), Image.Resampling.BILINEAR if fast else Image.Resampling.LANCZOS,
                                               reducing_gap=None if fast else 3.0)
            else:
                self._cache = im.resample(self.tile, (tw, th), im.UPSCALE_ENHANCED)
            self._cache_key = key
        return self._cache

    def render(self, x0: float, y0: float, x1: float, y1: float, out_w: int, out_h: int,
               fast: bool = False) -> Image.Image:
        out_w, out_h = max(1, int(out_w)), max(1, int(out_h))
        sx = out_w / max(1e-9, x1 - x0)
        sy = out_h / max(1e-9, y1 - y0)
        tw_f, th_f = self.rw * sx, self.rh * sy
        tw, th = int(math.ceil(tw_f)) + 1, int(math.ceil(th_f)) + 1
        if tw < 1 or th < 1:
            return Image.new("RGB", (out_w, out_h), self.bg)
        tile = self._scaled(tw, th, fast).convert("RGB")
        canvas = Image.new("RGB", (out_w, out_h), self.bg)
        ox, oy = self.spec.offset_x, self.spec.offset_y
        rt = self.spec.repeat_type
        i0 = int(math.floor((x0 - ox) / self.rw)) - 1
        i1 = int(math.ceil((x1 - ox) / self.rw)) + 1
        for i in range(i0, i1 + 1):
            col_dy = (self.rh / 2) if (rt == "half_drop" and i % 2) else 0.0
            j0 = int(math.floor((y0 - oy - col_dy) / self.rh)) - 1
            j1 = int(math.ceil((y1 - oy - col_dy) / self.rh)) + 1
            for j in range(j0, j1 + 1):
                row_dx = (self.rw / 2) if (rt == "brick" and j % 2) else 0.0
                tx = ox + i * self.rw + row_dx
                ty = oy + j * self.rh + col_dy
                px = int(math.floor((tx - x0) * sx))
                py = int(math.floor((ty - y0) * sy))
                if px >= out_w or py >= out_h or px + tw <= 0 or py + th <= 0:
                    continue
                canvas.paste(tile, (px, py))
        return canvas

    def repeat_file(self, dpi: int) -> Image.Image:
        """One repeat at print resolution (for step-and-repeat in the RIP)."""
        ppm = dpi / 0.0254
        w = max(1, round(self.rw * ppm))
        if self.spec.repeat_type in ("half_drop", "brick"):
            # the smallest rectangle that repeats straight is 2 repeats
            if self.spec.repeat_type == "half_drop":
                return self.render(0, 0, self.rw * 2, self.rh, max(1, round(2 * self.rw * ppm)),
                                   max(1, round(self.rh * ppm)))
            return self.render(0, 0, self.rw, self.rh * 2, w, max(1, round(2 * self.rh * ppm)))
        return self.render(0, 0, self.rw, self.rh, w, max(1, round(self.rh * ppm)))
