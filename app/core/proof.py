"""
Customer proof sheet ("preview with info").

Renders a shareable preview image like a print-shop proof:

  ┌──────────────┬──────────────┬─────────────────────────────────────────┐
  │(Width)X(Height)│ (Area)      │ NOTE:-                                  │
  │ 125"x 104"    │ 90.28 Sq.Ft │ THERE MIGHT BE SLIGHT VARIATION …        │
  ├──────────────┴──────────────┴─────────────────────────────────────────┤
  │  ┌───────────────────── white frame ─────────────────────────────┐    │
  │  │                     design (exact print shape)    [close-up]  │    │
  │  └───────────────────────────────────────────────────────────────┘    │
  │                        footer (shop name / phone)                     │
  └───────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

DEFAULT_NOTE = [
    "THERE MIGHT BE SLIGHT VARIATION IN COLORS IN ACTUAL PRINT.",
    "PLEASE CHECK SIZE & DESIGN CAREFULLY BEFORE PLACING THE ORDER.",
]

SQIN_PER_SQFT = 144.0
SQM_PER_SQIN = 0.00064516


@dataclass
class ProofSettings:
    width_in: float = 0.0
    height_in: float = 0.0
    unit: str = "in"                 # "in", "ft", "cm" for the size label
    show_area: bool = True
    area_unit: str = "sqft"          # "sqft" or "sqm"
    note_title: str = "NOTE:-"
    note_lines: list = field(default_factory=lambda: list(DEFAULT_NOTE))
    fill: bool = True                # True: trim to print shape, False: fit with white
    closeup: bool = False
    closeup_center: Tuple[float, float] = (0.5, 0.5)   # relative position in the design
    closeup_fraction: float = 0.16   # part of the design width shown in the close-up
    watermark: str = ""
    footer: str = ""
    width_px: int = 1800             # width of the proof image


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
def _font_dirs() -> list[Path]:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return [base / "assets" / "fonts"]


_font_cache: dict = {}


def get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    key = (max(6, int(size)), bold)
    if key in _font_cache:
        return _font_cache[key]
    names = (["LiberationSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"]
             if bold else ["LiberationSans-Regular.ttf", "arial.ttf", "Arial.ttf", "DejaVuSans.ttf"])
    candidates = []
    for d in _font_dirs():
        candidates += [d / n for n in names]
    candidates += [Path("C:/Windows/Fonts") / n for n in names]
    font = None
    for c in candidates:
        try:
            if c.is_file():
                font = ImageFont.truetype(str(c), key[0])
                break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default(key[0])
    _font_cache[key] = font
    return font


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------
def fmt_num(v: float, decimals: int = 2) -> str:
    s = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
    return s if s else "0"


def size_label(width_in: float, height_in: float, unit: str = "in") -> str:
    if unit == "cm":
        return f"{fmt_num(width_in * 2.54, 1)} x {fmt_num(height_in * 2.54, 1)} cm"
    if unit == "ft":
        def ft(v):
            f = int(v // 12)
            i = v - f * 12
            if round(i, 1) >= 12:
                f, i = f + 1, 0.0
            return f"{f}'{fmt_num(i, 1)}\u201d" if i >= 0.05 else f"{f}'"
        return f"{ft(width_in)} x {ft(height_in)}"
    return f"{fmt_num(width_in)}\u201dx {fmt_num(height_in)}\u201d"


def area_value(width_in: float, height_in: float, unit: str = "sqft") -> float:
    sq_in = width_in * height_in
    return sq_in * SQM_PER_SQIN if unit == "sqm" else sq_in / SQIN_PER_SQFT


def area_label(width_in: float, height_in: float, unit: str = "sqft") -> str:
    v = area_value(width_in, height_in, unit)
    return f"{v:.2f} Sq.M" if unit == "sqm" else f"{v:.2f} Sq.Ft"


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    l, _t, r, _b = draw.textbbox((0, 0), text, font=font)
    return r - l


def _fit_font(draw, lines, max_w, size, bold=True, min_size=8):
    size = int(size)
    while size > min_size:
        f = get_font(size, bold)
        if all(_text_w(draw, ln, f) <= max_w for ln in lines if ln):
            return f
        size -= 1
    return get_font(min_size, bold)


def _draw_text_v(draw, xy, text, font, fill):
    """Draw text with its top at y (ignoring the font's internal ascent gap)."""
    x, y = xy
    _l, t, _r, _b = draw.textbbox((0, 0), text, font=font)
    draw.text((x, y - t), text, font=font, fill=fill)


def _text_h(draw, text, font) -> int:
    _l, t, _r, b = draw.textbbox((0, 0), text or "Ag", font=font)
    return b - t


# --------------------------------------------------------------------------
# Renderer
# --------------------------------------------------------------------------
BG = (89, 89, 89)
BOX = (232, 232, 232)
LABEL_GREY = (140, 140, 140)
WHITE = (255, 255, 255)
BLACK = (10, 10, 10)
ACCENT = (26, 115, 232)


def design_shape_px(design_w: int, ps: ProofSettings) -> Tuple[int, int]:
    ratio = ps.height_in / ps.width_in if ps.width_in > 0 and ps.height_in > 0 else 1.0
    return design_w, max(1, round(design_w * ratio))


def closeup_box(src_size: Tuple[int, int], ps: ProofSettings) -> Tuple[int, int, int, int]:
    """Square region of the (print-shaped) design shown in the close-up."""
    W, H = src_size
    side = max(16, int(min(W, H, W * ps.closeup_fraction / 0.8)))
    side = min(side, W, H)
    cx, cy = ps.closeup_center
    x = int(round(cx * W - side / 2))
    y = int(round(cy * H - side / 2))
    x = max(0, min(W - side, x))
    y = max(0, min(H - side, y))
    return (x, y, x + side, y + side)


def _pad_to(img: Image.Image, size, max_px: float = 60e6) -> Image.Image:
    """ImageOps.pad, but an extreme print shape (e.g. 1 : 500) never makes a gigantic picture:
    the design is made smaller first so the padded result stays within max_px."""
    w, h = size
    if w * h > max_px:
        k = (max_px / (w * h)) ** 0.5
        img = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.Resampling.LANCZOS)
        w, h = max(1, round(w * k)), max(1, round(h * k))
    return ImageOps.pad(img, (max(w, 1), max(h, 1)), color=(255, 255, 255))


