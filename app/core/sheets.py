"""
Print size helpers and the two customer preview sheets.

* Download Preview: print size and area boxes, the design drawn with
  dimension arrows ("4 inches (10.16 cm / 102 mm)") and the colour / size
  warning underneath.
* Closeup Print Preview: the design with a marked spot, a magnified inset of
  that spot ("Zoom: 200%") and the print size / area underneath.

Everything here is plain Pillow so it can be tested without Qt. The on-screen
dialogs use the same text helpers and the same close-up geometry, so what the
customer receives matches what is shown in the app.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageOps

from app.core.proof import _draw_text_v, _fit_font, _text_h, _text_w, _watermark, get_font

CM_PER_IN = 2.54
MM_PER_IN = 25.4
IN_PER_FT = 12.0
SQIN_PER_SQFT = 144.0
SQM_PER_SQIN = 0.00064516

UNITS = ("in", "cm", "mm", "ft")
UNIT_NAMES = {"in": "inches", "cm": "cm", "mm": "mm", "ft": "feet"}
UNIT_DECIMALS = {"in": 2, "cm": 2, "mm": 0, "ft": 2}
_OTHERS = {"in": ("cm", "mm"), "cm": ("in", "mm"), "mm": ("in", "cm"), "ft": ("in", "cm")}

DEFAULT_WARNING = [
    "THERE MIGHT BE SLIGHT VARIATIONS IN COLORS IN ACTUAL PRINT.",
    "PLEASE CHECK SIZE & DESIGN CAREFULLY BEFORE PLACING THE ORDER.",
]
ZOOM_LEVELS = (1.5, 2.0, 3.0, 4.0, 6.0, 8.0)


# --------------------------------------------------------------------------
# Units and labels
# --------------------------------------------------------------------------
def to_unit(inches: float, unit: str) -> float:
    if unit == "in":
        return inches
    if unit == "cm":
        return inches * CM_PER_IN
    if unit == "mm":
        return inches * MM_PER_IN
    if unit == "ft":
        return inches / IN_PER_FT
    raise ValueError(unit)


def from_unit(value: float, unit: str) -> float:
    if unit == "in":
        return value
    if unit == "cm":
        return value / CM_PER_IN
    if unit == "mm":
        return value / MM_PER_IN
    if unit == "ft":
        return value * IN_PER_FT
    raise ValueError(unit)


def _fixed(v: float, decimals: int) -> str:
    return f"{v:.{decimals}f}"


def _trim(v: float, decimals: int = 2) -> str:
    s = f"{v:.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def fmt_len(inches: float, unit: str) -> str:
    """'4.00 in', '10.16 cm', '102 mm', '0.33 ft'."""
    return f"{_fixed(to_unit(inches, unit), UNIT_DECIMALS[unit])} {unit}"


def size_text(w_in: float, h_in: float, unit: str = "in") -> str:
    """'4.00 in × 3.00 in'."""
    return f"{fmt_len(w_in, unit)} × {fmt_len(h_in, unit)}"


def size_alt_text(w_in: float, h_in: float, unit: str = "in", first_only: bool = False) -> str:
    """'(10.16 cm × 7.62 cm / 102 mm × 76 mm)' – the size in the other units."""
    others = _OTHERS[unit][:1] if first_only else _OTHERS[unit]
    return "(" + " / ".join(size_text(w_in, h_in, u) for u in others) + ")"


def unit_word(value: float, unit: str) -> str:
    if unit == "in":
        return "inch" if abs(value - 1) < 1e-9 else "inches"
    if unit == "ft":
        return "foot" if abs(value - 1) < 1e-9 else "feet"
    return unit


def length_words(inches: float, unit: str = "in") -> str:
    """'4 inches', '10.16 cm'."""
    v = to_unit(inches, unit)
    return f"{_trim(v, UNIT_DECIMALS[unit])} {unit_word(round(v, 2), unit)}"


def size_words(w_in: float, h_in: float, unit: str = "in") -> str:
    """'4 inches × 3 inches'."""
    return f"{length_words(w_in, unit)} × {length_words(h_in, unit)}"


def length_label(inches: float, unit: str = "in") -> str:
    """Dimension-arrow label: '4 inches (10.16 cm / 102 mm)'."""
    alt = " / ".join(fmt_len(inches, u) for u in _OTHERS[unit])
    return f"{length_words(inches, unit)} ({alt})"


def conversions_text(inches: float, unit: str = "in") -> str:
    """'= 10.16 cm  =  102 mm' – one length in the other units."""
    return "=  " + "  =  ".join(fmt_len(inches, u) for u in _OTHERS[unit])


def area_value(w_in: float, h_in: float, unit: str = "sqft") -> float:
    sq_in = w_in * h_in
    return sq_in * SQM_PER_SQIN if unit == "sqm" else sq_in / SQIN_PER_SQFT


def area_text(w_in: float, h_in: float, unit: str = "sqft") -> str:
    """'0.083 sq ft', '90.28 sq ft', '0.008 sq m'."""
    v = area_value(w_in, h_in, unit)
    d = 3 if v < 1 else 2
    return f"{v:.{d}f} {'sq m' if unit == 'sqm' else 'sq ft'}"


def other_area_unit(unit: str) -> str:
    return "sqft" if unit == "sqm" else "sqm"


def print_quality(px_w: int, px_h: int, w_in: float, h_in: float) -> Tuple[float, str, str]:
    """(pixels per inch, level, text) – level is 'good', 'ok' or 'low'."""
    if w_in <= 0 or h_in <= 0:
        return 0.0, "low", ""
    ppi = min(px_w / w_in, px_h / h_in)
    if ppi >= 150:
        return ppi, "good", f"{ppi:.0f} pixels per inch – excellent for print"
    if ppi >= 72:
        return ppi, "ok", f"{ppi:.0f} pixels per inch – good for large / wall prints"
    return ppi, "low", f"{ppi:.0f} pixels per inch – low, may look blurry (upscale first)"


@dataclass
class PrintSpec:
    width_in: float
    height_in: float
    unit: str = "in"

    @classmethod
    def from_pixels(cls, w: int, h: int, dpi: int, unit: str = "in") -> "PrintSpec":
        dpi = max(1, int(dpi))
        return cls(w / dpi, h / dpi, unit if unit in UNITS else "in")

    def area(self, unit: str = "sqft") -> str:
        return area_text(self.width_in, self.height_in, unit)


@dataclass
class SheetOptions:
    note_lines: list = field(default_factory=lambda: list(DEFAULT_WARNING))
    watermark: str = ""
    footer: str = ""
    area_unit: str = "sqft"
    fill: bool = True        # print shape differs from the design: trim (True) or white bars
    width_px: int = 1800     # width of the saved preview image


def shape_to_print(img: Image.Image, w_in: float, h_in: float, fill: bool = True) -> Image.Image:
    """The design trimmed (fill) or padded with white to the print shape."""
    img = img.convert("RGB")
    if w_in <= 0 or h_in <= 0:
        return img
    r = w_in / h_in
    if abs(img.width / img.height - r) < 0.004:
        return img
    if fill:
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
    return ImageOps.pad(img, size, color=(255, 255, 255))


# --------------------------------------------------------------------------
# Close-up geometry (shared by the dialog and the saved image)
# --------------------------------------------------------------------------
@dataclass
class CloseupLayout:
    box: Tuple[float, float, float, float]      # marked spot (x0, y0, x1, y1) in picture coords
    inset: Tuple[float, float, float, float]    # magnified view
    line: Tuple[Tuple[float, float], Tuple[float, float]]
    inset_corner: str                           # "br", "bl", "tr" or "tl"
    badge_left: bool                            # put the "Zoom" badge top-left instead of top-right


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def closeup_layout(dw: float, dh: float, center: Tuple[float, float], zoom: float,
                   inset_frac: float = 0.46) -> CloseupLayout:
    """Where the marked spot, the magnified inset and the connector line go.

    ``center`` is the spot as a fraction of the picture (0..1). The inset shows
    the spot ``zoom`` times bigger than it appears in the picture.
    """
    dw, dh = max(1.0, float(dw)), max(1.0, float(dh))
    s = max(24.0, min(dw, dh) * inset_frac)
    b = min(max(6.0, s / max(zoom, 1.01)), dw, dh)
    cx, cy = center[0] * dw, center[1] * dh
    x0 = min(max(cx - b / 2, 0.0), dw - b)
    y0 = min(max(cy - b / 2, 0.0), dh - b)
    box = (x0, y0, x0 + b, y0 + b)
    m = max(6.0, min(dw, dh) * 0.03)
    corners = {"br": (dw - m - s, dh - m - s), "bl": (m, dh - m - s),
               "tr": (dw - m - s, m), "tl": (m, m)}
    bc = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

    def dist(name):
        x, y = corners[name]
        return (x + s / 2 - bc[0]) ** 2 + (y + s / 2 - bc[1]) ** 2

    order = sorted(corners, key=dist, reverse=True)       # farthest corner first
    pad = m * 0.6
    grown = (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)
    name = next((n for n in order
                 if not _overlap(grown, (corners[n][0], corners[n][1],
                                         corners[n][0] + s, corners[n][1] + s))), order[0])
    ix, iy = corners[name]
    inset = (ix, iy, ix + s, iy + s)
    ic = (ix + s / 2, iy + s / 2)
    box_pts = [(box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])]
    ins_pts = [(inset[0], inset[1]), (inset[2], inset[1]), (inset[0], inset[3]), (inset[2], inset[3])]
    p0 = min(box_pts, key=lambda p: (p[0] - ic[0]) ** 2 + (p[1] - ic[1]) ** 2)
    p1 = min(ins_pts, key=lambda p: (p[0] - bc[0]) ** 2 + (p[1] - bc[1]) ** 2)
    badge_zone = (dw * 0.70, 0, dw, dh * 0.16)
    badge_left = name == "tr" or _overlap(box, badge_zone)
    return CloseupLayout(box, inset, (p0, p1), name, badge_left)


def source_box(layout: CloseupLayout, scale: float) -> Tuple[int, int, int, int]:
    """The marked spot in source pixels (scale = source px per picture px)."""
    x0, y0, x1, y1 = layout.box
    return (int(round(x0 * scale)), int(round(y0 * scale)),
            max(int(round(x0 * scale)) + 1, int(round(x1 * scale))),
            max(int(round(y0 * scale)) + 1, int(round(y1 * scale))))


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------
INK = (30, 41, 59)
MUTED = (100, 116, 139)
PANEL = (246, 248, 251)
BOX = (241, 245, 249)
BOX_LINE = (226, 232, 240)
RED = (225, 29, 46)
WARN_BG = (255, 248, 225)
WARN_LINE = (253, 230, 138)
WARN_ICON = (245, 166, 35)
WHITE = (255, 255, 255)


def _arrow(d: ImageDraw.ImageDraw, p0, p1, width: int, head: float, color=INK) -> None:
    import math
    d.line([p0, p1], fill=color, width=width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    for (x, y), a in ((p1, ang), (p0, ang + math.pi)):
        left = (x - head * math.cos(a - 0.42), y - head * math.sin(a - 0.42))
        right = (x - head * math.cos(a + 0.42), y - head * math.sin(a + 0.42))
        d.polygon([(x, y), left, right], fill=color)


def _info_box(canvas, d, rect, label, value, alt, s) -> None:
    x0, y0, x1, y1 = rect
    d.rounded_rectangle(rect, radius=int(10 * s), fill=BOX, outline=BOX_LINE, width=max(1, int(s)))
    inner = x1 - x0 - int(36 * s)
    f_lab = _fit_font(d, [label], inner, 15 * s, bold=False)
    f_val = _fit_font(d, [value], inner, 27 * s)
    f_alt = _fit_font(d, [alt], inner, 14 * s, bold=False) if alt else None
    y = y0 + int(16 * s)
    _draw_text_v(d, (x0 + int(18 * s), y), label, f_lab, MUTED)
    y += _text_h(d, label, f_lab) + int(10 * s)
    _draw_text_v(d, (x0 + int(18 * s), y), value, f_val, INK)
    if alt:
        y += _text_h(d, value, f_val) + int(10 * s)
        _draw_text_v(d, (x0 + int(18 * s), y), alt, f_alt, MUTED)


def _warning_triangle(d, x, y, size) -> None:
    d.polygon([(x + size / 2, y), (x + size, y + size * 0.9), (x, y + size * 0.9)], fill=WARN_ICON)
    lw = max(2, int(size * 0.11))
    cx = x + size / 2
    d.line([(cx, y + size * 0.32), (cx, y + size * 0.6)], fill=WHITE, width=lw)
    r = lw * 0.7
    d.ellipse([cx - r, y + size * 0.7 - r, cx + r, y + size * 0.7 + r], fill=WHITE)


def _footer(canvas, d, text, y, W, s) -> int:
    if not text.strip():
        return y
    f = _fit_font(d, [text.strip()], W - int(60 * s), 17 * s, bold=False)
    _draw_text_v(d, ((W - _text_w(d, text.strip(), f)) // 2, y), text.strip(), f, MUTED)
    return y + _text_h(d, text.strip(), f) + int(18 * s)


def _picture_size(avail_w: float, ratio: float, max_h: float) -> Tuple[int, int]:
    dw = avail_w
    dh = dw * ratio
    if dh > max_h:
        dh = max_h
        dw = dh / ratio
    return max(1, int(round(dw))), max(1, int(round(dh)))


# --------------------------------------------------------------------------
# Download Preview sheet
# --------------------------------------------------------------------------
def render_download_preview(img: Image.Image, spec: PrintSpec, opts: SheetOptions) -> Image.Image:
    W = int(opts.width_px)
    s = W / 1000.0
    pad = int(32 * s)
    unit = spec.unit
    w_in, h_in = spec.width_in, spec.height_in
    shaped = shape_to_print(img, w_in, h_in, opts.fill)
    tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    # --- sizes ---
    box_h = int(112 * s)
    top_zone = int(52 * s)      # horizontal arrow + label
    left_zone = int(58 * s)     # vertical arrow + label
    inner = int(22 * s)
    avail_w = W - 2 * pad - left_zone - 2 * inner
    ratio = h_in / w_in if w_in > 0 and h_in > 0 else shaped.height / shaped.width
    dw, dh = _picture_size(avail_w, ratio, 1.2 * W)
    panel_h = top_zone + dh + 2 * inner
    lines = [ln.strip() for ln in opts.note_lines if ln.strip()][:3]
    f_warn = _fit_font(tmp, lines or [""], W - 2 * pad - int(110 * s), 18 * s)
    lh = _text_h(tmp, "AG", f_warn)
    warn_h = (int(34 * s) + len(lines) * lh + (len(lines) - 1) * int(9 * s)) if lines else 0
    foot_h = int(48 * s) if opts.footer.strip() else 0
    H = pad + box_h + int(18 * s) + panel_h + (int(18 * s) + warn_h if warn_h else 0) + pad + foot_h

    canvas = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(canvas)

    # --- info boxes ---
    gap = int(14 * s)
    bw1 = int((W - 2 * pad - gap) * 0.6)
    y = pad
    _info_box(canvas, d, (pad, y, pad + bw1, y + box_h), "Print Size (W × H)",
              size_text(w_in, h_in, unit), size_alt_text(w_in, h_in, unit), s)
    _info_box(canvas, d, (pad + bw1 + gap, y, W - pad, y + box_h), "Area",
              area_text(w_in, h_in, opts.area_unit),
              area_text(w_in, h_in, other_area_unit(opts.area_unit)), s)
    y += box_h + int(18 * s)

    # --- picture with dimension arrows ---
    d.rounded_rectangle((pad, y, W - pad, y + panel_h), radius=int(12 * s), fill=PANEL)
    ix = pad + inner + left_zone + (avail_w - dw) // 2
    iy = y + inner + top_zone
    shown = shaped.resize((dw, dh), Image.Resampling.LANCZOS, reducing_gap=3.0)
    if opts.watermark.strip():
        shown = _watermark(shown, opts.watermark.strip(), dw / 955.0)
    canvas.paste(shown, (ix, iy))
    lw = max(2, int(2 * s))
    head = 11 * s

    # horizontal
    label = length_label(w_in, unit)
    f_dim = _fit_font(d, [label], max(40, dw - int(70 * s)), 19 * s, min_size=9)
    tw, th = _text_w(d, label, f_dim), _text_h(d, label, f_dim)
    ay = iy - int(26 * s)
    lx = ix + (dw - tw) // 2
    g = int(12 * s)
    _arrow(d, (lx - g, ay), (ix, ay), lw, head)
    _arrow(d, (lx + tw + g, ay), (ix + dw, ay), lw, head)
    _draw_text_v(d, (lx, ay - th // 2), label, f_dim, INK)

    # vertical (text reads bottom to top)
    vlabel = length_label(h_in, unit)
    f_v = _fit_font(d, [vlabel], max(40, dh - int(70 * s)), 19 * s, min_size=9)
    vw, vh = _text_w(d, vlabel, f_v), _text_h(d, vlabel, f_v)
    ax = ix - int(30 * s)
    ly = iy + (dh - vw) // 2
    _arrow(d, (ax, ly - g), (ax, iy), lw, head)
    _arrow(d, (ax, ly + vw + g), (ax, iy + dh), lw, head)
    timg = Image.new("RGBA", (vw + 4, vh + 6), (0, 0, 0, 0))
    _draw_text_v(ImageDraw.Draw(timg), (2, 3), vlabel, f_v, INK + (255,))
    timg = timg.rotate(90, expand=True)
    canvas.paste(timg, (ax - timg.width // 2, ly - 2), timg)
    y += panel_h

    # --- warning ---
    if warn_h:
        y += int(18 * s)
        d.rounded_rectangle((pad, y, W - pad, y + warn_h), radius=int(10 * s),
                            fill=WARN_BG, outline=WARN_LINE, width=max(1, int(1.5 * s)))
        tri = int(40 * s)
        _warning_triangle(d, pad + int(26 * s), y + (warn_h - tri) // 2, tri)
        ty = y + int(17 * s)
        for ln in lines:
            _draw_text_v(d, (pad + int(90 * s), ty), ln, f_warn, INK)
            ty += lh + int(9 * s)
        y += warn_h

    y += pad
    if foot_h:
        _footer(canvas, d, opts.footer, y - int(6 * s), W, s)
    return canvas


# --------------------------------------------------------------------------
# Closeup Print Preview sheet
# --------------------------------------------------------------------------
def render_closeup_preview(img: Image.Image, spec: PrintSpec, center: Tuple[float, float],
                           zoom: float, opts: SheetOptions) -> Image.Image:
    W = int(opts.width_px)
    s = W / 1000.0
    pad = int(28 * s)
    w_in, h_in = spec.width_in, spec.height_in
    shaped = shape_to_print(img, w_in, h_in, opts.fill)
    ratio = h_in / w_in if w_in > 0 and h_in > 0 else shaped.height / shaped.width
    dw, dh = _picture_size(W - 2 * pad, ratio, 1.2 * W)
    bar_h = int(96 * s)
    foot_h = int(48 * s) if opts.footer.strip() else 0
    H = pad + dh + int(16 * s) + bar_h + pad + foot_h
    canvas = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(canvas)

    ox = (W - dw) // 2
    oy = pad
    shown = shaped.resize((dw, dh), Image.Resampling.LANCZOS, reducing_gap=3.0)
    if opts.watermark.strip():
        shown = _watermark(shown, opts.watermark.strip(), dw / 955.0)
    canvas.paste(shown, (ox, oy))

    lay = closeup_layout(dw, dh, center, zoom)
    k = shaped.width / dw
    detail_box = source_box(lay, k)
    x0, y0, x1, y1 = lay.inset
    side = max(1, int(round(x1 - x0)))
    detail = shaped.crop(detail_box).resize((side, side), Image.Resampling.LANCZOS)

    lw = max(2, int(3 * s))
    (p0x, p0y), (p1x, p1y) = lay.line
    d.line([(ox + p0x, oy + p0y), (ox + p1x, oy + p1y)], fill=RED, width=lw)
    bx = [ox + lay.box[0], oy + lay.box[1], ox + lay.box[2], oy + lay.box[3]]
    d.rectangle(bx, outline=RED, width=lw)
    ix, iy = int(round(ox + x0)), int(round(oy + y0))
    border = max(3, int(4 * s))
    d.rectangle([ix - border - 2, iy - border - 2, ix + side + border + 1, iy + side + border + 1],
                fill=WHITE)
    canvas.paste(detail, (ix, iy))
    d.rectangle([ix - border, iy - border, ix + side + border - 1, iy + side + border - 1],
                outline=RED, width=border)

    # zoom badge
    tag = f"Zoom: {zoom * 100:.0f}%"
    f_tag = get_font(int(20 * s))
    tw, th = _text_w(d, tag, f_tag), _text_h(d, tag, f_tag)
    bw_, bh_ = tw + int(26 * s), th + int(20 * s)
    m = int(14 * s)
    bx0 = ox + m if lay.badge_left else ox + dw - m - bw_
    d.rounded_rectangle((bx0, oy + m, bx0 + bw_, oy + m + bh_), radius=int(7 * s), fill=(24, 24, 27))
    _draw_text_v(d, (bx0 + int(13 * s), oy + m + int(10 * s)), tag, f_tag, WHITE)

    # info bar
    y = oy + dh + int(16 * s)
    d.rounded_rectangle((pad, y, W - pad, y + bar_h), radius=int(10 * s), fill=BOX, outline=BOX_LINE,
                        width=max(1, int(s)))
    cols = [("Print Size", size_text(w_in, h_in, spec.unit), size_alt_text(w_in, h_in, spec.unit, True)),
            ("Area", area_text(w_in, h_in, opts.area_unit), ""),
            ("Close-up", f"{zoom * 100:.0f}%", "zoomed detail")]
    widths = [0.5, 0.25, 0.25]
    x = pad
    total = W - 2 * pad
    for (lab, val, alt), frac in zip(cols, widths):
        cw = int(total * frac)
        f_l = get_font(int(14 * s), bold=False)
        f_v = _fit_font(d, [val], cw - int(36 * s), 22 * s)
        cy = y + int(14 * s)
        _draw_text_v(d, (x + int(20 * s), cy), lab, f_l, MUTED)
        cy += _text_h(d, lab, f_l) + int(8 * s)
        _draw_text_v(d, (x + int(20 * s), cy), val, f_v, INK)
        if alt:
            cy += _text_h(d, val, f_v) + int(7 * s)
            _draw_text_v(d, (x + int(20 * s), cy), alt, get_font(int(13 * s), bold=False), MUTED)
        if x > pad:
            d.line([(x, y + int(14 * s)), (x, y + bar_h - int(14 * s))], fill=BOX_LINE, width=max(1, int(s)))
        x += cw
    y += bar_h + pad
    if foot_h:
        _footer(canvas, d, opts.footer, y - int(6 * s), W, s)
    return canvas


def sheet_filename(src_name: Optional[str], spec: PrintSpec, kind: str, ext: str) -> str:
    stem = Path(src_name).stem if src_name else "design"
    u = spec.unit
    w = _trim(to_unit(spec.width_in, u), 2)
    h = _trim(to_unit(spec.height_in, u), 2)
    return f"{stem}_{kind}_{w}x{h}{u}{ext}"
