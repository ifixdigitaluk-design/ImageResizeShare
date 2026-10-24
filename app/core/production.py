"""
Print production: design sources, panel files with slug and marks, output
presets and the "send to print" package.

Every panel is rendered straight from the source design on one shared pixel
grid, so neighbouring panels match exactly and the full wall is never held in
memory at once.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import sys
import zipfile
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageOps

from app.core import colour as col
from app.core import imaging as im
from app.core import units as u
from app.core import wall as wl
from app.core.paths import base_dir
from app.core.proof import get_font

Progress = Callable[[float, str], None]


class Cancelled(Exception):
    pass


# ======================================================================
# Design sources
# ======================================================================
class ImageSource:
    """A placed picture (mural)."""

    def __init__(self, img: Image.Image, job: wl.Job):
        self.img = img if img.mode in ("RGB", "RGBA") else img.convert("RGB")
        self.job = job
        self.rp = wl.resolve_placement(job, self.img.size)
        self.bg = col.rgb_of(job.placement.background or "#ffffff")
        self._flipped: Optional[Image.Image] = None
        self.ai_engine = None           # set (on a copy, see with_ai) to AI-enlarge while printing
        self.ai_art = False

    @property
    def size_px(self) -> Tuple[int, int]:
        return self.img.size

    @property
    def ppi(self) -> float:
        return self.rp.dpi

    def _src(self) -> Image.Image:
        if not self.rp.flip_h:
            return self.img
        if self._flipped is None:
            self._flipped = ImageOps.mirror(self.img)
        return self._flipped

    def render(self, x0: float, y0: float, x1: float, y1: float, out_w: int, out_h: int,
               fast: bool = False) -> Image.Image:
        out_w, out_h = max(1, int(out_w)), max(1, int(out_h))
        src = self._src()
        dw, dh = src.size
        s = self.rp.scale
        u0, u1 = (x0 - self.rp.ox) * s, (x1 - self.rp.ox) * s
        v0, v1 = (y0 - self.rp.oy) * s, (y1 - self.rp.oy) * s
        canvas = Image.new("RGB", (out_w, out_h), self.bg)
        cu0, cv0 = max(0.0, u0), max(0.0, v0)
        cu1, cv1 = min(float(dw), u1), min(float(dh), v1)
        if cu1 - cu0 <= 1e-6 or cv1 - cv0 <= 1e-6:
            return canvas
        kx, ky = out_w / (u1 - u0), out_h / (v1 - v0)
        ox0, oy0 = int(round((cu0 - u0) * kx)), int(round((cv0 - v0) * ky))
        ox1, oy1 = int(round((cu1 - u0) * kx)), int(round((cv1 - v0) * ky))
        tw, th = max(1, ox1 - ox0), max(1, oy1 - oy0)
        if fast or (kx <= 1.05 and ky <= 1.05):
            part = src.resize((tw, th), Image.Resampling.BILINEAR if fast else Image.Resampling.LANCZOS,
                              box=(cu0, cv0, cu1, cv1), reducing_gap=None if fast else 3.0)
        else:
            # enlarge: padded integer crop -> stepwise Lanczos + anti-halo sharpening -> exact window
            # (or the AI engine when printing with "AI-enhance": more context so panels join cleanly)
            use_ai = self.ai_engine is not None
            pad = 16 if use_ai else 4
            iu0, iv0 = max(0, int(math.floor(cu0)) - pad), max(0, int(math.floor(cv0)) - pad)
            iu1, iv1 = min(dw, int(math.ceil(cu1)) + pad), min(dh, int(math.ceil(cv1)) + pad)
            big_w = max(1, int(round((iu1 - iu0) * kx)))
            big_h = max(1, int(round((iv1 - iv0) * ky)))
            if big_w * big_h > max(4 * tw * th, 4_000_000):
                # a tiny design stretched over a wall: enlarging the padded crop would make a picture
                # far bigger than the output (hundreds of thousands of px wide), so make only the output
                part = src.resize((tw, th), Image.Resampling.LANCZOS, box=(cu0, cv0, cu1, cv1))
            else:
                crop = src.crop((iu0, iv0, iu1, iv1))
                method = ((im.UPSCALE_AI_ART if self.ai_art else im.UPSCALE_AI_PHOTO) if use_ai
                          else im.UPSCALE_ENHANCED)
                big = im.resample(crop, (big_w, big_h), method, ai_engine=self.ai_engine)
                bx, by = int(round((cu0 - iu0) * kx)), int(round((cv0 - iv0) * ky))
                part = big.crop((bx, by, bx + tw, by + th))
        if part.mode == "RGBA":
            canvas.paste(part.convert("RGB"), (ox0, oy0), part.getchannel("A"))
        else:
            canvas.paste(part, (ox0, oy0))
        return canvas


def with_ai(source, ai_engine, art: bool = False):
    """A copy of `source` that AI-enlarges the design while printing (no giant upscaled design is
    needed, so walls of any size get AI detail). Patterns and other sources are returned as they are.
    The studio's own source is not changed, so its screen views stay fast."""
    if ai_engine is None or not getattr(ai_engine, "available", lambda: False)():
        return source

    def copy_img(src: ImageSource) -> ImageSource:
        c = ImageSource.__new__(ImageSource)
        c.__dict__.update(src.__dict__)
        c.ai_engine, c.ai_art = ai_engine, art
        return c
    if isinstance(source, ImageSource):
        return copy_img(source)
    from app.core.layers import LayeredSource
    if isinstance(source, LayeredSource) and isinstance(source.base, ImageSource):
        return LayeredSource(copy_img(source.base), source.job, source.job_dir)
    return source


