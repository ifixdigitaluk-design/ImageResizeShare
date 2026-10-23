"""
AI Upscale studio engine (Lupa-style modes and presets).

Modes
  * High Fidelity  – sharp and true to the original (Real-ESRGAN photo model)
  * Balanced       – a little extra clarity, still natural
  * Creative Detail – extra micro-contrast and fine texture for a crisp, rich look
  * Illustration & Anime – clean lines and flat colours (Real-ESRGAN anime model)

All modes run offline. With the AI engine present (any Vulkan GPU) the
enlargement is done by Real-ESRGAN; otherwise the "Enhanced" Lanczos +
anti-halo sharpening path is used and a note explains it.

Unlike cloud upscalers (Lupa, Magnific), nothing here invents new objects:
"Creative Detail" strengthens texture that is already in the picture.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, Optional, Tuple

from PIL import Image, ImageChops, ImageFilter

from app.core import imaging as im

MODE_FIDELITY = "fidelity"
MODE_BALANCED = "balanced"
MODE_CREATIVE = "creative"
MODE_ART = "art"

MODES = {
    MODE_FIDELITY: ("High Fidelity", "Sharp and true to the original. Best for photos."),
    MODE_BALANCED: ("Balanced", "Natural look with a little extra clarity."),
    MODE_CREATIVE: ("Creative Detail", "Richer texture and micro-detail. Nature, stone, fabric."),
    MODE_ART: ("Illustration & Anime", "Clean lines and flat colours. Art, patterns, logos."),
}

FACTORS = (2.0, 3.0, 4.0, 8.0, 16.0)


@dataclass
class UpscaleSettings:
    mode: str = MODE_FIDELITY
    factor: float = 4.0
    target: Optional[Tuple[int, int]] = None   # exact output size (fit print size); overrides factor
    detail: int = 35      # 0..100 sharpening / clarity
    denoise: int = 15     # 0..100 clean-up of JPEG noise before enlarging
    texture: int = 0      # 0..100 fine grain / micro-texture after enlarging

    def copy(self) -> "UpscaleSettings":
        return replace(self)


# (name, settings) – one-click presets like Lupa's
PRESETS = [
    ("Portrait", dict(mode=MODE_FIDELITY, detail=25, denoise=35, texture=0)),
    ("Illustration", dict(mode=MODE_ART, detail=35, denoise=20, texture=0)),
    ("Nature", dict(mode=MODE_CREATIVE, detail=50, denoise=10, texture=30)),
    ("Anime", dict(mode=MODE_ART, detail=20, denoise=30, texture=0)),
    ("Product", dict(mode=MODE_FIDELITY, detail=45, denoise=15, texture=0)),
    ("Wallpaper", dict(mode=MODE_BALANCED, detail=45, denoise=15, texture=15)),
    ("Text & Logo", dict(mode=MODE_ART, detail=60, denoise=10, texture=0)),
]


def apply_preset(us: UpscaleSettings, name: str) -> UpscaleSettings:
    for n, vals in PRESETS:
        if n == name:
            return replace(us, **vals)
    raise KeyError(name)


def target_size(src_size: Tuple[int, int], us: UpscaleSettings) -> Tuple[int, int]:
    if us.target:
        return max(1, int(us.target[0])), max(1, int(us.target[1]))
    w, h = src_size
    return max(1, round(w * us.factor)), max(1, round(h * us.factor))


def size_for_print(src_size: Tuple[int, int], width_in: float, height_in: float, dpi: int,
                   keep_ratio: bool = True) -> Tuple[int, int]:
    """Pixels needed for a print size at a DPI (keeps the picture's shape)."""
    w = max(1, round(width_in * dpi))
    h = max(1, round(height_in * dpi))
    if keep_ratio:
        sw, sh = src_size
        h = max(1, round(w * sh / sw))
    return w, h


def check_target(size: Tuple[int, int]) -> Optional[str]:
    """None when fine, otherwise a friendly message."""
    w, h = size
    if w > im.MAX_OUTPUT_SIDE or h > im.MAX_OUTPUT_SIDE or w * h > im.MAX_OUTPUT_PIXELS:
        return (f"{w:,} × {h:,} px is above the limit ({im.MAX_OUTPUT_SIDE:,} px per side, "
                f"{im.MAX_OUTPUT_PIXELS // 1_000_000} MP). Choose a smaller factor, or for wallpaper "
                "use 100–150 DPI – murals are seen from a distance.")
    return None


# --------------------------------------------------------------------------
def _denoise(img: Image.Image, amount: int) -> Image.Image:
    if amount <= 0:
        return img
    k = 0.7 * amount / 100.0

    def f(rgb: Image.Image) -> Image.Image:
        clean = rgb.filter(ImageFilter.MedianFilter(3))
        if amount > 60:
            clean = clean.filter(ImageFilter.SMOOTH)
        return Image.blend(rgb, clean, k)
    return im._apply_rgb(img, f)


def _detail(img: Image.Image, amount: int, scale: float, ai: bool) -> Image.Image:
    if amount <= 0:
        return img
    radius = (0.7 + 0.25 * min(scale, 4)) if not ai else 0.9
    percent = int(30 + amount * 1.5)

    def f(rgb: Image.Image) -> Image.Image:
        sharp = rgb.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=1))
        return im._antihalo(rgb, sharp)
    return im._apply_rgb(img, f)


