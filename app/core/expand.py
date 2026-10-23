"""
Expand a design so it fits the wall without cutting anything off.

When a customer's picture is narrower (or shorter) than the wall, "Fill" would
crop it and "Fit" would leave empty bands. Expanding adds new picture at the
sides (or top / bottom) instead:

* Soft mirror    – the edge reflected and gradually softened (nature, abstract)
* Stretch edges  – the edge pixels stretched outwards (skies, plain backgrounds)
* Blurred background – a soft, blurred version of the picture behind it
* AI (online)    – new matching content drawn by an AI model (Replicate account)

The original pixels are never changed; only the new margins are made.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

METHODS = {
    "mirror": "Soft mirror",
    "stretch": "Stretch edges",
    "blur": "Blurred background",
    "ai": "AI – new picture content (online)",
}
WORK_MAX = 2000


@dataclass
class ExpandPlan:
    left: int
    right: int
    top: int
    bottom: int
    size: Tuple[int, int]          # original design size

    @property
    def out_size(self) -> Tuple[int, int]:
        return self.size[0] + self.left + self.right, self.size[1] + self.top + self.bottom

    @property
    def empty(self) -> bool:
        return self.left + self.right + self.top + self.bottom == 0

    def describe(self, px_per_m: float) -> str:
        parts = []
        for n, v in (("left", self.left), ("right", self.right), ("top", self.top), ("bottom", self.bottom)):
            if v:
                parts.append(f"{v / px_per_m * 100:.0f} cm on the {n}" if px_per_m else f"{v} px on the {n}")
        return ", ".join(parts) if parts else "nothing – the design already fits"


def plan(design_size: Tuple[int, int], target_aspect: float, where: str = "even", extra: float = 0.0) -> ExpandPlan:
    """Pixels to add so the design has `target_aspect` (width ÷ height).

    where: even / left / right (for wider) or even / top / bottom (for taller); 'left' means
    the new picture goes on the left. `extra` adds that fraction all round (e.g. 0.02).
    """
    dw, dh = design_size
    a = dw / dh
    left = right = top = bottom = 0
    if target_aspect > a * 1.002:                     # wall is wider: add at the sides
        add = int(round(dh * target_aspect)) - dw
        if where == "left":
            left = add
        elif where == "right":
            right = add
        else:
            left = add // 2
            right = add - left
    elif target_aspect < a / 1.002:                   # wall is taller: add top / bottom
        add = int(round(dw / target_aspect)) - dh
        if where == "top":
            top = add
        elif where == "bottom":
            bottom = add
        else:
            top = add // 2
            bottom = add - top
    if extra > 0:
        e = int(round(max(dw, dh) * extra))
        left, right, top, bottom = left + e, right + e, top + e, bottom + e
    return ExpandPlan(left, right, top, bottom, design_size)


def _distance(plan_: ExpandPlan, scale: float) -> np.ndarray:
    """Distance (px) of every output pixel from the original picture."""
    W, H = plan_.out_size
    W, H = max(1, int(round(W * scale))), max(1, int(round(H * scale)))
    x0, y0 = plan_.left * scale, plan_.top * scale
    x1, y1 = x0 + plan_.size[0] * scale, y0 + plan_.size[1] * scale
    xs = np.arange(W, dtype=np.float32) + 0.5
    ys = np.arange(H, dtype=np.float32) + 0.5
    dx = np.maximum(np.maximum(x0 - xs, xs - x1), 0)[None, :]
    dy = np.maximum(np.maximum(y0 - ys, ys - y1), 0)[:, None]
    return np.sqrt(dx * dx + dy * dy)


def _pad(a: np.ndarray, pl: ExpandPlan, scale: float, mode: str) -> np.ndarray:
    l, r = int(round(pl.left * scale)), int(round(pl.right * scale))
    t, b = int(round(pl.top * scale)), int(round(pl.bottom * scale))
    H, W = a.shape[:2]
    out_w, out_h = max(1, int(round(pl.out_size[0] * scale))), max(1, int(round(pl.out_size[1] * scale)))
    r += out_w - (W + l + r)
    b += out_h - (H + t + b)
    if mode == "symmetric":
        # reflect repeatedly if the margin is wider than the picture
        res = a
        while l > 0 or r > 0 or t > 0 or b > 0:
            hh, ww = res.shape[:2]
            sl, sr, st, sb = min(l, ww), min(r, ww), min(t, hh), min(b, hh)
            res = np.pad(res, ((st, sb), (sl, sr), (0, 0)), mode="symmetric")
            l, r, t, b = l - sl, r - sr, t - st, b - sb
        return res
    return np.pad(a, ((t, b), (l, r), (0, 0)), mode="edge")


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur; large blurs are done on a smaller copy (same look, much faster)."""
    H, W = a.shape[:2]
    img = Image.fromarray(a)
    if sigma > 6:
        f = sigma / 4.0
        small = img.resize((max(2, int(W / f)), max(2, int(H / f))), Image.Resampling.BILINEAR)
        small = small.filter(ImageFilter.GaussianBlur(4))
        return np.asarray(small.resize((W, H), Image.Resampling.BICUBIC), np.float32)
    return np.asarray(img.filter(ImageFilter.GaussianBlur(max(0.5, sigma))), np.float32)


