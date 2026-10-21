"""
Image engine for Image Resize & Share.

Pure Pillow code (no Qt) so it can be unit-tested and reused by batch mode.

Quality rules used everywhere:
  * Lanczos resampling (best general-purpose filter in Pillow).
  * Enlarging is done in <=2x steps followed by size-aware sharpening
    ("Enhanced"), or with Real-ESRGAN AI super-resolution when available.
  * EXIF orientation is applied on load so photos never come out sideways.
  * ICC colour profiles are preserved so colours don't shift.
  * JPG is written with 4:4:4 chroma (no colour smearing) at high quality.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional, Tuple

from PIL import Image, ImageChops, ImageFile, ImageFilter, ImageOps

try:  # iPhone HEIC/HEIF + AVIF support
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover - optional dependency
    HEIF_OK = False

# Allow big print-size images (default limit ~89 MP triggers warnings).
Image.MAX_IMAGE_PIXELS = 400_000_000

MAX_OUTPUT_SIDE = 30000          # hard safety limit for one side
MAX_OUTPUT_PIXELS = 250_000_000  # ~250 MP

RESAMPLE = Image.Resampling.LANCZOS

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
MODE_FIT_PAD = "fit_pad"        # keep whole image, add background to fill box
MODE_FIT_INSIDE = "fit_inside"  # keep whole image, no borders (may be smaller)
MODE_FILL = "fill"              # fill the box, crop overflowing edges
MODE_STRETCH = "stretch"        # force exact size (distorts)

UPSCALE_STANDARD = "standard"   # plain Lanczos
UPSCALE_ENHANCED = "enhanced"   # stepwise Lanczos + detail sharpening
UPSCALE_AI_PHOTO = "ai_photo"   # Real-ESRGAN x4plus
UPSCALE_AI_ART = "ai_art"       # Real-ESRGAN x4plus-anime (logos, drawings, text)

BG_WHITE = "white"
BG_BLACK = "black"
BG_TRANSPARENT = "transparent"
BG_BLUR = "blur"
BG_CUSTOM = "custom"

FORMATS = {
    "JPG": {"ext": ".jpg", "pil": "JPEG", "lossy": True, "alpha": False},
    "PNG": {"ext": ".png", "pil": "PNG", "lossy": False, "alpha": True},
    "WEBP": {"ext": ".webp", "pil": "WEBP", "lossy": True, "alpha": True},
    "PDF": {"ext": ".pdf", "pil": "PDF", "lossy": True, "alpha": False},
}

UNITS = ("px", "%", "cm", "mm", "in")


# --------------------------------------------------------------------------
# Data classes
# --------------------------------------------------------------------------
@dataclass
class EditState:
    """Geometry edits applied to the source before resizing (undoable)."""
    rotation: int = 0              # 0, 90, 180, 270 (clockwise)
    flip_h: bool = False
    flip_v: bool = False
    crop: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h) in oriented coords

    def copy(self) -> "EditState":
        return replace(self)


@dataclass
class ResizeSettings:
    enabled: bool = True
    width: int = 0                 # target box in pixels (0 = keep)
    height: int = 0
    mode: str = MODE_FIT_PAD
    background: str = BG_WHITE
    custom_color: Tuple[int, int, int] = (255, 255, 255)
    upscale: str = UPSCALE_ENHANCED
    sharpen: int = -1              # -1 = auto, else 0..100
    allow_upscale: bool = True


@dataclass
class OutputSettings:
    fmt: str = "JPG"
    quality: int = 92
    webp_lossless: bool = False
    target_kb: int = 0             # 0 = off
    dpi: int = 300
    strip_metadata: bool = False
    jpg_background: Tuple[int, int, int] = (255, 255, 255)


@dataclass
class ProcessResult:
    image: Image.Image
    data: bytes
    fmt: str
    quality_used: Optional[int]
    notes: list = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        return len(self.data)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
@dataclass
class LoadedImage:
    image: Image.Image           # orientation-corrected, display-ready mode
    path: Optional[Path]
    file_size: int
    original_format: str
    icc_profile: Optional[bytes]
    exif: Optional[bytes]
    dpi: Optional[Tuple[float, float]]
    n_frames: int = 1


def supported_input_extensions() -> list[str]:
    exts = {e.lower() for e, f in Image.registered_extensions().items() if f in Image.OPEN}
    # Hide exotic formats nobody expects; keep the common ones first.
    common = [".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif", ".bmp",
              ".gif", ".tif", ".tiff", ".ico", ".jfif", ".tga"]
    return [e for e in common if e in exts]


def _normalise_mode(img: Image.Image) -> Image.Image:
    """Convert to RGB or RGBA (8-bit) while keeping transparency."""
    if img.mode in ("RGB", "RGBA"):
        return img
    if img.mode == "P":
        return img.convert("RGBA") if "transparency" in img.info else img.convert("RGB")
    if img.mode in ("LA", "PA"):
        return img.convert("RGBA")
    if img.mode == "CMYK":
        return img.convert("RGB")
    if img.mode in ("I;16", "I;16B", "I;16L", "I"):
        # 16-bit greyscale: scale down to 8-bit properly
        return img.point(lambda v: v / 256).convert("L").convert("RGB")
    if img.mode == "1" or img.mode == "L":
        return img.convert("RGB")
    return img.convert("RGBA" if "A" in img.mode else "RGB")


def load_image(path: str | Path) -> LoadedImage:
    path = Path(path)
    with Image.open(path) as im:
        im.load()
        fmt = im.format or path.suffix.upper().lstrip(".")
        n_frames = getattr(im, "n_frames", 1)
        icc = im.info.get("icc_profile")
        dpi = im.info.get("dpi")
        oriented = ImageOps.exif_transpose(im)  # fixes sideways phone photos
        exif = None
        try:
            ex = oriented.getexif()
            if ex:
                ex[0x0112] = 1  # orientation already applied
                exif = ex.tobytes()
        except Exception:
            exif = None
        img = _normalise_mode(oriented)
        img = img.copy()
    return LoadedImage(image=img, path=path, file_size=path.stat().st_size,
                       original_format=fmt, icc_profile=icc, exif=exif,
                       dpi=dpi, n_frames=n_frames)


def from_pil(img: Image.Image, name: str = "pasted") -> LoadedImage:
    return LoadedImage(image=_normalise_mode(img).copy(), path=None, file_size=0,
                       original_format="PNG", icc_profile=img.info.get("icc_profile"),
                       exif=None, dpi=None)


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------
def apply_orientation(img: Image.Image, st: EditState) -> Image.Image:
    out = img
    if st.rotation % 360:
        # PIL rotates counter-clockwise; we store clockwise degrees.
        method = {90: Image.Transpose.ROTATE_270,
                  180: Image.Transpose.ROTATE_180,
                  270: Image.Transpose.ROTATE_90}[st.rotation % 360]
        out = out.transpose(method)
    if st.flip_h:
        out = out.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if st.flip_v:
        out = out.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return out


def clamp_crop(crop, size) -> Optional[Tuple[int, int, int, int]]:
    if not crop:
        return None
    W, H = size
    x, y, w, h = (int(round(v)) for v in crop)
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = max(1, min(w, W - x))
    h = max(1, min(h, H - y))
    if (x, y, w, h) == (0, 0, W, H):
        return None
    return (x, y, w, h)


def rotate_state(st: EditState, src_size: Tuple[int, int], clockwise: bool) -> EditState:
    """Rotate what the user currently sees by 90° (crop box follows)."""
    W, H = oriented_size(src_size, st)
    new = st.copy()
    delta = 90 if clockwise else 270
    # Our order is rotate-then-flip; a single flip reverses rotation direction.
    if st.flip_h != st.flip_v:
        delta = 360 - delta
    new.rotation = (st.rotation + delta) % 360
    c = clamp_crop(st.crop, (W, H))
    if c:
        x, y, w, h = c
        new.crop = (H - y - h, x, h, w) if clockwise else (y, W - x - w, h, w)
    return new


def flip_state(st: EditState, src_size: Tuple[int, int], horizontal: bool) -> EditState:
    """Mirror what the user currently sees (crop box follows)."""
    W, H = oriented_size(src_size, st)
    new = st.copy()
    if horizontal:
        new.flip_h = not st.flip_h
    else:
        new.flip_v = not st.flip_v
    c = clamp_crop(st.crop, (W, H))
    if c:
        x, y, w, h = c
        new.crop = (W - x - w, y, w, h) if horizontal else (x, H - y - h, w, h)
    return new


def apply_edits(img: Image.Image, st: EditState) -> Image.Image:
    out = apply_orientation(img, st)
    c = clamp_crop(st.crop, out.size)
    if c:
        x, y, w, h = c
        out = out.crop((x, y, x + w, y + h))
    return out


def oriented_size(size: Tuple[int, int], st: EditState) -> Tuple[int, int]:
    w, h = size
    return (h, w) if st.rotation % 180 == 90 else (w, h)


def edited_size(size: Tuple[int, int], st: EditState) -> Tuple[int, int]:
    osz = oriented_size(size, st)
    c = clamp_crop(st.crop, osz)
    return (c[2], c[3]) if c else osz


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------
def to_pixels(value: float, unit: str, dpi: int, base_px: int) -> int:
    if unit == "px":
        px = value
    elif unit == "%":
        px = base_px * value / 100.0
    elif unit == "in":
        px = value * dpi
    elif unit == "cm":
        px = value / 2.54 * dpi
    elif unit == "mm":
        px = value / 25.4 * dpi
    else:
        raise ValueError(unit)
    return max(1, int(round(px)))


def from_pixels(px: int, unit: str, dpi: int, base_px: int) -> float:
    if unit == "px":
        return float(px)
    if unit == "%":
        return px * 100.0 / max(1, base_px)
    if unit == "in":
        return px / dpi
    if unit == "cm":
        return px / dpi * 2.54
    if unit == "mm":
        return px / dpi * 25.4
    raise ValueError(unit)


def print_size_text(w: int, h: int, dpi: int) -> str:
    return (f"{w / dpi * 2.54:.1f} × {h / dpi * 2.54:.1f} cm  "
            f"({w / dpi:.2f} × {h / dpi:.2f} in) at {dpi} DPI")


# --------------------------------------------------------------------------
# Resampling (quality core)
# --------------------------------------------------------------------------
def _auto_sharpen_amount(scale: float) -> int:
    """Sharpening strength (0..100) appropriate for a given scale factor."""
    if scale <= 0.5:
        return 25     # strong reductions lose micro-contrast; restore a bit
    if scale < 1.0:
        return 15
    if scale <= 1.05:
        return 0
    # Enlarging: more scale -> more softness to counter.
    return int(min(80, 25 + (scale - 1.0) * 20))


def _antihalo(base: Image.Image, sharp: Image.Image) -> Image.Image:
    """Clamp sharpened pixels to the local min/max of the unsharpened image.

    This keeps the crisp edge but removes the white/dark outlines ("halos")
    that ordinary sharpening creates around hair, text and logos.
    """
    lo = base.filter(ImageFilter.MinFilter(3))
    hi = base.filter(ImageFilter.MaxFilter(3))
    return ImageChops.darker(ImageChops.lighter(sharp, lo), hi)


def _unsharp(img: Image.Image, amount: int, scale: float) -> Image.Image:
    if amount <= 0:
        return img
    if scale < 1:
        radius, threshold = 0.8, 1
    else:
        radius, threshold = min(2.2, 0.6 + 0.3 * scale), 1
    percent = int(40 + amount * 1.6)           # 40..200

    def f(im: Image.Image) -> Image.Image:
        sharp = im.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold))
        return _antihalo(im, sharp) if scale > 1 else sharp
    return _apply_rgb(img, f)


def _apply_rgb(img: Image.Image, fn: Callable[[Image.Image], Image.Image]) -> Image.Image:
    """Apply a filter to colour channels only (keep alpha untouched)."""
    if img.mode == "RGBA":
        rgb = fn(img.convert("RGB"))
        rgb.putalpha(img.getchannel("A"))
        return rgb
    return fn(img)


def _stepwise_upscale(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
    """Enlarge in <=2x Lanczos steps.

    Large single-jump enlargements create ringing and blur; doing it in
    stages keeps edges cleaner.
    """
    tw, th = size
    cur = img
    while cur.width * 2 < tw and cur.height * 2 < th:
        cur = cur.resize((cur.width * 2, cur.height * 2), RESAMPLE)
    return cur.resize((tw, th), RESAMPLE)


def resample(img: Image.Image, size: Tuple[int, int], method: str = UPSCALE_ENHANCED,
             sharpen: int = -1, ai_engine=None, notes: Optional[list] = None,
             progress: Optional[Callable[[str], None]] = None) -> Image.Image:
    """High-quality resize to an exact pixel size."""
    tw, th = size
    if (tw, th) == img.size:
        return img.copy()
    scale = math.sqrt((tw * th) / float(img.width * img.height))
    enlarging = tw > img.width or th > img.height

    if not enlarging:
        out = img.resize((tw, th), RESAMPLE, reducing_gap=3.0)
        amount = _auto_sharpen_amount(scale) if sharpen < 0 else sharpen
        return _unsharp(out, amount, scale)

    # ---- Enlarging -------------------------------------------------------
    if method in (UPSCALE_AI_PHOTO, UPSCALE_AI_ART):
        if ai_engine is not None and ai_engine.available():
            try:
                if progress:
                    progress("AI enhancing… (this can take a few seconds)")
                big = ai_engine.upscale_to(img, (tw, th),
                                           art=(method == UPSCALE_AI_ART))
                out = big.resize((tw, th), RESAMPLE, reducing_gap=3.0) if big.size != (tw, th) else big
                if sharpen > 0:
                    out = _unsharp(out, sharpen // 2, 1.0)
                return out
            except Exception as exc:  # GPU missing, out of memory, ...
                if notes is not None:
                    notes.append(f"AI upscale unavailable ({exc}); used Enhanced instead.")
        elif notes is not None:
            notes.append("AI engine not found; used Enhanced upscaling instead.")
        method = UPSCALE_ENHANCED

    if method == UPSCALE_STANDARD:
        out = img.resize((tw, th), RESAMPLE)
        return _unsharp(out, max(0, sharpen), scale) if sharpen > 0 else out

    out = _stepwise_upscale(img, (tw, th))
    amount = _auto_sharpen_amount(scale) if sharpen < 0 else sharpen
    return _unsharp(out, amount, scale)


# --------------------------------------------------------------------------
# Resize with box modes
# --------------------------------------------------------------------------
def compute_layout(src: Tuple[int, int], box: Tuple[int, int], mode: str):
    """Return (scaled_size, canvas_size, offset, crop_box_in_scaled)."""
    sw, sh = src
    bw, bh = box
    if mode == MODE_STRETCH:
        return (bw, bh), (bw, bh), (0, 0), None
    rw, rh = bw / sw, bh / sh
    if mode == MODE_FILL:
        r = max(rw, rh)
        nw, nh = max(bw, round(sw * r)), max(bh, round(sh * r))
        left, top = (nw - bw) // 2, (nh - bh) // 2
        return (nw, nh), (bw, bh), (0, 0), (left, top, left + bw, top + bh)
    r = min(rw, rh)
    nw, nh = max(1, round(sw * r)), max(1, round(sh * r))
    if mode == MODE_FIT_INSIDE:
        return (nw, nh), (nw, nh), (0, 0), None
    return (nw, nh), (bw, bh), ((bw - nw) // 2, (bh - nh) // 2), None


def _background(src: Image.Image, canvas: Tuple[int, int], rs: ResizeSettings) -> Image.Image:
    if rs.background == BG_TRANSPARENT:
        return Image.new("RGBA", canvas, (0, 0, 0, 0))
    if rs.background == BG_BLUR:
        bg = ImageOps.fit(src.convert("RGB"), canvas, RESAMPLE)
        radius = max(8, int(max(canvas) / 40))
        bg = bg.filter(ImageFilter.GaussianBlur(radius))
        # Darken slightly so the photo stands out
        bg = Image.blend(bg, Image.new("RGB", canvas, (0, 0, 0)), 0.15)
        return bg.convert("RGBA") if src.mode == "RGBA" else bg
    color = {BG_WHITE: (255, 255, 255), BG_BLACK: (0, 0, 0)}.get(rs.background, rs.custom_color)
    mode = "RGBA" if src.mode == "RGBA" else "RGB"
    return Image.new(mode, canvas, color + ((255,) if mode == "RGBA" else ()))


def check_output_size(w: int, h: int) -> None:
    if w > MAX_OUTPUT_SIDE or h > MAX_OUTPUT_SIDE or w * h > MAX_OUTPUT_PIXELS:
        raise ValueError(f"Output {w}×{h} is too large (max {MAX_OUTPUT_SIDE}px per side, "
                         f"{MAX_OUTPUT_PIXELS // 1_000_000} MP).")


def resize_image(img: Image.Image, rs: ResizeSettings, ai_engine=None,
                 notes: Optional[list] = None, progress=None) -> Image.Image:
    if not rs.enabled or rs.width <= 0 or rs.height <= 0:
        return img
    box = (int(rs.width), int(rs.height))
    check_output_size(*box)
    scaled, canvas, offset, crop_box = compute_layout(img.size, box, rs.mode)
    if not rs.allow_upscale and (scaled[0] > img.width or scaled[1] > img.height):
        r = min(img.width / scaled[0], img.height / scaled[1])
        scaled = (max(1, round(scaled[0] * r)), max(1, round(scaled[1] * r)))
        if notes is not None:
            notes.append("Enlarging is off, so the image was kept at its original size.")
        if rs.mode in (MODE_FIT_INSIDE, MODE_STRETCH):
            canvas = scaled
        offset = ((canvas[0] - scaled[0]) // 2, (canvas[1] - scaled[1]) // 2)
        crop_box = None

    out = resample(img, scaled, rs.upscale, rs.sharpen, ai_engine, notes, progress)
    if crop_box:
        out = out.crop(crop_box)
    if out.size != canvas:
        bg = _background(img, canvas, rs)
        if bg.mode == "RGBA" and out.mode != "RGBA":
            out = out.convert("RGBA")
        if out.mode == "RGBA":
            if bg.mode != "RGBA":
                bg = bg.convert("RGBA")
            bg.alpha_composite(out, offset)
        else:
            bg.paste(out, offset)
        out = bg
    return out


# --------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------
def _flatten(img: Image.Image, color=(255, 255, 255)) -> Image.Image:
    if img.mode != "RGBA":
        return img.convert("RGB") if img.mode != "RGB" else img
    bg = Image.new("RGB", img.size, color)
    bg.paste(img, mask=img.getchannel("A"))
    return bg


def has_transparency(img: Image.Image) -> bool:
    if img.mode != "RGBA":
        return False
    lo, _ = img.getchannel("A").getextrema()
    return lo < 255


def encode(img: Image.Image, os_: OutputSettings, quality: Optional[int] = None,
           icc: Optional[bytes] = None, exif: Optional[bytes] = None) -> bytes:
    fmt = os_.fmt.upper()
    q = int(quality if quality is not None else os_.quality)
    buf = io.BytesIO()
    kw: dict = {"dpi": (os_.dpi, os_.dpi)}
    if icc:
        kw["icc_profile"] = icc
    if exif and not os_.strip_metadata and fmt in ("JPG", "WEBP", "PNG"):
        kw["exif"] = exif

    if fmt == "JPG":
        im = _flatten(img, os_.jpg_background)
        kw.update(quality=q, optimize=True, progressive=True,
                  subsampling=0 if q >= 85 else 2)  # 4:4:4 for high quality
        # optimize/progressive JPEG needs the whole stream in one buffer
        ImageFile.MAXBLOCK = max(ImageFile.MAXBLOCK, im.width * im.height * 3 + (1 << 20))
        im.save(buf, "JPEG", **kw)
    elif fmt == "PNG":
        im = img if img.mode == "RGBA" and has_transparency(img) else _flatten(img)
        kw.update(compress_level=6)
        im.save(buf, "PNG", **kw)
    elif fmt == "WEBP":
        im = img if has_transparency(img) else _flatten(img)
        if os_.webp_lossless:
            kw.update(lossless=True, quality=100, method=4, exact=True)
        else:
            kw.update(quality=q, method=6)
        kw.pop("dpi", None)
        im.save(buf, "WEBP", **kw)
    elif fmt == "PDF":
        im = _flatten(img, os_.jpg_background)
        kw.pop("dpi", None)
        kw.pop("exif", None)
        kw.update(resolution=float(os_.dpi), quality=q)
        im.save(buf, "PDF", **kw)
    else:
        raise ValueError(f"Unsupported format {fmt}")
    return buf.getvalue()


def encode_to_target(img: Image.Image, os_: OutputSettings, icc=None, exif=None,
                     notes: Optional[list] = None) -> Tuple[bytes, Optional[int], Image.Image]:
    """Encode; if a target size is set, find the highest quality that fits.

    Returns (data, quality_used, image_actually_encoded). If even quality 35
    is too big the image is shrunk gradually (and a note is added).
    """
    fmt = os_.fmt.upper()
    lossy = FORMATS[fmt]["lossy"] and not (fmt == "WEBP" and os_.webp_lossless)
    if os_.target_kb <= 0 or not lossy:
        if os_.target_kb > 0 and notes is not None:
            notes.append(f"Target file size works with JPG or lossy WEBP, not {fmt}.")
        return encode(img, os_, None, icc, exif), (os_.quality if lossy else None), img

    limit = os_.target_kb * 1024
    work = img
    for _shrink in range(12):
        lo, hi, best = 35, min(98, max(os_.quality, 35)), None
        data_hi = encode(work, os_, hi, icc, exif)
        if len(data_hi) <= limit:
            return data_hi, hi, work
        while lo <= hi:
            mid = (lo + hi) // 2
            data = encode(work, os_, mid, icc, exif)
            if len(data) <= limit:
                best = (data, mid)
                lo = mid + 1
            else:
                hi = mid - 1
        if best:
            if work is not img and notes is not None:
                notes.append(f"Reduced to {work.width}×{work.height} px to reach "
                             f"{os_.target_kb} KB.")
            return best[0], best[1], work
        nw, nh = max(1, int(work.width * 0.9)), max(1, int(work.height * 0.9))
        work = img.resize((nw, nh), RESAMPLE, reducing_gap=3.0)
    if notes is not None:
        notes.append("Could not reach the target file size.")
    return encode(work, os_, 35, icc, exif), 35, work


# --------------------------------------------------------------------------
# Full pipeline
# --------------------------------------------------------------------------
def process(src: LoadedImage, st: EditState, rs: ResizeSettings, os_: OutputSettings,
            ai_engine=None, progress=None) -> ProcessResult:
    notes: list = []
    img = apply_edits(src.image, st)
    img = resize_image(img, rs, ai_engine, notes, progress)
    if os_.fmt.upper() == "JPG" and has_transparency(img):
        notes.append("JPG has no transparency; background filled with white.")
    exif = None if os_.strip_metadata else src.exif
    data, q, final = encode_to_target(img, os_, src.icc_profile, exif, notes)
    return ProcessResult(image=final, data=data, fmt=os_.fmt.upper(), quality_used=q, notes=notes)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    i = 1
    while True:
        p = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not p.exists():
            return p
        i += 1


def auto_filename(src_name: str, w: int, h: int, fmt: str) -> str:
    stem = Path(src_name).stem if src_name else "image"
    return f"{stem}_{w}x{h}{FORMATS[fmt.upper()]['ext']}"


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


# --------------------------------------------------------------------------
# Coordinate mapping (used by the close-up / loupe view)
# --------------------------------------------------------------------------
def _layout_for(src: LoadedImage, st: EditState, rs: ResizeSettings, result_size):
    osz = oriented_size(src.image.size, st)
    c = clamp_crop(st.crop, osz)
    cx, cy = (c[0], c[1]) if c else (0, 0)
    bw, bh = (c[2], c[3]) if c else osz
    if rs.enabled and rs.width > 0 and rs.height > 0:
        scaled, canvas, offset, crop_box = compute_layout((bw, bh), (rs.width, rs.height), rs.mode)
    else:
        scaled, canvas, offset, crop_box = (bw, bh), (bw, bh), (0, 0), None
    f = result_size[0] / max(1, canvas[0])
    return (cx, cy), (bw, bh), scaled, offset, crop_box, f


def result_to_source(pt, src: LoadedImage, st: EditState, rs: ResizeSettings, result_size):
    """Map a point in the result image to the oriented (uncropped) source.

    Returns (x, y, k) where k = result pixels per source pixel.
    """
    (cx, cy), (bw, bh), scaled, offset, crop_box, f = _layout_for(src, st, rs, result_size)
    x, y = pt[0] / f, pt[1] / f
    if crop_box:
        x, y = x + crop_box[0], y + crop_box[1]
    else:
        x, y = x - offset[0], y - offset[1]
    sx, sy = scaled[0] / bw, scaled[1] / bh
    return (cx + x / sx, cy + y / sy, f * sx)


def source_to_result(pt, src: LoadedImage, st: EditState, rs: ResizeSettings, result_size):
    (cx, cy), (bw, bh), scaled, offset, crop_box, f = _layout_for(src, st, rs, result_size)
    sx, sy = scaled[0] / bw, scaled[1] / bh
    x, y = (pt[0] - cx) * sx, (pt[1] - cy) * sy
    if crop_box:
        x, y = x - crop_box[0], y - crop_box[1]
    else:
        x, y = x + offset[0], y + offset[1]
    return (x * f, y * f)