def _micro_contrast(img: Image.Image, strength: float) -> Image.Image:
    """Local contrast ("clarity") – makes texture pop without halos at edges."""
    if strength <= 0:
        return img
    radius = max(4.0, min(img.size) / 220.0)

    def f(rgb: Image.Image) -> Image.Image:
        return rgb.filter(ImageFilter.UnsharpMask(radius=radius, percent=int(strength), threshold=2))
    return im._apply_rgb(img, f, overlap=int(radius * 3.5) + 8)


def _texture(img: Image.Image, amount: int) -> Image.Image:
    """Fine luminance grain, the way print designers add 'tooth' to big enlargements."""
    if amount <= 0:
        return img
    sigma = 1.5 + 6.5 * amount / 100.0

    def f(rgb: Image.Image) -> Image.Image:
        noise = Image.effect_noise(rgb.size, sigma).filter(ImageFilter.GaussianBlur(0.45))
        n3 = Image.merge("RGB", (noise, noise, noise))
        return ImageChops.add(rgb, n3, scale=1.0, offset=-128)
    return im._apply_rgb(img, f)


def upscale(img: Image.Image, us: UpscaleSettings, ai_engine=None, notes: Optional[list] = None,
            progress: Optional[Callable[[str], None]] = None) -> Image.Image:
    """Enlarge ``img`` with the chosen mode and fine-tune settings."""
    tw, th = target_size(img.size, us)
    msg = check_target((tw, th))
    if msg:
        raise ValueError(msg)
    scale = math.sqrt((tw * th) / float(img.width * img.height))
    work = _denoise(img, us.denoise)

    used_ai = False
    if scale > 1.0 and ai_engine is not None and ai_engine.available():
        try:
            if progress:
                progress("AI upscaling… large images can take a minute")
            big = ai_engine.upscale_to(work, (tw, th), art=(us.mode == MODE_ART))
            out = big if big.size == (tw, th) else big.resize((tw, th), im.RESAMPLE, reducing_gap=3.0)
            used_ai = True
        except Exception as exc:
            if notes is not None:
                notes.append(f"AI engine could not run ({exc}); used Enhanced instead.")
            out = None
    else:
        out = None
        if scale > 1.0 and notes is not None:
            notes.append("AI engine not available on this PC – used Enhanced upscaling "
                         "(sharp, but rebuilds less detail).")
    if out is None and scale > 1.0:
        # Enhanced: stepwise Lanczos, then anti-halo sharpening scaled by "Detail"
        # (50 = the standard amount for this enlargement, 0 = none, 100 = strong).
        if progress:
            progress("Upscaling…")
        out = im._stepwise_upscale(work, (tw, th))
        amount = min(100, int(round(im._auto_sharpen_amount(scale) * us.detail / 50.0)))
        out = im._unsharp(out, amount, scale, inplace=True)
    else:
        if out is None:
            out = work.resize((tw, th), im.RESAMPLE, reducing_gap=3.0)
        if progress:
            progress("Finishing details…")
        out = _detail(out, us.detail, scale, used_ai)
    if us.mode == MODE_CREATIVE:
        out = _micro_contrast(out, 35 + us.detail * 0.3)
    elif us.mode == MODE_BALANCED:
        out = _micro_contrast(out, 15)
    out = _texture(out, us.texture)
    return out


def describe(us: UpscaleSettings, src_size: Tuple[int, int]) -> str:
    tw, th = target_size(src_size, us)
    f = tw / src_size[0]
    return f"{MODES[us.mode][0]} · {f:.1f}× · {tw:,} × {th:,} px"
