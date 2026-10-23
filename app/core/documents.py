"""
Printable documents (A3 landscape at 150 dpi, saved as PDF / JPG):

* installer_sheet() – wall elevation with numbered panels, seams, overlaps,
                       openings, dimensions, hanging instructions, panel list.
* proof_sheet()     – customer proof with business details, the design on the
                       wall, room mockup, specification, warning and approval box.
* options_sheet()   – 2–4 design options side by side (A / B / C / D).
* survey_sheet()    – measured wall from a photo with dimension lines.
* test_strip()      – a 100 %-scale piece of the design with colour bars.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from app.core import colour as col
from app.core import units as u
from app.core import wall as wl
from app.core.proof import get_font

DPI = 150
A3 = (int(420 / 25.4 * DPI), int(297 / 25.4 * DPI))     # 2480 x 1754
A4P = (int(210 / 25.4 * DPI), int(297 / 25.4 * DPI))

INK = (24, 32, 46)
MUTED = (100, 112, 130)
LINE = (210, 216, 226)
PANEL_BG = (246, 248, 251)
RED = (214, 32, 48)
BLUE = (26, 115, 232)
YELLOW_BG = (255, 247, 220)
YELLOW_LINE = (246, 214, 120)

WARNING = ("THERE MIGHT BE SLIGHT VARIATIONS IN COLOURS IN ACTUAL PRINT. "
           "PLEASE CHECK SIZE & DESIGN CAREFULLY BEFORE APPROVING.")


# ======================================================================
# Drawing helpers
# ======================================================================
def F(size: float, bold: bool = False):
    return get_font(int(round(size)), bold)


def tw(d: ImageDraw.ImageDraw, text: str, font) -> int:
    l, _t, r, _b = d.textbbox((0, 0), text, font=font)
    return r - l


def th(d: ImageDraw.ImageDraw, text: str, font) -> int:
    _l, t, _r, b = d.textbbox((0, 0), text or "Ag", font=font)
    return b - t


def text(d, xy, s, font, fill=INK, anchor="la"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)


def wrap(d, s: str, font, width: int) -> List[str]:
    out, line = [], ""
    for word in s.split():
        t = (line + " " + word).strip()
        if tw(d, t, font) <= width or not line:
            line = t
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out


def para(d, xy, s, font, width, fill=INK, gap=1.25) -> int:
    x, y = xy
    lh = int(th(d, "Ag", font) * gap) + 2
    for ln in s.split("\n"):
        for w in wrap(d, ln, font, width) or [""]:
            d.text((x, y), w, font=font, fill=fill)
            y += lh
    return y


def dashed(d, p0, p1, fill, width=2, dash=10, gap=7):
    x0, y0 = p0
    x1, y1 = p1
    L = math.hypot(x1 - x0, y1 - y0)
    if L == 0:
        return
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    t = 0.0
    while t < L:
        e = min(L, t + dash)
        d.line([(x0 + ux * t, y0 + uy * t), (x0 + ux * e, y0 + uy * e)], fill=fill, width=width)
        t = e + gap


def hatch(img: Image.Image, box, colour=(120, 130, 150), alpha=70, spacing=12, width=2):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    h = y1 - y0
    for t in range(-h, x1 - x0, spacing):
        ld.line([(t, h), (t + h, 0)], fill=colour + (alpha,), width=width)
    img.paste(layer, (x0, y0), layer)


def tint(img: Image.Image, box, colour, alpha: int):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    if x1 - x0 < 1 or y1 - y0 < 1:
        return
    layer = Image.new("RGBA", (x1 - x0, y1 - y0), colour + (alpha,))
    img.paste(layer, (x0, y0), layer)


def dim_h(img, d, x0, x1, y, label, font, fill=INK, above=True, tick=9):
    d.line([(x0, y), (x1, y)], fill=fill, width=2)
    for x in (x0, x1):
        d.line([(x, y - tick), (x, y + tick)], fill=fill, width=2)
        d.line([(x - tick * 0.6, y + tick * 0.6), (x + tick * 0.6, y - tick * 0.6)], fill=fill, width=2)
    w = tw(d, label, font) + 10
    h = th(d, label, font) + 6
    cx = (x0 + x1) / 2
    if w > abs(x1 - x0) - 6:
        yb = y - h - 6 if above else y + 6
    else:
        yb = y - h / 2
    d.rectangle([cx - w / 2, yb, cx + w / 2, yb + h], fill=(255, 255, 255))
    d.text((cx, yb + h / 2), label, font=font, fill=fill, anchor="mm")


def dim_v(img, d, x, y0, y1, label, font, fill=INK, tick=9):
    d.line([(x, y0), (x, y1)], fill=fill, width=2)
    for y in (y0, y1):
        d.line([(x - tick, y), (x + tick, y)], fill=fill, width=2)
        d.line([(x - tick * 0.6, y + tick * 0.6), (x + tick * 0.6, y - tick * 0.6)], fill=fill, width=2)
    w = tw(d, label, font) + 10
    h = th(d, label, font) + 6
    t = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    ImageDraw.Draw(t).text((w / 2, h / 2), label, font=font, fill=fill + (255,) if len(fill) == 3 else fill,
                           anchor="mm")
    t = t.rotate(90, expand=True)
    if t.height > abs(y1 - y0) - 6:
        img.paste(t, (int(x - t.width - 6), int((y0 + y1) / 2 - t.height / 2)), t)
    else:
        img.paste(t, (int(x - t.width / 2), int((y0 + y1) / 2 - t.height / 2)), t)


def fit_image(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    im = img.copy()
    im.thumbnail((box_w, box_h), Image.Resampling.LANCZOS)
    return im


def header(page: Image.Image, title: str, subtitle: str, job: wl.Job, business: Dict, h: int = 170) -> int:
    d = ImageDraw.Draw(page)
    W = page.width
    m = 60
    x = m
    logo = business.get("logo")
    if logo and Path(logo).is_file():
        try:
            lg = Image.open(logo).convert("RGBA")
            lg.thumbnail((260, h - 50))
            page.paste(lg, (x, (h - lg.height) // 2), lg)
            x += lg.width + 28
        except Exception:
            pass
    name = business.get("name") or ""
    if name:
        text(d, (x, 40), name, F(40, True))
        contact = "  ·  ".join(v for v in (business.get("phone"), business.get("email"), business.get("website")) if v)
        text(d, (x, 92), contact, F(24), MUTED)
        if business.get("address"):
            text(d, (x, 124), business.get("address"), F(22), MUTED)
    text(d, (W - m, 34), title, F(46, True), anchor="ra")
    text(d, (W - m, 94), subtitle, F(24), MUTED, anchor="ra")
    info = f"{job.job_no}   ·   {job.customer or '—'}   ·   {datetime.now():%d %b %Y}"
    text(d, (W - m, 128), info, F(24), INK, anchor="ra")
    d.line([(m, h), (W - m, h)], fill=LINE, width=3)
    return h + 20


# ======================================================================
# Elevation (the wall run with the design, panels, openings, dimensions)
# ======================================================================
def draw_elevation(page: Image.Image, box, job: wl.Job, source=None, *, design_alpha: float = 1.0,
                   panels: Optional[List[wl.Panel]] = None, numbers: bool = True, seams: bool = True,
                   bleed: bool = True, obstacles: bool = True, dims: bool = True, unit: str = "m",
                   panel_dims: bool = True, crop_to_wall: bool = False) -> Tuple[float, float, float]:
    """Draw inside `box` (x0, y0, x1, y1). Returns (px per metre, origin x, origin y) of the artwork."""
    d = ImageDraw.Draw(page)
    x0, y0, x1, y1 = box
    pad_l, pad_t, pad_r, pad_b = (110 if dims else 20), (150 if (dims or numbers) else 20), 30, (110 if dims else 20)
    aw, ah = job.art_width, job.art_height
    if crop_to_wall:   # show only the walls (customer proofs)
        ex0, ey0 = job.panels.bleed_left, job.panels.bleed_top
        ex1, ey1 = ex0 + job.run_width, job.floor_y
        if not panels:
            pad_t = 90 if dims else 20
    else:
        ex0, ey0, ex1, ey1 = 0.0, 0.0, aw, ah
    ew, eh = ex1 - ex0, ey1 - ey0
    s = min((x1 - x0 - pad_l - pad_r) / ew, (y1 - y0 - pad_t - pad_b) / eh)
    ox = x0 + pad_l + ((x1 - x0 - pad_l - pad_r) - ew * s) / 2 - ex0 * s
    oy = y0 + pad_t + ((y1 - y0 - pad_t - pad_b) - eh * s) / 2 - ey0 * s
    X = lambda m: ox + m * s
    Y = lambda m: oy + m * s
    # design
    if source is not None:
        art = source.render(ex0, ey0, ex1, ey1, max(1, int(ew * s)), max(1, int(eh * s)))
        if design_alpha < 1:
            art = Image.blend(Image.new("RGB", art.size, (255, 255, 255)), art, design_alpha)
        page.paste(art, (int(X(ex0)), int(Y(ey0))))
    else:
        d.rectangle([X(ex0), Y(ey0), X(ex1), Y(ey1)], fill=(236, 239, 244))
    # bleed and areas without wall
    if bleed:
        bl, bt = job.panels.bleed_left, job.panels.bleed_top
        tint(page, (X(0), Y(0), X(aw), Y(bt)), (255, 255, 255), 120)
        tint(page, (X(0), Y(job.floor_y), X(aw), Y(ah)), (255, 255, 255), 120)
        tint(page, (X(0), Y(bt), X(bl), Y(job.floor_y)), (255, 255, 255), 120)
        tint(page, (X(aw - job.panels.bleed_right), Y(bt), X(aw), Y(job.floor_y)), (255, 255, 255), 120)
    # where there is no wall (above lower walls and slopes, below stairs)
    if job.uneven:
        bt = job.panels.bleed_top
        mask = Image.new("L", page.size, 0)
        md = ImageDraw.Draw(mask)
        md.rectangle([X(job.panels.bleed_left), Y(bt if not crop_to_wall else ey0),
                      X(job.panels.bleed_left + job.run_width), Y(job.floor_y)], fill=255)
        for i in range(len(job.walls)):
            md.polygon([(X(x), Y(y)) for x, y in job.wall_outline(i)], fill=0)
        if crop_to_wall:
            page.paste((255, 255, 255), (0, 0), mask)
        else:
            white = Image.new("RGB", page.size, (255, 255, 255))
            page.paste(Image.blend(page, white, 0.6), (0, 0), mask)
            lines = Image.new("RGB", page.size, (120, 130, 150))
            hm = Image.new("L", page.size, 0)
            hd = ImageDraw.Draw(hm)
            for t in range(-page.height, page.width, 12):
                hd.line([(t, page.height), (t + page.height, 0)], fill=70, width=2)
            page.paste(lines, (0, 0), Image.composite(hm, Image.new("L", page.size, 0), mask))
        d = ImageDraw.Draw(page)
    for i, w in enumerate(job.walls):
        d.polygon([(X(x), Y(y)) for x, y in job.wall_outline(i)], outline=INK, width=3)
    for cx, kind in job.corners():
        dashed(d, (X(cx), Y(job.panels.bleed_top)), (X(cx), Y(job.floor_y)), (90, 90, 90), 2)
        text(d, (X(cx) + 6, Y(job.floor_y) - 34), f"{kind} corner", F(18), MUTED)
    # openings and furniture
    if obstacles:
        for wi, o in job.all_obstacles():
            ox0, oy0, ox1, oy1 = job.obstacle_rect(wi, o)
            r = (X(ox0), Y(oy0), X(ox1), Y(oy1))
            c = col.rgb_of(o.colour)
            if o.in_front:
                hatch(page, r, c, 110, 10, 2)
                dashed(d, (r[0], r[1]), (r[2], r[1]), c, 3)
                dashed(d, (r[2], r[1]), (r[2], r[3]), c, 3)
                dashed(d, (r[0], r[1]), (r[0], r[3]), c, 3)
            else:
                tint(page, r, (255, 255, 255), 150)
                d.rectangle(r, outline=c, width=4)
            lab = o.name + (" (in front)" if o.in_front else "")
            f = F(20, True)
            if r[2] - r[0] > tw(d, lab, f) + 16 and r[3] - r[1] > 36:
                d.rectangle([r[0] + 6, r[1] + 6, r[0] + 16 + tw(d, lab, f), r[1] + 34], fill=c)
                text(d, (r[0] + 11, r[1] + 9), lab, f, (255, 255, 255))
    # panels
    if panels:
        for k, p in enumerate(panels):
            if k % 2 == 1:
                tint(page, (X(p.x0), Y(p.y0), X(p.x1), Y(p.y1)), (26, 115, 232), 26)
            if p.y0 > 1e-6 or p.y1 < ah - 1e-6:
                d.rectangle([X(p.x0), Y(p.y0), X(p.x1), Y(p.y1)], outline=(26, 115, 232), width=2)
            if p.seam_right is not None and seams:
                o = job.panels.overlap
                tint(page, (X(p.seam_right - o / 2), Y(0), X(p.seam_right + o / 2), Y(ah)), RED, 60)
                dashed(d, (X(p.seam_right), Y(0) - 10), (X(p.seam_right), Y(ah) + 10), RED, 3, 14, 8)
            if numbers:
                cx = (X(p.x0) + X(p.x1)) / 2
                r = 26
                cy = Y(0) - 60
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=INK)
                text(d, (cx, cy), f"P{p.index}", F(20, True), (255, 255, 255), anchor="mm")
    # dimensions
    if dims:
        f = F(20, True)
        rx0, rx1 = X(job.panels.bleed_left), X(job.panels.bleed_left + job.run_width)
        ry0, ry1 = Y(job.panels.bleed_top), Y(job.floor_y)
        dim_h(page, d, rx0, rx1, Y(ey0) - (110 if numbers and panels else 40),
              f"wall {u.fmt(job.run_width, unit)}  ({u.ft_in(job.run_width)})", f)
        dim_v(page, d, X(ex0) - 60, ry0, ry1, f"{u.fmt(job.run_height, unit)}  ({u.ft_in(job.run_height)})", f)
        if panels and panel_dims:
            for p in panels:
                dim_h(page, d, X(p.x0), X(p.x1), Y(ah) + 40, f"{p.width * 100:.1f}", F(18), INK, above=False)
            text(d, (X(0), Y(ah) + 72), f"panel widths in cm incl. {job.panels.overlap * 100:.1f} cm overlap · "
                 f"print area {u.fmt(aw, unit)} × {u.fmt(ah, unit)} incl. bleed", F(18), MUTED)
        elif len(job.walls) > 1:
            for i, w in enumerate(job.walls):
                a, _, b, _ = job.wall_rect(i)
                dim_h(page, d, X(a), X(b), Y(job.floor_y) + 40, u.fmt(w.width, unit), F(18), INK, above=False)
    return s, ox, oy


# ======================================================================
# Installation sheet
# ======================================================================
def installer_sheet(job: wl.Job, source, panels: List[wl.Panel], files: Sequence[str], business: Dict
                    ) -> List[Image.Image]:
    W, H = A3
    p1 = Image.new("RGB", (W, H), (255, 255, 255))
    top = header(p1, "INSTALLATION SHEET", f"{job.room or 'Wall'} · {len(panels)} panels", job, business)
    d = ImageDraw.Draw(p1)
    right_w = 760
    draw_elevation(p1, (40, top, W - right_w - 40, H - 60), job, source, design_alpha=0.55, panels=panels)
    x = W - right_w
    y = top + 10
    d.rounded_rectangle([x, y, W - 50, H - 60], radius=18, fill=PANEL_BG)
    x += 30
    y += 26
    text(d, (x, y), "How to hang", F(32, True))
    y += 56
    o = job.panels.overlap * 100
    order = "RIGHT" if job.panels.right_to_left else "LEFT"
    steps = [
        f"Check you have panels P1 to P{len(panels)}. P1 starts at the {order} of the wall.",
        "Every panel has ▲ TOP printed in the white strip. Trim the white strips off before hanging.",
        f"Bleed: {job.panels.bleed_top * 100:.0f} cm extra at top and bottom, {job.panels.bleed_left * 100:.0f} cm "
        "at the sides – trim at the ceiling, skirting and wall edges.",
        (f"Overlap: {o:.1f} cm at each seam. Line the next panel's edge up with the black tick; the red "
         "triangle is the seam line." if o > 0 else "Butt joint: panels meet edge to edge (no overlap)."),
        "Hang P1 against a plumb / laser line, not the corner of the room.",
        f"Material: {job.material}. Use the paste and method the material maker recommends.",
        "Cut around doors, windows, sockets and switches after hanging (power off first).",
    ]
    f = F(22)
    for i, s in enumerate(steps, 1):
        d.ellipse([x, y + 2, x + 34, y + 36], fill=INK)
        text(d, (x + 17, y + 19), str(i), F(18, True), (255, 255, 255), anchor="mm")
        y = para(d, (x + 48, y + 4), s, f, right_w - 150) + 14
    y += 6
    text(d, (x, y), "Panels", F(28, True))
    y += 46
    f2 = F(19)
    for p, name in zip(panels, files):
        text(d, (x, y), f"P{p.index:02d}", F(19, True))
        text(d, (x + 70, y), f"{p.width * 100:.1f} × {p.height * 100:.1f} cm", f2)
        nm = name if len(name) <= 46 else name[:43] + "…"
        text(d, (x + 300, y), nm, F(15), MUTED)
        y += 30
        if y > H - 260:
            text(d, (x, y), f"… {len(panels) - p.index} more – see job ticket", f2, MUTED)
            break
    from app.core.production import _qr
    qr = _qr(f"{job.job_no}|{len(panels)} panels|{job.customer}", 170)
    if qr is not None:
        p1.paste(qr, (W - 50 - 30 - 170, H - 60 - 30 - 170))
    # page 2: the panels side by side
    p2 = Image.new("RGB", (W, H), (255, 255, 255))
    top = header(p2, "PANEL ORDER", "hang in this order", job, business)
    d2 = ImageDraw.Draw(p2)
    gap = 26
    n = len(panels)
    avail_w = W - 120 - gap * (n - 1)
    total_w = sum(p.width for p in panels)
    s = min(avail_w / total_w, (H - top - 260) / job.art_height)
    x = 60 + (avail_w - total_w * s) / 2
    seq = sorted(panels, key=lambda p: p.x0)
    for p in seq:
        pw, ph = max(1, int(p.width * s)), max(1, int(p.height * s))
        img = source.render(p.x0, p.y0, p.x1, p.y1, pw, ph) if source is not None else Image.new("RGB", (pw, ph), (230, 230, 230))
        yy = top + 90 + int(p.y0 * s)
        p2.paste(img, (int(x), yy))
        d2.rectangle([x, yy, x + pw, yy + ph], outline=INK, width=2)
        d2.ellipse([x + pw / 2 - 30, yy - 76, x + pw / 2 + 30, yy - 16], fill=INK)
        text(d2, (x + pw / 2, yy - 46), f"P{p.index}", F(22, True), (255, 255, 255), anchor="mm")
        text(d2, (x + pw / 2, yy + ph + 18), f"{p.width * 100:.1f} cm", F(20, True), anchor="ma")
        text(d2, (x + pw / 2, yy + ph + 48), f"{p.height * 100:.0f} long" if job.uneven else "▲ top", F(18),
             MUTED, anchor="ma")
        x += pw + gap
    arrow_y = H - 90
    d2.line([(160, arrow_y), (W - 160, arrow_y)], fill=MUTED, width=4)
    if job.panels.right_to_left:
        d2.polygon([(160, arrow_y), (190, arrow_y - 14), (190, arrow_y + 14)], fill=MUTED)
        text(d2, (W / 2, arrow_y - 40), "hang from right to left", F(22), MUTED, anchor="ma")
    else:
        d2.polygon([(W - 160, arrow_y), (W - 190, arrow_y - 14), (W - 190, arrow_y + 14)], fill=MUTED)
        text(d2, (W / 2, arrow_y - 40), "hang from left to right", F(22), MUTED, anchor="ma")
    return [p1, p2]


# ======================================================================
# Customer proof
# ======================================================================
def proof_sheet(job: wl.Job, source, business: Dict, *, mockup: Optional[Image.Image] = None,
                version: int = 1, show_seams: bool = False, watermark: bool = True,
                notes: str = "", unit: str = "m", ppi: float = 0.0) -> Image.Image:
    W, H = A3
    page = Image.new("RGB", (W, H), (255, 255, 255))
    top = header(page, f"DESIGN PROOF  v{version}", "Please check and approve", job, business)
    d = ImageDraw.Draw(page)
    right_w = 760 if mockup is not None else 700
    panels = wl.compute_panels(job) if show_seams else None
    draw_elevation(page, (40, top, W - right_w - 40, H - 330), job, source, panels=panels,
                   numbers=bool(panels), seams=bool(panels), bleed=False, unit=unit, panel_dims=False,
                   crop_to_wall=not show_seams)
    x = W - right_w
    y = top + 10
    if mockup is not None:
        mk = fit_image(mockup, right_w - 50, 470)
        page.paste(mk, (x, y))
        d.rectangle([x, y, x + mk.width, y + mk.height], outline=LINE, width=2)
        text(d, (x, y + mk.height + 8), "Room preview (illustration)", F(18), MUTED)
        y += mk.height + 48
    rows = [
        ("Customer", job.customer or "—"), ("Room", job.room or "—"),
        ("Wall size", " + ".join(u.fmt_size(w.width, w.height, unit) for w in job.walls)),
        ("Wall area", u.fmt_area_both(job.wall_area())),
        ("Net area", u.fmt_area_both(job.wall_area() - job.openings_area()) + "  (minus doors/windows)"),
        ("Print size", f"{u.fmt_size(job.art_width, job.art_height, unit)} incl. bleed"),
        ("Panels", f"{len(wl.compute_panels(job))} × up to {job.panels.media_width * 100:.0f} cm"),
        ("Material", f"{job.material} · {job.finish}"),
    ]
    if ppi:
        lvl, txt = wl.ppi_quality(ppi, job.view_distance)
        rows.append(("Print quality", txt.split(" – ")[0] + " – " + {"excellent": "excellent", "good": "good",
                                                                          "low": "may look soft up close"}[lvl]))
    f_l, f_v = F(21), F(21, True)
    for k, v in rows:
        text(d, (x, y), k, f_l, MUTED)
        y2 = para(d, (x + 190, y), v, f_v, right_w - 240)
        y = max(y + 34, y2 + 4)
    if notes or job.notes:
        y += 8
        text(d, (x, y), "Notes", F(22, True))
        y = para(d, (x, y + 32), notes or job.notes, F(20), right_w - 60, MUTED)
    # warning + approval
    by = H - 300
    d.rounded_rectangle([40, by, W - 40, by + 74], radius=14, fill=YELLOW_BG, outline=YELLOW_LINE, width=2)
    d.polygon([(80, by + 56), (104, by + 16), (128, by + 56)], fill=(245, 166, 35))
    text(d, (104, by + 44), "!", F(26, True), (255, 255, 255), anchor="mm")
    text(d, (150, by + 22), WARNING, F(21, True))
    ay = by + 100
    d.rounded_rectangle([40, ay, W - 40, H - 40], radius=14, outline=INK, width=3)
    text(d, (70, ay + 20), "CUSTOMER APPROVAL", F(26, True))
    f = F(22)
    cols = [("Approved for print", 70), ("Name", 520), ("Signature", 1050), ("Date", 1640)]
    for lab, cx in cols:
        text(d, (cx, ay + 80), lab, f, MUTED)
        if lab == "Approved for print":
            for i, t in enumerate(("Yes", "No – changes below")):
                bx = cx + i * 160
                d.rectangle([bx, ay + 116, bx + 30, ay + 146], outline=INK, width=3)
                text(d, (bx + 40, ay + 118), t, F(20))
        else:
            d.line([(cx, ay + 146), (cx + (430 if lab != "Date" else 300), ay + 146)], fill=INK, width=2)
    if watermark:
        page = _watermark(page, "PROOF – NOT FOR PRINT")
    return page


def _watermark(page: Image.Image, label: str) -> Image.Image:
    layer = Image.new("RGBA", page.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    f = F(90, True)
    step_x, step_y = 1300, 520
    for yy in range(-200, page.height + 400, step_y):
        for xx in range(-400, page.width + 400, step_x):
            ld.text((xx + (yy // step_y % 2) * step_x // 2, yy), label, font=f, fill=(200, 30, 50, 28))
    layer = layer.rotate(18, resample=Image.Resampling.BICUBIC, center=(page.width / 2, page.height / 2))
    base = page.convert("RGBA")
    base.alpha_composite(layer)
    return base.convert("RGB")


# ======================================================================
# Options sheet
# ======================================================================
def options_sheet(job: wl.Job, options: Sequence[Tuple[str, Image.Image]], business: Dict) -> Image.Image:
    W, H = A3
    page = Image.new("RGB", (W, H), (255, 255, 255))
    top = header(page, "DESIGN OPTIONS", f"{len(options)} options to choose from", job, business)
    d = ImageDraw.Draw(page)
    n = max(1, len(options))
    cols = 2 if n > 1 else 1
    rows = math.ceil(n / cols)
    gw = (W - 80 - (cols - 1) * 40) // cols
    gh = (H - top - 200 - (rows - 1) * 40) // rows
    for i, (label, img) in enumerate(options):
        cx = 40 + (i % cols) * (gw + 40)
        cy = top + 10 + (i // cols) * (gh + 40)
        d.rounded_rectangle([cx, cy, cx + gw, cy + gh], radius=16, fill=PANEL_BG)
        letter = "ABCD"[i] if i < 4 else str(i + 1)
        d.ellipse([cx + 20, cy + 18, cx + 80, cy + 78], fill=INK)
        text(d, (cx + 50, cy + 48), letter, F(32, True), (255, 255, 255), anchor="mm")
        text(d, (cx + 100, cy + 34), label, F(28, True))
        pic = fit_image(img, gw - 40, gh - 120)
        page.paste(pic, (int(cx + (gw - pic.width) / 2), int(cy + 100 + (gh - 120 - pic.height) / 2)))
    by = H - 150
    d.rounded_rectangle([40, by, W - 40, H - 40], radius=14, outline=INK, width=3)
    text(d, (70, by + 38), "Chosen option:", F(26, True))
    for i in range(min(n, 4)):
        bx = 330 + i * 150
        d.rectangle([bx, by + 34, bx + 36, by + 70], outline=INK, width=3)
        text(d, (bx + 48, by + 36), "ABCD"[i], F(26, True))
    text(d, (1000, by + 38), "Name / signature / date:", F(24), MUTED)
    d.line([(1330, by + 70), (W - 80, by + 70)], fill=INK, width=2)
    return page


# ======================================================================
# Survey sheet
# ======================================================================
def draw_wall_survey(page: Image.Image, box, w: wl.Wall, flat: Optional[Image.Image], unit: str = "m"):
    from app.core.measure import wall_dimensions
    d = ImageDraw.Draw(page)
    x0, y0, x1, y1 = box
    pad_l, pad_t, pad_r, pad_b = 130, 150, 130, 120
    s = min((x1 - x0 - pad_l - pad_r) / w.width, (y1 - y0 - pad_t - pad_b) / w.height)
    ox = x0 + pad_l + ((x1 - x0 - pad_l - pad_r) - w.width * s) / 2
    oy = y0 + pad_t
    X = lambda m: ox + m * s
    Y = lambda h: oy + (w.height - h) * s
    if flat is not None:
        page.paste(flat.convert("RGB").resize((int(w.width * s), int(w.height * s)), Image.Resampling.LANCZOS),
                   (int(X(0)), int(Y(w.height))))
    else:
        d.rectangle([X(0), Y(w.height), X(w.width), Y(0)], fill=(236, 239, 244))
    # 50 cm grid
    for i in range(1, int(w.width / 0.5) + 1):
        d.line([(X(i * 0.5), Y(w.height)), (X(i * 0.5), Y(0))], fill=(255, 255, 255), width=1)
    for i in range(1, int(w.height / 0.5) + 1):
        d.line([(X(0), Y(i * 0.5)), (X(w.width), Y(i * 0.5))], fill=(255, 255, 255), width=1)
    if w.shaped:
        outline = [(X(x), Y(y)) for x, y in w.outline()]
        mask = Image.new("L", page.size, 0)
        md = ImageDraw.Draw(mask)
        md.rectangle([X(0), Y(w.height), X(w.width), Y(0)], fill=255)
        md.polygon(outline, fill=0)
        page.paste(Image.blend(page, Image.new("RGB", page.size, (255, 255, 255)), 0.65), (0, 0), mask)
        d = ImageDraw.Draw(page)
        d.rectangle([X(0), Y(w.height), X(w.width), Y(0)], outline=(170, 178, 190), width=1)
        d.polygon(outline, outline=INK, width=3)
    else:
        d.rectangle([X(0), Y(w.height), X(w.width), Y(0)], outline=INK, width=3)
    for o in w.obstacles:
        c = col.rgb_of(o.colour)
        r = (X(o.x), Y(o.top), X(o.x + o.w), Y(o.y))
        if o.in_front:
            hatch(page, r, c, 120, 10, 2)
            for a, b in (((r[0], r[1]), (r[2], r[1])), ((r[2], r[1]), (r[2], r[3])), ((r[0], r[3]), (r[0], r[1]))):
                dashed(d, a, b, c, 3)
        else:
            tint(page, r, c, 40)
            d.rectangle(r, outline=c, width=4)
        lab = o.name + (" · in front" if o.in_front else "")
        f = F(20, True)
        lw_ = tw(d, lab, f) + 16
        lx, ly = r[0] + 6, r[1] + 6
        if lw_ > r[2] - r[0] - 8:
            lx, ly = r[2] - lw_, r[1] - 36
        d.rectangle([lx, ly, lx + lw_, ly + 30], fill=c)
        text(d, (lx + 8, ly + 3), lab, f, (255, 255, 255))
    f = F(20, True)
    for dm in wall_dimensions(w, unit):
        c = col.rgb_of(dm.colour)
        if dm.side in ("top", "bottom"):
            off = (-30 - 40 * dm.level) if dm.side == "top" else (30 + 40 * (dm.level - 1))
            yy = (Y(dm.y0) + off) if dm.side == "top" else (Y(0) + off)
            dim_h(page, d, X(dm.x0), X(dm.x1), yy, dm.text, f, c, above=dm.side == "top")
        else:
            off = {"left": -18 - 50 * dm.level, "right": 18 + 50 * dm.level}.get(dm.side, 0)
            if dm.level == 1 and dm.side == "left":
                xx = X(0) - 60
            else:
                xx = X(dm.x0) + off
            dim_v(page, d, xx, Y(dm.y1), Y(dm.y0), dm.text, f, c)


def survey_sheet(job: wl.Job, wall_index: int, flat: Optional[Image.Image], photo: Optional[Image.Image],
                 corners: Optional[Sequence[Tuple[float, float]]], business: Dict, accuracy: str = "",
                 unit: str = "m") -> Image.Image:
    from app.core.measure import items_table
    W, H = A3
    page = Image.new("RGB", (W, H), (255, 255, 255))
    w = job.walls[wall_index]
    top = header(page, "SITE SURVEY", f"{w.name} · measured from a photo", job, business)
    d = ImageDraw.Draw(page)
    right_w = 680
    draw_wall_survey(page, (40, top, W - right_w - 40, H - 60), w, flat, unit)
    x = W - right_w
    y = top + 10
    if photo is not None:
        ph = fit_image(photo, right_w - 50, 380)
        page.paste(ph, (x, y))
        if corners:
            k = ph.width / photo.width
            pts = [(x + cx * k, y + cy * k) for cx, cy in corners]
            d.line(pts + [pts[0]], fill=BLUE, width=3)
            for i, (px, py) in enumerate(pts):
                d.ellipse([px - 12, py - 12, px + 12, py + 12], fill=BLUE, outline=(255, 255, 255), width=2)
                text(d, (px, py), str(i + 1), F(14, True), (255, 255, 255), anchor="mm")
        y += ph.height + 24
    text(d, (x, y), "Wall", F(26, True))
    y += 40
    for k, v in (("Size", u.fmt_size(w.width, w.height, unit) + f"  ({u.ft_in(w.width)} × {u.ft_in(w.height)})"),
                 ("Area", u.fmt_area_both(w.area())),
                 ("Minus openings", u.fmt_area_both(w.area() - w.openings_area())),
                 ("Behind furniture", u.fmt_area_both(w.hidden_area()))):
        text(d, (x, y), k, F(20), MUTED)
        text(d, (x + 210, y), v, F(20, True))
        y += 32
    if accuracy:
        y = para(d, (x, y + 6), accuracy, F(19), right_w - 60, (21, 128, 61)) + 4
    y += 14
    text(d, (x, y), "Items", F(26, True))
    y += 40
    hdr = ["Item", "W × H", "From left", "From floor"]
    xs = [x, x + 210, x + 420, x + 530]
    for hx, h in zip(xs, hdr):
        text(d, (hx, y), h, F(17, True), MUTED)
    y += 28
    for row in items_table(w, unit):
        for hx, v in zip(xs, row[:4]):
            text(d, (hx, y), v, F(17))
        y += 26
        if y > H - 120:
            break
    para(d, (x, H - 110), "Measured from a photo. Doors and windows (in the wall) are measured in the wall plane; "
                          "furniture shows the wall area it hides as seen from the camera. Check critical "
                          "sizes on site before cutting.", F(16), right_w - 60, MUTED)
    return page


# ======================================================================
# Test strip
# ======================================================================
def test_strip(source, job: wl.Job, centre: Tuple[float, float], size_m: Tuple[float, float] = (0.297, 0.21),
               dpi: int = 100, label: str = "") -> Image.Image:
    """A piece of the design at 100 % scale with colour control patches below it."""
    ppm = dpi / u.M_PER_IN
    w_m, h_m = size_m
    cx, cy = centre
    x0 = min(max(0.0, cx - w_m / 2), max(0.0, job.art_width - w_m))
    y0 = min(max(0.0, cy - h_m / 2), max(0.0, job.art_height - h_m))
    W, H = max(1, round(w_m * ppm)), max(1, round(h_m * ppm))
    art = source.render(x0, y0, x0 + w_m, y0 + h_m, W, H)
    bar = max(40, int(0.035 * ppm))
    page = Image.new("RGB", (W, H + bar * 2), (255, 255, 255))
    page.paste(art, (0, 0))
    d = ImageDraw.Draw(page)
    n = len(col.CONTROL_PATCHES) + 11
    pw = W / n
    for i, (lab, rgb) in enumerate(col.CONTROL_PATCHES):
        d.rectangle([i * pw, H, (i + 1) * pw - 1, H + bar], fill=rgb)
    for k in range(11):
        g = int(round(255 * (1 - k / 10)))
        i = len(col.CONTROL_PATCHES) + k
        d.rectangle([i * pw, H, (i + 1) * pw - 1, H + bar], fill=(g, g, g))
    f = F(max(10, bar * 0.36))
    info = (label or f"TEST STRIP · {job.job_no} · {job.customer} · 100 % scale · {dpi} dpi · "
            f"{w_m * 100:.1f} × {h_m * 100:.1f} cm · area {x0 * 100:.0f},{y0 * 100:.0f} cm from top-left")
    text(d, (int(0.01 * ppm), H + bar + bar * 0.25), info, f)
    return page