def _soften(padded: np.ndarray, dist: np.ndarray, strength: float) -> np.ndarray:
    """Blur more the further a pixel is from the original picture."""
    H, W = padded.shape[:2]
    base = max(H, W)
    sig = [base * f * strength for f in (0.004, 0.015, 0.045, 0.11)]
    layers = [padded.astype(np.float32)] + [_blur(padded, s) for s in sig]
    # 0 at the picture edge → most blurred far away
    t = np.clip(dist / (base * 0.25), 0, 1) * (len(layers) - 1)
    out = np.zeros_like(layers[0])
    for i in range(len(layers)):
        w = np.clip(1 - np.abs(t - i), 0, 1)[..., None]
        out += layers[i] * w
    return out


def _feather_paste(canvas: Image.Image, img: Image.Image, at: Tuple[int, int], feather: int) -> Image.Image:
    """Paste the original picture back, blending only its outermost `feather` pixels."""
    if feather <= 0:
        canvas.paste(img, at)
        return canvas
    w, h = img.size
    m = np.ones((h, w), np.float32)
    f = min(feather, w // 4, h // 4)
    if f > 0:
        ramp = np.linspace(0, 1, f + 2, dtype=np.float32)[1:-1]
        m[:, :f] = np.minimum(m[:, :f], ramp[None, :])
        m[:, w - f:] = np.minimum(m[:, w - f:], ramp[::-1][None, :])
        m[:f, :] = np.minimum(m[:f, :], ramp[:, None])
        m[h - f:, :] = np.minimum(m[h - f:, :], ramp[::-1][:, None])
    canvas.paste(img, at, Image.fromarray((m * 255).astype("uint8")))
    return canvas


def expand_offline(img: Image.Image, pl: ExpandPlan, method: str = "mirror") -> Image.Image:
    """Add the margins in `pl` without AI. The original picture stays pixel-perfect."""
    if pl.empty:
        return img.copy()
    rgb = img.convert("RGB")
    scale = min(1.0, WORK_MAX / max(pl.out_size))
    small = rgb if scale >= 1 else rgb.resize((max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))),
                                              Image.Resampling.LANCZOS)
    a = np.asarray(small)
    dist = _distance(pl, scale)
    if method == "blur":
        Wo, Ho = dist.shape[1], dist.shape[0]
        k = max(Wo / a.shape[1], Ho / a.shape[0])
        bg = small.resize((max(Wo, int(a.shape[1] * k) + 2), max(Ho, int(a.shape[0] * k) + 2)),
                          Image.Resampling.BILINEAR)
        bx, by = (bg.width - Wo) // 2, (bg.height - Ho) // 2
        bg = bg.crop((bx, by, bx + Wo, by + Ho)).filter(ImageFilter.GaussianBlur(max(Wo, Ho) * 0.03))
        pad = _pad(a, pl, scale, "symmetric").astype(np.float32)
        t = np.clip(dist / (max(Wo, Ho) * 0.12), 0, 1)[..., None]
        out = pad * (1 - t) + np.asarray(bg, np.float32) * t
    else:
        pad = _pad(a, pl, scale, "symmetric" if method == "mirror" else "edge")
        out = _soften(pad, dist, 1.0 if method == "mirror" else 0.6)
    ext = Image.fromarray(np.clip(out, 0, 255).astype("uint8"))
    if scale < 1:
        ext = ext.resize(pl.out_size, Image.Resampling.LANCZOS)
    feather = max(2, int(min(rgb.size) * 0.01))
    return _feather_paste(ext, rgb, (pl.left, pl.top), feather)


def expand_ai(img: Image.Image, pl: ExpandPlan, token: str, prompt: str = "",
              progress: Optional[Callable[[str], None]] = None, opener=None, max_side: int = 1440) -> Image.Image:
    """New picture content in the margins from an online AI model (Replicate)."""
    from app.core import cloud
    if pl.empty:
        return img.copy()
    rgb = img.convert("RGB")
    scale = min(1.0, max_side / max(pl.out_size))
    # context for the model: the soft-mirror version; the mask tells it what to redraw
    rough = expand_offline(rgb, pl, "mirror")
    small = rough.resize((max(64, round(pl.out_size[0] * scale)), max(64, round(pl.out_size[1] * scale))),
                         Image.Resampling.LANCZOS)
    mask = Image.new("L", small.size, 255)
    inset = max(2, int(min(small.size) * 0.01))
    x0, y0 = round(pl.left * scale) + inset, round(pl.top * scale) + inset
    x1, y1 = round((pl.left + pl.size[0]) * scale) - inset, round((pl.top + pl.size[1]) * scale) - inset
    mask.paste(0, (x0, y0, x1, y1))
    kw = {"opener": opener} if opener is not None else {}
    out = cloud.outpaint(small, mask, token, prompt, progress, **kw)
    out = out.resize(pl.out_size, Image.Resampling.LANCZOS)
    feather = max(4, int(min(rgb.size) * 0.02))
    return _feather_paste(out, rgb, (pl.left, pl.top), feather)


def crop_fraction(design_size: Tuple[int, int], target_aspect: float) -> float:
    """How much of the design 'Fill the wall' cuts away (0–1)."""
    a = design_size[0] / design_size[1]
    return 1 - (target_aspect / a if a > target_aspect else a / target_aspect)