def uses_ai(source) -> bool:
    base = getattr(source, "base", source) if not isinstance(source, ImageSource) else source
    return isinstance(base, ImageSource) and base.ai_engine is not None


def make_source(job: wl.Job, design: Image.Image, tile: Optional[Image.Image] = None):
    if job.design_kind == "pattern" and tile is not None:
        from app.core.pattern import PatternSource, PatternSpec
        return PatternSource(tile, PatternSpec.from_dict(job.pattern), col.rgb_of(job.placement.background or "#fff"))
    return ImageSource(design, job)


def render_area(source, job: wl.Job, x0: float, y0: float, x1: float, y1: float, px_per_m: float,
                fast: bool = False) -> Image.Image:
    w = max(1, int(round((x1 - x0) * px_per_m)))
    h = max(1, int(round((y1 - y0) * px_per_m)))
    return source.render(x0, y0, x1, y1, w, h, fast=fast)


def render_artwork(source, job: wl.Job, max_side: int = 2400, fast: bool = True) -> Tuple[Image.Image, float]:
    """The whole artwork (with bleed) for screens. Returns (image, px per metre)."""
    ppm = max_side / max(job.art_width, job.art_height)
    return render_area(source, job, 0, 0, job.art_width, job.art_height, ppm, fast), ppm


def render_wall_area(source, job: wl.Job, max_side: int = 2400, fast: bool = False) -> Tuple[Image.Image, float]:
    """Only the wall run (no bleed) – for mockups."""
    x0, y0 = job.panels.bleed_left, job.panels.bleed_top
    ppm = max_side / max(job.run_width, job.run_height)
    return render_area(source, job, x0, y0, x0 + job.run_width, y0 + job.run_height, ppm, fast), ppm


# ======================================================================
# Output presets
# ======================================================================
@dataclass
class OutputPreset:
    name: str
    fmt: str = "TIFF"                 # TIFF / PDF / JPG / PNG
    colour: str = "sRGB IEC61966-2.1"
    intent: str = "Relative colorimetric"
    dpi: int = 100
    scale: float = 1.0                # 1 = 100 %; 0.5, 0.25, 0.1 for very large walls
    slug: bool = True                 # job / panel labels above and below the print
    marks: bool = True                # crop + overlap marks in the slug
    mirror: bool = False
    jpeg_quality: int = 95
    blank_openings: bool = False
    hot_folder: str = ""
    zip_package: bool = True
    builtin: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "OutputPreset":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


