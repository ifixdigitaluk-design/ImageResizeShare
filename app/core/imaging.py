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
    "TIFF": {"ext": ".tif", "pil": "TIFF", "lossy": False, "alpha": True},
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
    preview_scale: float = 1.0               # < 1: a screen-sized preview of a bigger output
    full_size: Optional[Tuple[int, int]] = None   # the real output size (pixels)
    est_bytes: Optional[int] = None          # estimated file size of the real output (previews)

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def is_preview(self) -> bool:
        return self.preview_scale < 1.0

    @property
    def out_size(self) -> Tuple[int, int]:
        """Size of the file this result stands for (the real output, also for a preview)."""
        return self.full_size or self.image.size


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
    # one copy of the picture, not up to four (a 250 MP file is 750 MB a copy)
    im = Image.open(path)
    try:
        n_frames = getattr(im, "n_frames", 1)      # before load(): counting frames moves through the file
        im.load()
        fmt = im.format or path.suffix.upper().lstrip(".")
    finally:
        if getattr(im, "fp", None) is not None:      # loaded: let the file go (Windows locks open files)
            im.fp.close()
            im.fp = None
    icc = im.info.get("icc_profile")
    dpi = im.info.get("dpi")
    ImageOps.exif_transpose(im, in_place=True)     # fixes sideways phone photos
    exif = None
    try:
        raw = im.info.get("exif")              # the real EXIF block (not a TIFF's own layout tags)
        if raw:
            ex = Image.Exif()
            ex.load(raw)
            if ex:
                ex[0x0112] = 1  # orientation already applied
                exif = ex.tobytes()
    except Exception:
        exif = None
    img = _normalise_mode(im)
    return LoadedImage(image=img, path=path, file_size=path.stat().st_size,
                       original_format=fmt, icc_profile=icc, exif=exif,
                       dpi=dpi, n_frames=n_frames)


def load_error_text(path, exc: BaseException) -> str:
    """A plain-words reason why a picture could not be opened."""
    from PIL import UnidentifiedImageError
    name = Path(str(path)).name
    if isinstance(exc, FileNotFoundError):
        return f"{name} could not be found. It may have been moved or deleted."
    if isinstance(exc, PermissionError):
        return f"{name} could not be read. It may be open in another program, or still downloading."
    if isinstance(exc, Image.DecompressionBombError):
        return f"{name} is too big to open safely (over {Image.MAX_IMAGE_PIXELS // 1_000_000} megapixels)."
    if isinstance(exc, MemoryError):
        return f"{name} is too big for this computer's memory."
    try:
        empty = Path(str(path)).stat().st_size == 0
    except OSError:
        empty = False
    if empty:
        return f"{name} is empty (0 bytes). It may not have finished copying or downloading."
    if isinstance(exc, UnidentifiedImageError):
        ext = Path(str(path)).suffix.lower()
        if ext in (".heic", ".heif") and not HEIF_OK:
            return f"{name} is an iPhone HEIC photo and HEIC support is not installed."
        return f"{name} is not a picture this app can read, or the file is damaged."
    if isinstance(exc, (OSError, SyntaxError, ValueError)):
        return f"{name} looks damaged or incomplete ({exc}). Try saving or downloading it again."
    return f"{name} could not be opened ({exc})."


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


def _unsharp(img: Image.Image, amount: int, scale: float, inplace: bool = False) -> Image.Image:
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
    return _apply_rgb(img, f, 16, inplace)


STRIP_PIXELS = 6_000_000     # big images are filtered in strips of about this size (low memory)