def shape_design(img: Image.Image, ps: ProofSettings) -> Image.Image:
    """Full-resolution design trimmed (or padded) to the print shape."""
    img = img.convert("RGB")
    if ps.width_in <= 0 or ps.height_in <= 0:
        return img
    r = ps.width_in / ps.height_in
    if abs(img.width / img.height - r) < 0.002:
        return img
    if ps.fill:
        if img.width / img.height > r:
            w = max(1, round(img.height * r))
            x = (img.width - w) // 2
            return img.crop((x, 0, x + w, img.height))
        h = max(1, round(img.width / r))
        y = (img.height - h) // 2
        return img.crop((0, y, img.width, y + h))
    if img.width / img.height > r:
        size = (img.width, max(1, round(img.width / r)))
    else:
        size = (max(1, round(img.height * r)), img.height)
    return _pad_to(img, size)


def render_proof(img: Image.Image, ps: ProofSettings) -> Image.Image:
    W = int(ps.width_px)
    s = W / 955.0                          # proportions follow the reference proof
    full = shape_design(img, ps)

    # ---------- measure header ----------
    tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    pad = int(10 * s)
    f_small = get_font(int(15 * s))
    f_big = get_font(int(29 * s))
    size_txt = size_label(ps.width_in, ps.height_in, ps.unit)
    boxes = [("(Width)X(Height)", size_txt)]
    if ps.show_area:
        boxes.append(("(Area)", area_label(ps.width_in, ps.height_in, ps.area_unit)))
    box_w = [max(_text_w(tmp, a, f_small), _text_w(tmp, b, f_big)) + 2 * pad for a, b in boxes]
    header_h = int(70 * s)

    margin = int(10 * s)
    frame = int(18 * s)
    footer_h = int(40 * s) if ps.footer.strip() else 0
    design_w = W - 2 * (margin + frame)
    dw, dh = design_shape_px(design_w, ps)
    x_in = 0
    if dh > 4 * design_w:              # a very tall print: show it narrower so the page stays sensible
        dw, dh = max(1, round(design_w * 4 * design_w / dh)), 4 * design_w
        x_in = (design_w - dw) // 2
    H = header_h + margin + 2 * frame + dh + margin + footer_h

    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    # ---------- header boxes ----------
    x = int(27 * s)
    for (lab, val), bw in zip(boxes, box_w):
        d.rectangle([x, 0, x + bw, header_h - int(2 * s)], fill=BOX)
        _draw_text_v(d, (x + (bw - _text_w(d, lab, f_small)) // 2, int(7 * s)), lab, f_small, LABEL_GREY)
        _draw_text_v(d, (x + (bw - _text_w(d, val, f_big)) // 2, int(32 * s)), val, f_big, BLACK)
        x += bw + int(6 * s)

    # ---------- note ----------
    nx = x + int(4 * s)
    max_w = W - nx - int(12 * s)
    lines = [ln.strip() for ln in ps.note_lines if ln.strip()][:3]
    if ps.note_title.strip() or lines:
        f_title = _fit_font(d, [ps.note_title], max_w, 22 * s)
        f_note = _fit_font(d, lines or [""], max_w, (15 if len(lines) <= 2 else 12) * s)
        y = int(5 * s)
        if ps.note_title.strip():
            _draw_text_v(d, (nx, y), ps.note_title, f_title, WHITE)
            y += _text_h(d, ps.note_title, f_title) + int(6 * s)
        avail = header_h - y - int(4 * s)
        lh = _text_h(d, "AG", f_note)
        gap = max(int(3 * s), (avail - lh * max(1, len(lines))) // max(1, len(lines)))
        gap = min(gap, int(7 * s))
        for ln in lines:
            _draw_text_v(d, (nx, y), ln, f_note, WHITE)
            y += lh + gap

    # ---------- white frame + design ----------
    fy = header_h + margin
    d.rectangle([margin, fy, W - margin - 1, fy + 2 * frame + dh - 1], fill=WHITE)
    shown = full.resize((dw, dh), Image.Resampling.LANCZOS, reducing_gap=3.0)
    if ps.watermark.strip():
        shown = _watermark(shown, ps.watermark.strip(), s)
    ox, oy = margin + frame + x_in, fy + frame
    canvas.paste(shown, (ox, oy))

    # ---------- close-up inset ----------
    if ps.closeup:
        bx0, by0, bx1, by1 = closeup_box(full.size, ps)
        k = dw / full.width
        rect = [ox + bx0 * k, oy + by0 * k, ox + bx1 * k, oy + by1 * k]
        lw = max(2, int(2.5 * s))
        d.rectangle(rect, outline=ACCENT, width=lw)
        inset = int(min(dw, dh) * 0.42)
        detail = full.crop((bx0, by0, bx1, by1)).resize((inset, inset), Image.Resampling.LANCZOS)
        border = max(3, int(4 * s))
        ix = ox + dw - inset - int(14 * s)
        iy = oy + dh - inset - int(14 * s)
        # move the inset to the left if it would cover the marked area
        if rect[2] > ix - border and rect[3] > iy - border:
            ix = ox + int(14 * s)
        # connector line (drawn first so the inset sits on top of it)
        d.line([((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2),
                (ix + inset / 2, iy + inset / 2)], fill=ACCENT, width=max(1, lw // 2))
        d.rectangle(rect, outline=ACCENT, width=lw)
        d.rectangle([ix - border, iy - border, ix + inset + border - 1, iy + inset + border - 1],
                    fill=WHITE)
        canvas.paste(detail, (ix, iy))
        zoom = inset / max(1.0, (bx1 - bx0) * k)
        tag = f"CLOSE-UP  {zoom:.1f}x"
        f_tag = get_font(int(13 * s))
        tw = _text_w(d, tag, f_tag) + int(14 * s)
        th = _text_h(d, tag, f_tag) + int(10 * s)
        d.rectangle([ix, iy, ix + tw, iy + th], fill=ACCENT)
        _draw_text_v(d, (ix + int(7 * s), iy + int(5 * s)), tag, f_tag, WHITE)

    canvas.info["design_box"] = (ox, oy, dw, dh)

    # ---------- footer ----------
    if footer_h:
        f_foot = _fit_font(d, [ps.footer], W - 4 * margin, 17 * s)
        ft = ps.footer.strip()
        fy2 = H - footer_h + (footer_h - _text_h(d, ft, f_foot)) // 2 - margin // 2
        _draw_text_v(d, ((W - _text_w(d, ft, f_foot)) // 2, fy2), ft, f_foot, WHITE)
    return canvas


def _watermark(img: Image.Image, text: str, s: float) -> Image.Image:
    """Repeated diagonal text. One small rotated stamp is placed many times (a full-size rotated layer
    as big as the picture's diagonal took seconds and GBs for a big or tall proof)."""
    base = img.convert("RGBA")
    f = get_font(int(34 * s))
    tmp = ImageDraw.Draw(base)
    tw = _text_w(tmp, text, f) + int(120 * s)
    th = _text_h(tmp, text, f) + int(110 * s)
    # the stamp: text + soft shadow, as before, then turned 30° like the old layer
    sw, sh = _text_w(tmp, text, f) + 8, _text_h(tmp, text, f) + 12
    stamp = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.text((0, 0), text, font=f, fill=(255, 255, 255, 95))
    sd.text((2, 2), text, font=f, fill=(0, 0, 0, 40))       # on top, as before: the embossed look
    stamp = stamp.rotate(30, resample=Image.Resampling.BICUBIC, expand=True)
    W, H = base.size
    cx, cy = W / 2, H / 2
    diag = math.hypot(W, H) + tw
    c, si = math.cos(math.radians(30)), math.sin(math.radians(30))
    half = diag / 2
    rows = range(int(-half), int(half) + th, th)
    for row, y in enumerate(rows):
        off = (row % 2) * tw // 2
        for x in range(int(-half) - tw, int(half) + tw, tw):
            # centre of this text in the unrotated grid, turned 30° anticlockwise about the picture centre
            dx, dy = x + off + sw / 2, y + sh / 2
            px = cx + dx * c + dy * si
            py = cy - dx * si + dy * c
            ox, oy = int(px - stamp.width / 2), int(py - stamp.height / 2)
            if ox >= W or oy >= H or ox + stamp.width <= 0 or oy + stamp.height <= 0:
                continue
            base.alpha_composite(stamp, (max(0, ox), max(0, oy)),
                                 (max(0, -ox), max(0, -oy)))
    return base.convert("RGB")


def proof_filename(src_name: Optional[str], ps: ProofSettings, ext: str) -> str:
    stem = Path(src_name).stem if src_name else "design"
    return f"{stem}_proof_{fmt_num(ps.width_in, 1)}x{fmt_num(ps.height_in, 1)}in{ext}"