BUILTIN_PRESETS = [
    OutputPreset("Print house – TIFF RGB 100 dpi", "TIFF", "sRGB IEC61966-2.1", dpi=100, builtin=True),
    OutputPreset("Print house – TIFF RGB 150 dpi", "TIFF", "sRGB IEC61966-2.1", dpi=150, builtin=True),
    OutputPreset("Print house – PDF CMYK FOGRA39 100 dpi", "PDF", "CMYK – FOGRA39 coated (Europe)", dpi=100,
                 builtin=True),
    OutputPreset("Print house – TIFF CMYK GRACoL 100 dpi", "TIFF", "CMYK – GRACoL coated (USA)", dpi=100,
                 builtin=True),
    OutputPreset("RIP hot folder – TIFF RGB, no slug", "TIFF", "sRGB IEC61966-2.1", dpi=100, slug=False,
                 marks=False, builtin=True),
    OutputPreset("Very large wall – TIFF 50 % scale", "TIFF", "sRGB IEC61966-2.1", dpi=100, scale=0.5,
                 builtin=True),
    OutputPreset("Proof print – JPG 72 dpi", "JPG", "sRGB IEC61966-2.1", dpi=72, jpeg_quality=90,
                 zip_package=False, builtin=True),
]


def presets_file() -> Path:
    return base_dir() / "output_presets.json"


def load_presets() -> List[OutputPreset]:
    out = list(BUILTIN_PRESETS)
    try:
        data = json.loads(presets_file().read_text(encoding="utf-8"))
        for d in data:
            p = OutputPreset.from_dict(d)
            p.builtin = False
            out = [q for q in out if q.name != p.name] + [p]
    except Exception:
        pass
    return out


def save_presets(presets: List[OutputPreset]) -> None:
    data = [asdict(p) for p in presets if not p.builtin]
    presets_file().write_text(json.dumps(data, indent=1), encoding="utf-8")


def find_preset(name: str) -> OutputPreset:
    for p in load_presets():
        if p.name == name:
            return p
    return BUILTIN_PRESETS[0]


# ======================================================================
# Panel files
# ======================================================================
SLUG_MM = 30.0


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", s or "").strip().replace(" ", "-")
    return s[:40] or "job"


def panel_filename(job: wl.Job, p: wl.Panel, n: int, preset: OutputPreset) -> str:
    ext = {"TIFF": ".tif", "PDF": ".pdf", "JPG": ".jpg", "PNG": ".png"}[preset.fmt]
    scale = "" if abs(preset.scale - 1) < 1e-6 else f"_{int(round(preset.scale * 100))}pct"
    who = safe_name(job.customer)[:16].strip("-") or "job"      # short: Windows paths max out at 260 letters
    return (f"{safe_name(job.job_no)}_{who}_P{p.index:02d}-of-{n:02d}_"
            f"{p.width * 100:.1f}x{p.height * 100:.1f}cm{scale}{ext}")