def _in_strips(img: Image.Image, fn: Callable[[Image.Image], Image.Image], overlap: int = 16,
               inplace: bool = False) -> Image.Image:
    """fn(img) for a local filter (reach < overlap pixels), done strip by strip so a 200 MP
    print needs a few MB of working memory instead of several GB. The result is identical to
    fn(img). With inplace=True the result is written back into img (saves one full copy;
    only for images nobody else uses)."""
    w, h = img.size
    rows = max(64, STRIP_PIXELS // max(1, w))
    if h <= rows + 2 * overlap:
        return fn(img)
    out = img if inplace else Image.new(img.mode, img.size)
    keep = None                       # original rows just above the current strip (inplace)
    y = 0
    while y < h:
        y1 = min(h, y + rows)
        b = min(h, y1 + overlap)
        if not inplace:
            a = max(0, y - overlap)
            part, top = img.crop((0, a, w, b)), y - a
        else:
            below = img.crop((0, y, w, b))
            if keep is not None:
                part = Image.new(img.mode, (w, keep.height + below.height))
                part.paste(keep, (0, 0))
                part.paste(below, (0, keep.height))
                top = keep.height
            else:
                part, top = below, 0
            keep = img.crop((0, max(0, y1 - overlap), w, y1))     # before it is overwritten
        res = fn(part)
        out.paste(res.crop((0, top, w, top + (y1 - y))), (0, y))
        y = y1
    return out


def _apply_rgb(img: Image.Image, fn: Callable[[Image.Image], Image.Image], overlap: int = 16,
               inplace: bool = False) -> Image.Image:
    """Apply a local filter to colour channels only (keep alpha untouched)."""
    if img.mode == "RGBA":
        rgb = _in_strips(img.convert("RGB"), fn, overlap, inplace=True)     # a fresh copy anyway
        rgb.putalpha(img.getchannel("A"))
        return rgb
    return _in_strips(img, fn, overlap, inplace)


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
        return _unsharp(out, amount, scale, inplace=True)

    # ---- Enlarging -------------------------------------------------------
    if method in (UPSCALE_AI_PHOTO, UPSCALE_AI_ART):
        if ai_engine is not None and ai_engine.available():
            try:
                if progress:
                    progress("AI enhancing… (this can take a few seconds)")
                big = ai_engine.upscale_to(img, (tw, th),
                                           art=(method == UPSCALE_AI_ART), progress=progress)
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
        return _unsharp(out, max(0, sharpen), scale, inplace=True) if sharpen > 0 else out

    out = _stepwise_upscale(img, (tw, th))
    amount = _auto_sharpen_amount(scale) if sharpen < 0 else sharpen
    return _unsharp(out, amount, scale, inplace=True)


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


def resize_layout(size: Tuple[int, int], rs: ResizeSettings):
    """(scaled, canvas, offset, crop_box, kept) for an edited picture of `size`: compute_layout plus
    the 'enlarging off' rule. kept = True when enlarging was refused. Used by the resize, the fast
    preview and the close-up, so all three always agree."""
    if not rs.enabled or rs.width <= 0 or rs.height <= 0:
        return size, size, (0, 0), None, False
    box = (int(rs.width), int(rs.height))
    scaled, canvas, offset, crop_box = compute_layout(size, box, rs.mode)
    kept = False
    if not rs.allow_upscale and (scaled[0] > size[0] or scaled[1] > size[1]):
        r = min(size[0] / scaled[0], size[1] / scaled[1])
        scaled = (max(1, round(scaled[0] * r)), max(1, round(scaled[1] * r)))
        if rs.mode in (MODE_FIT_INSIDE, MODE_STRETCH):
            canvas = scaled
        offset = ((canvas[0] - scaled[0]) // 2, (canvas[1] - scaled[1]) // 2)
        crop_box = None
        kept = True
    return scaled, canvas, offset, crop_box, kept


def resize_image(img: Image.Image, rs: ResizeSettings, ai_engine=None,
                 notes: Optional[list] = None, progress=None) -> Image.Image:
    if not rs.enabled or rs.width <= 0 or rs.height <= 0:
        return img
    check_output_size(int(rs.width), int(rs.height))
    scaled, canvas, offset, crop_box, kept = resize_layout(img.size, rs)
    if kept and notes is not None:
        notes.append("Enlarging is off, so the image was kept at its original size.")

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
        big = im.width * im.height > 40_000_000
        # optimize / progressive keep the whole picture in memory (about 6 bytes a pixel), which
        # very large prints cannot afford; the file is only ~5 % bigger without them
        kw.update(quality=q, optimize=not big, progressive=not big,
                  subsampling=0 if q >= 85 else 2)  # 4:4:4 for high quality
        if not big:   # optimize/progressive JPEG needs the whole stream in one buffer
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
    elif fmt == "TIFF":
        im = img if img.mode == "RGBA" and has_transparency(img) else _flatten(img)
        kw.update(compression="tiff_lzw")   # lossless, the usual choice for print shops
        im.save(buf, "TIFF", **kw)
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


PREVIEW_PIXELS = 8_000_000    # bigger outputs are previewed at about this size while editing


def preview_scale_for(src: LoadedImage, st: EditState, rs: ResizeSettings, os_: OutputSettings,
                      max_px: int = PREVIEW_PIXELS) -> float:
    """1.0, or how much smaller the editing preview is than the real output."""
    if os_.target_kb > 0:                    # the file size is the point: make it for real
        return 1.0
    _s, canvas, _o, _c, _k = resize_layout(edited_size(src.image.size, st), rs)
    px = canvas[0] * canvas[1]
    return 1.0 if px <= max_px else math.sqrt(max_px / px)


def process_preview(src: LoadedImage, st: EditState, rs: ResizeSettings, os_: OutputSettings,
                    ai_engine=None, progress=None, max_px: int = PREVIEW_PIXELS) -> ProcessResult:
    """What the editor shows while you change settings. Small outputs are made for real; a big
    print (up to 250 MP) is made at screen size, so each change takes a moment instead of many
    seconds and a few GB. Download, share and print make the real thing with process().
    The file size shown for a preview is an estimate."""
    k = preview_scale_for(src, st, rs, os_, max_px)
    if k >= 1.0:
        return process(src, st, rs, os_, ai_engine, progress)
    notes: list = []
    img = apply_edits(src.image, st)
    _s, canvas, _o, _c, kept = resize_layout(img.size, rs)
    check_output_size(*canvas)
    small = replace(rs, width=max(1, round(rs.width * k)), height=max(1, round(rs.height * k)))
    if small.upscale in (UPSCALE_AI_PHOTO, UPSCALE_AI_ART):
        small.upscale = UPSCALE_ENHANCED     # AI on the real output only (the close-up shows it)
    if kept:
        notes.append("Enlarging is off, so the image was kept at its original size.")
    out = resize_image(img, small, None, None, progress)
    if os_.fmt.upper() == "JPG" and has_transparency(out):
        notes.append("JPG has no transparency; background filled with white.")
    exif = None if os_.strip_metadata else src.exif
    data, q, final = encode_to_target(out, os_, src.icc_profile, exif, None)
    try:
        est = _estimate_bytes(src, st, small_rs_full(rs), os_, canvas)
    except Exception:                        # an estimate only: never let it stop the preview
        est = int(len(data) / (final.width / canvas[0]) ** 2)
    return ProcessResult(image=final, data=data, fmt=os_.fmt.upper(), quality_used=q, notes=notes,
                         preview_scale=final.width / canvas[0], full_size=canvas, est_bytes=est)


def small_rs_full(rs: ResizeSettings) -> ResizeSettings:
    """Settings for sample tiles: the real size, but no AI (that runs on the real output only)."""
    if rs.upscale in (UPSCALE_AI_PHOTO, UPSCALE_AI_ART):
        return replace(rs, upscale=UPSCALE_ENHANCED)
    return rs


def _estimate_bytes(src: LoadedImage, st: EditState, rs: ResizeSettings, os_: OutputSettings,
                    canvas: Tuple[int, int], grid: int = 6, tile: int = 160) -> int:
    """File size of the real output, from a grid of real-size sample tiles encoded together
    (a big enlargement compresses much better than its small preview would suggest)."""
    W, H = canvas
    t = min(tile, W // grid, H // grid)
    if t < 16:
        raise ValueError("too small to sample")
    mosaic = None
    for gy in range(grid):
        for gx in range(grid):
            x0 = int((gx + 0.5) * W / grid - t / 2)
            y0 = int((gy + 0.5) * H / grid - t / 2)
            piece = render_region(src, st, rs, (x0, y0, x0 + t, y0 + t))
            if mosaic is None:
                mosaic = Image.new(piece.mode, (t * grid, t * grid))
            if piece.mode != mosaic.mode:
                piece = piece.convert(mosaic.mode)
            mosaic.paste(piece, (gx * t, gy * t))
    data = encode(mosaic, os_, None, None, None)
    per_px = len(data) / float(mosaic.width * mosaic.height)
    return int(per_px * W * H)


def estimated_bytes(res: ProcessResult) -> int:
    """File size of the real output (exact, or estimated from a preview)."""
    if not res.is_preview:
        return res.size_bytes
    if res.est_bytes:
        return res.est_bytes
    return int(res.size_bytes / (res.preview_scale ** 2))


def render_region(src: LoadedImage, st: EditState, rs: ResizeSettings, region: Tuple[int, int, int, int],
                  ai_engine=None) -> Image.Image:
    """The real output's pixels in `region` (x0, y0, x1, y1 in output pixels), made without making
    the whole output: for the close-up of a big print while editing."""
    x0, y0, x1, y1 = (int(v) for v in region)
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    if tw * th > 6_000_000:
        raise ValueError("close-up area too big")
    ori = apply_orientation(src.image, st)
    c = clamp_crop(st.crop, ori.size)
    cx, cy = (c[0], c[1]) if c else (0, 0)
    bw, bh = (c[2], c[3]) if c else ori.size
    scaled, canvas, offset, crop_box, _kept = resize_layout((bw, bh), rs)
    sx, sy = scaled[0] / bw, scaled[1] / bh
    # background: made small and enlarged (it is plain, or blurred anyway)
    kb = min(1.0, math.sqrt(2_000_000 / max(1, canvas[0] * canvas[1])))
    small_canvas = (max(1, round(canvas[0] * kb)), max(1, round(canvas[1] * kb)))
    base = ori.crop((cx, cy, cx + bw, cy + bh)) if c else ori
    if rs.background == BG_BLUR:
        bg_small = _background(base.resize(small_canvas, Image.Resampling.BILINEAR), small_canvas, rs)
        bx, by = bg_small.width / canvas[0], bg_small.height / canvas[1]
        out = bg_small.resize((tw, th), Image.Resampling.BILINEAR,
                              box=(x0 * bx, y0 * by, min(bg_small.width, x1 * bx), min(bg_small.height, y1 * by)))
    else:
        out = _background(base, (tw, th), rs) if crop_box is None else Image.new(
            "RGBA" if base.mode == "RGBA" else "RGB", (tw, th))
    # where the region falls on the resized picture
    if crop_box:
        ix0, iy0 = x0 + crop_box[0], y0 + crop_box[1]
    else:
        ix0, iy0 = x0 - offset[0], y0 - offset[1]
    ix1, iy1 = ix0 + tw, iy0 + th
    vx0, vy0, vx1, vy1 = max(0, ix0), max(0, iy0), min(scaled[0], ix1), min(scaled[1], iy1)
    if vx1 > vx0 and vy1 > vy0:
        pad = 6                                            # source pixels of context for the filters
        u0, v0 = vx0 / sx, vy0 / sy
        u1, v1 = vx1 / sx, vy1 / sy
        pu0, pv0 = max(0, int(math.floor(u0)) - pad), max(0, int(math.floor(v0)) - pad)
        pu1, pv1 = min(bw, int(math.ceil(u1)) + pad), min(bh, int(math.ceil(v1)) + pad)
        piece = base.crop((pu0, pv0, pu1, pv1))
        big_w, big_h = max(1, round((pu1 - pu0) * sx)), max(1, round((pv1 - pv0) * sy))
        big = resample(piece, (big_w, big_h), rs.upscale, rs.sharpen, ai_engine, None)
        ox, oy = round(vx0 - pu0 * sx), round(vy0 - pv0 * sy)
        part = big.crop((ox, oy, ox + (vx1 - vx0), oy + (vy1 - vy0)))
        at = (vx0 - ix0, vy0 - iy0)
        if part.mode == "RGBA" or out.mode == "RGBA":
            out = out.convert("RGBA")
            out.alpha_composite(part.convert("RGBA"), at)
        else:
            out.paste(part, at)
    return out


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
    scaled, canvas, offset, crop_box, _kept = resize_layout((bw, bh), rs)
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