def _qr(text: str, box_px: int) -> Optional[Image.Image]:
    try:
        import qrcode  # type: ignore
        q = qrcode.QRCode(border=1, box_size=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
        q.add_data(text)
        q.make(fit=True)
        img = q.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
        return img.resize((box_px, box_px), Image.Resampling.NEAREST)
    except Exception:
        return None


def render_panel(source, job: wl.Job, panel: wl.Panel, panels: List[wl.Panel], preset: OutputPreset,
                 band_rows: int = 4096, cancel: Optional[Callable[[], bool]] = None) -> Image.Image:
    """One printable panel (RGB) at the preset's resolution, with slug and marks."""
    eff_dpi = preset.dpi * preset.scale
    ppm = eff_dpi / u.M_PER_IN
    px0, px1 = int(round(panel.x0 * ppm)), int(round(panel.x1 * ppm))
    py0, py1 = int(round(panel.y0 * ppm)), int(round(panel.y1 * ppm))
    W, H = max(1, px1 - px0), max(1, py1 - py0)
    art = Image.new("RGB", (W, H), source.bg if hasattr(source, "bg") else (255, 255, 255))
    for b0 in range(0, H, band_rows):
        if cancel and cancel():
            raise Cancelled()
        b1 = min(H, b0 + band_rows)
        part = source.render(px0 / ppm, (py0 + b0) / ppm, px1 / ppm, (py0 + b1) / ppm, W, b1 - b0)
        art.paste(part, (0, b0))
    if preset.blank_openings:
        d = ImageDraw.Draw(art)
        margin = 0.05
        for wi, o in job.all_obstacles():
            if o.in_front or not o.blank_print:
                continue
            x0, y0, x1, y1 = job.obstacle_rect(wi, o)
            x0, y0, x1, y1 = x0 + margin, y0 + margin, x1 - margin, y1 - margin
            if x1 > x0 and y1 > y0:
                d.rectangle([x0 * ppm - px0, y0 * ppm - py0, x1 * ppm - px0, y1 * ppm - py0], fill=(255, 255, 255))
    if preset.mirror:
        art = ImageOps.mirror(art)
    if not preset.slug:
        return art
    return _add_slug(art, job, panel, panels, preset, ppm, eff_dpi)


def _add_slug(art: Image.Image, job: wl.Job, panel: wl.Panel, panels: List[wl.Panel], preset: OutputPreset,
              ppm: float, dpi: float) -> Image.Image:
    W, H = art.size
    mm = dpi / 25.4
    slug = max(8, int(round(SLUG_MM * mm)))
    page = Image.new("RGB", (W, H + 2 * slug), (255, 255, 255))
    page.paste(art, (0, slug))
    d = ImageDraw.Draw(page)
    n = len(panels)
    fsz = max(8, int(round(5.0 * mm)))
    f_b = get_font(fsz, bold=True)
    f_r = get_font(max(7, int(fsz * 0.8)), bold=False)
    lw = max(1, int(round(0.3 * mm)))
    top = (f"▲ TOP    {job.job_no}  ·  {job.customer or ''}  {('· ' + job.room) if job.room else ''}"
           f"    PANEL {panel.index} of {n}    {panel.width * 100:.1f} × {panel.height * 100:.1f} cm"
           f"    {dpi:.0f} dpi{'  ·  ' + str(int(preset.scale * 100)) + ' % SCALE' if preset.scale != 1 else ''}"
           f"    {preset.colour.replace('CMYK – ', '')}    {datetime.now():%d %b %Y}")
    order = "right → left" if job.panels.right_to_left else "left → right"
    bottom = (f"▼ BOTTOM    P{panel.index}/{n}    hang {order}    overlap {job.panels.overlap * 100:.1f} cm at seams"
              f"    bleed {job.panels.bleed_top * 100:.0f}/{job.panels.bleed_bottom * 100:.0f} cm top/bottom"
              f"    {job.material}")
    tx = int(4 * mm)
    d.text((tx, int(slug * 0.30)), top, font=f_b, fill=(0, 0, 0))
    d.text((tx, H + slug + int(slug * 0.30)), bottom, font=f_r, fill=(0, 0, 0))
    qr = _qr(f"{job.job_no}|P{panel.index}/{n}|{panel.width * 100:.1f}x{panel.height * 100:.1f}cm",
             max(16, int(slug * 0.8)))
    if qr is not None and W > qr.width * 4:
        page.paste(qr, (W - qr.width - int(3 * mm), H + slug + (slug - qr.height) // 2))
    if preset.marks:
        ml = int(round(8 * mm))
        for y_edge, direction in ((slug, -1), (slug + H, 1)):
            for x in (0, W - 1):
                d.line([(x, y_edge + direction * int(2 * mm)), (x, y_edge + direction * (int(2 * mm) + ml))],
                       fill=(0, 0, 0), width=lw)
        # overlap guides: where the neighbouring panel's edge lands, and the seam
        o = job.panels.overlap
        guides = []
        if panel.seam_left is not None:
            guides += [((panel.seam_left - panel.x0) * ppm, "seam"), (o * ppm, "edge")]
        if panel.seam_right is not None:
            guides += [((panel.seam_right - panel.x0) * ppm, "seam"), (W - o * ppm, "edge")]
        for gx, kind in guides:
            if preset.mirror:
                gx = W - gx
            gx = int(round(gx))
            length = int(6 * mm) if kind == "seam" else int(4 * mm)
            for y_edge, direction in ((slug, -1), (slug + H, 1)):
                y_a = y_edge + direction * int(1 * mm)
                y_b = y_a + direction * length
                if kind == "seam":
                    d.polygon([(gx, y_a), (gx - int(1.5 * mm), y_b), (gx + int(1.5 * mm), y_b)], fill=(220, 0, 0))
                else:
                    d.line([(gx, y_a), (gx, y_b)], fill=(0, 0, 0), width=lw)
    return page


def save_image(img: Image.Image, path: Path, preset: OutputPreset) -> None:
    prof = col.find_profile(preset.colour) or col.find_profile("sRGB IEC61966-2.1")
    out = img
    icc = None
    if prof is not None and prof.colour_space == "CMYK":
        out = col.to_cmyk(img, prof, preset.intent)
        icc = prof.path.read_bytes()
    elif prof is not None:
        out = col.to_rgb_profile(img, prof, preset.intent)
        icc = prof.path.read_bytes()
    dpi = preset.dpi * preset.scale
    path.parent.mkdir(parents=True, exist_ok=True)
    if preset.fmt == "TIFF":
        kw = dict(compression="tiff_lzw", dpi=(dpi, dpi))
        if icc:
            kw["icc_profile"] = icc
        raw = out.width * out.height * len(out.getbands())
        if raw > 3_500_000_000:
            kw["big_tiff"] = True
        out.save(path, "TIFF", **kw)
    elif preset.fmt == "PDF":
        out.save(path, "PDF", resolution=float(dpi), quality=preset.jpeg_quality)
    elif preset.fmt == "PNG":
        kw = dict(dpi=(dpi, dpi), compress_level=6)
        if icc and out.mode != "CMYK":
            kw["icc_profile"] = icc
        out.convert("RGB").save(path, "PNG", **kw)
    else:
        from PIL import ImageFile
        ImageFile.MAXBLOCK = max(ImageFile.MAXBLOCK, out.width * out.height * 4 + (1 << 20))
        kw = dict(quality=preset.jpeg_quality, dpi=(dpi, dpi), subsampling=0, optimize=True)
        if icc:
            kw["icc_profile"] = icc
        out.save(path, "JPEG", **kw)


def estimate_bytes(job: wl.Job, preset: OutputPreset) -> int:
    ppm = preset.dpi * preset.scale / u.M_PER_IN
    panels = wl.compute_panels(job)
    raw = sum(p.width * ppm * (p.height * ppm + 2 * SLUG_MM / 1000 * ppm) for p in panels)
    ch = 4 if "CMYK" in preset.colour else 3
    ratio = {"TIFF": 0.6, "PDF": 0.15, "JPG": 0.12, "PNG": 0.5}[preset.fmt]
    return int(raw * ch * ratio)


# ======================================================================
# Package
# ======================================================================
@dataclass
class PackageResult:
    folder: Path
    files: List[Path] = field(default_factory=list)
    zip_path: Optional[Path] = None
    hot_folder_copy: Optional[Path] = None


def job_ticket(job: wl.Job, preset: OutputPreset, panels: List[wl.Panel], files: List[str], ppi: float) -> dict:
    return {
        "job_no": job.job_no, "customer": job.customer, "phone": job.phone, "room": job.room,
        "address": job.address, "created": datetime.now().isoformat(timespec="seconds"),
        "walls": [{"name": w.name, "width_m": round(w.width, 4), "height_m": round(w.height, 4),
                   "corner_after": w.corner_after} for w in job.walls],
        "print_area_m": [round(job.art_width, 4), round(job.art_height, 4)],
        "bleed_cm": {k: round(getattr(job.panels, f"bleed_{k}") * 100, 2) for k in ("top", "bottom", "left", "right")},
        "panels": [{"no": p.index, "width_cm": round(p.width * 100, 2), "length_cm": round(p.height * 100, 2),
                    "file": f} for p, f in zip(panels, files)],
        "overlap_cm": round(job.panels.overlap * 100, 2), "media_width_cm": round(job.panels.media_width * 100, 2),
        "hang_order": "right to left" if job.panels.right_to_left else "left to right",
        "material": job.material, "finish": job.finish,
        "output": {"preset": preset.name, "format": preset.fmt, "colour": preset.colour, "intent": preset.intent,
                   "dpi": preset.dpi, "scale": preset.scale, "slug": preset.slug, "mirror": preset.mirror},
        "design_ppi_at_full_size": round(ppi, 1),
        "proof_version": job.proof_version, "approved_by": job.approved_by, "approved_on": job.approved_on,
        "notes": job.notes,
    }


def ticket_text(t: dict) -> str:
    lines = [f"JOB TICKET  {t['job_no']}", "=" * 60,
             f"Customer : {t['customer']}  {t.get('phone', '')}", f"Room     : {t['room']}",
             f"Address  : {t['address']}", ""]
    for w in t["walls"]:
        lines.append(f"Wall     : {w['name']}  {w['width_m']:.3f} × {w['height_m']:.3f} m  (corner after: {w['corner_after']})")
    b = t["bleed_cm"]
    lines += ["", f"Print area incl. bleed : {t['print_area_m'][0]:.3f} × {t['print_area_m'][1]:.3f} m",
              f"Bleed (cm)             : top {b['top']}, bottom {b['bottom']}, left {b['left']}, right {b['right']}",
              f"Media width            : {t['media_width_cm']} cm   Overlap at seams: {t['overlap_cm']} cm",
              f"Hang order             : {t['hang_order']}",
              f"Material / finish      : {t['material']} / {t['finish']}",
              f"Output                 : {t['output']['format']}  {t['output']['colour']}  {t['output']['dpi']} dpi"
              f"  scale {int(t['output']['scale'] * 100)} %",
              f"Design resolution      : {t['design_ppi_at_full_size']} ppi at full size",
              f"Proof                  : v{t['proof_version']}  approved by {t['approved_by'] or '—'} {t['approved_on'] or ''}",
              "", "PANELS"]
    for p in t["panels"]:
        lines.append(f"  P{p['no']:02d}  {p['width_cm']:>7.2f} × {p['length_cm']:.2f} cm   {p['file']}")
    if t.get("notes"):
        lines += ["", "NOTES", t["notes"]]
    return "\n".join(lines) + "\n"


README_TXT = """HOW TO PRINT THIS JOB
=====================
1. Print every file in /panels at 100 % (no "fit to page"). The DPI is stored in each file.
   If the files say "50 % SCALE", print at 200 %.
2. Each panel has a white strip at the top (▲ TOP) and bottom with the job and panel number,
   crop marks and overlap guides (red triangles = seam line). Trim the strips before hanging.
3. Hang in the order shown on the installation sheet. Neighbouring panels overlap by the
   amount in the job ticket; line the edge of the next panel up with the black overlap tick.
4. Colour: the files carry their ICC profile. Print with that profile (or convert in the RIP).
"""


WARN_PANEL_PX = 200e6     # above this a panel needs a lot of memory and time


def total_ram() -> int:
    """This PC's memory in bytes (0 if unknown)."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ave", ctypes.c_ulonglong)]
            m = MS()
            m.len = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.total)
        import os
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except Exception:
        return 0


def max_panel_px() -> float:
    """The biggest panel file this PC can make. Each panel is made in memory (RGB panel + CMYK copy:
    about 7 bytes a pixel at the peak), so this keeps a panel to about a third of the memory, leaving
    room for the rest of the app. 8 GB → 420 MP, 16 GB → 840 MP; at least 300 MP."""
    return max(300e6, total_ram() / 20)


MAX_PANEL_PX = max_panel_px()


def biggest_panel(job: wl.Job, preset: OutputPreset) -> Tuple[int, int]:
    """Pixel size of the biggest panel file at this preset."""
    ppm = preset.dpi * preset.scale / u.M_PER_IN
    best = (0, 0)
    for p in wl.compute_panels(job):
        w, h = int(round((p.x1 - p.x0) * ppm)), int(round((p.y1 - p.y0) * ppm))
        if w * h > best[0] * best[1]:
            best = (w, h)
    return best


def panel_too_big_text(job: wl.Job, preset: OutputPreset) -> Optional[str]:
    """A message when a panel can't be made in one file at this preset, else None."""
    w, h = biggest_panel(job, preset)
    if w * h <= MAX_PANEL_PX:
        return None
    k = (MAX_PANEL_PX / (w * h)) ** 0.5
    dpi = max(10, int(preset.dpi * preset.scale * k) // 10 * 10)
    scale = next((sc for sc in (0.5, 0.25, 0.1) if sc <= k * preset.scale), 0.1)
    return (f"The biggest panel would be {w:,} × {h:,} px ({w * h / 1e6:,.0f} MP) with the "
            f"“{preset.name}” preset – too big to make as one file on a PC. Choose a preset with "
            f"{dpi} dpi or less, or a {int(scale * 100)} % scale preset "
            "(Presets › scale: the print shop prints it bigger).")


def make_package(job: wl.Job, job_dir: Path, source, preset: OutputPreset, *, installer_sheet: bool = True,
                 include_proof: bool = True, test_strip: Optional[Image.Image] = None,
                 preflight_text: str = "", business: Optional[dict] = None,
                 progress: Optional[Progress] = None, cancel: Optional[Callable[[], bool]] = None,
                 out_dir: Optional[Path] = None) -> PackageResult:
    from app.core import documents as docs
    too_big = panel_too_big_text(job, preset)
    if too_big:
        raise ValueError(too_big)
    panels = wl.compute_panels(job)
    n = len(panels)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    folder = (out_dir or (job_dir / "print")) / f"{safe_name(job.job_no)}_{stamp}_proof-v{job.proof_version}"
    (folder / "panels").mkdir(parents=True, exist_ok=True)
    res = PackageResult(folder)
    names = []
    steps = n + 3
    ai_note = " (AI-enhancing, this takes longer)" if uses_ai(source) else ""
    for k, p in enumerate(panels):
        if progress:
            progress(k / steps, f"Panel {p.index} of {n}…{ai_note}")
        if cancel and cancel():
            raise Cancelled()
        # with AI, a panel is made in one go (up to 80 MP) so the AI sees the whole piece: no joins
        eff = preset.dpi * preset.scale / u.M_PER_IN
        one_go = uses_ai(source) and (p.x1 - p.x0) * (p.y1 - p.y0) * eff * eff <= 80e6
        img = render_panel(source, job, p, panels, preset, cancel=cancel,
                           band_rows=1 << 30 if one_go else 4096)
        name = panel_filename(job, p, n, preset)
        path = folder / "panels" / name
        save_image(img, path, preset)
        names.append(name)
        res.files.append(path)
        del img
    if progress:
        progress(n / steps, "Installation sheet…")
    if installer_sheet:
        pages = docs.installer_sheet(job, source, panels, names, business or {})
        p_pdf = folder / "installation_sheet.pdf"
        pages[0].save(p_pdf, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
        pages[0].convert("RGB").save(folder / "installation_sheet.png", "PNG")
        res.files += [p_pdf, folder / "installation_sheet.png"]
    if include_proof and job.proof_file:
        src = job_dir / job.proof_file
        if src.is_file():
            dst = folder / ("approved_" + src.name)
            shutil.copyfile(src, dst)
            res.files.append(dst)
    if test_strip is not None:
        ts = folder / f"{safe_name(job.job_no)}_TEST-STRIP_100pct.tif"
        save_image(test_strip, ts, preset if preset.fmt == "TIFF" else OutputPreset("ts", "TIFF", preset.colour,
                                                                                       dpi=preset.dpi))
        res.files.append(ts)
    t = job_ticket(job, preset, panels, names, getattr(source, "ppi", 0.0))
    (folder / "job_ticket.json").write_text(json.dumps(t, indent=1), encoding="utf-8")
    (folder / "job_ticket.txt").write_text(ticket_text(t), encoding="utf-8")
    (folder / "README.txt").write_text(README_TXT, encoding="utf-8")
    if preflight_text:
        (folder / "preflight_report.txt").write_text(preflight_text, encoding="utf-8")
        res.files.append(folder / "preflight_report.txt")
    res.files += [folder / "job_ticket.json", folder / "job_ticket.txt", folder / "README.txt"]
    if progress:
        progress((n + 1) / steps, "Packing…")
    if preset.zip_package:
        zp = folder.with_suffix(".zip")
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for f in sorted(folder.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(folder.parent))
        res.zip_path = zp
    if preset.hot_folder:
        hf = Path(preset.hot_folder)
        if hf.is_dir():
            dst = hf / folder.name
            dst.mkdir(parents=True, exist_ok=True)
            for f in (folder / "panels").iterdir():
                shutil.copyfile(f, dst / f.name)
            shutil.copyfile(folder / "job_ticket.txt", dst / "job_ticket.txt")
            res.hot_folder_copy = dst
    if progress:
        progress(1.0, "Done")
    return res
