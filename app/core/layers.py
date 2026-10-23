"""
Text and logos on top of the design (names in kids' rooms, café slogans, shop logos).

A layer is a dict stored in Job.layers:
  kind      "text" or "image"
  text      the words (new lines allowed)              – text
  font      font name (see list_fonts())               – text
  colour    "#rrggbb"                                   – text
  outline   outline colour or "" for none              – text
  shadow    True / False                               – text
  file      job-relative path of a PNG / JPG           – image
  x, y      left edge and bottom edge, metres from the left of the wall run and from the floor
  h         height in metres (the width follows the text / logo shape)
  opacity   0–1
  id        short id

Layers are drawn by LayeredSource on every render of the design, so they appear on
the wall plan, proofs, mockups and in the print files at full resolution.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.core import wall as wl
from app.core.paths import resource_path

_FONTS: Optional[Dict[str, str]] = None
_SIZE_REF = 200          # font size used to measure the text shape


def _font_dirs() -> List[Path]:
    dirs = [resource_path("assets/fonts")]
    if sys.platform.startswith("win"):
        dirs.append(Path("C:/Windows/Fonts"))
        local = Path.home() / "AppData/Local/Microsoft/Windows/Fonts"
        dirs.append(local)
    elif sys.platform == "darwin":
        dirs += [Path("/Library/Fonts"), Path("/System/Library/Fonts"), Path.home() / "Library/Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path.home() / ".fonts"]
    return dirs


def list_fonts() -> Dict[str, str]:
    """Font name -> file. Bundled Liberation Sans first, then the computer's own fonts.

    Reading every font file is slow on a PC with hundreds of fonts, so the names are kept
    in a small cache file and only new fonts are read.
    """
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    import json
    cache_file = None
    cache: Dict[str, list] = {}
    try:
        from app.core.paths import base_dir
        cache_file = base_dir() / "fonts_cache.json"
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    new_cache: Dict[str, list] = {}
    out: Dict[str, str] = {}
    for d in _font_dirs():
        if not d.is_dir():
            continue
        try:
            files = sorted(list(d.rglob("*.ttf")) + list(d.rglob("*.otf")) + list(d.rglob("*.TTF")))[:1500]
        except OSError:
            continue
        for f in files:
            key = str(f)
            try:
                stamp = f.stat().st_mtime
            except OSError:
                continue
            hit = cache.get(key)
            if hit and abs(hit[0] - stamp) < 1:
                fam, style = hit[1], hit[2]
            else:
                try:
                    fam, style = ImageFont.truetype(key, 12).getname()
                except Exception:
                    continue
            new_cache[key] = [stamp, fam, style]
            if not fam:
                continue
            name = fam if style in ("Regular", "Book", "Normal", "Roman") else f"{fam} {style}"
            out.setdefault(name, key)
    if cache_file is not None and new_cache != cache:
        try:
            cache_file.write_text(json.dumps(new_cache), encoding="utf-8")
        except Exception:
            pass
    _FONTS = dict(sorted(out.items(), key=lambda kv: (not kv[0].startswith("Liberation Sans"), kv[0].lower())))
    return _FONTS


def default_font() -> str:
    fonts = list_fonts()
    for n in ("Liberation Sans Bold", "Arial Bold", "Segoe UI Bold"):
        if n in fonts:
            return n
    return next(iter(fonts), "")


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = list_fonts().get(name) or list_fonts().get(default_font())
    try:
        return ImageFont.truetype(path, max(4, int(size)))
    except Exception:
        return ImageFont.load_default()


def new_text_layer(job: wl.Job, text: str = "Your text") -> dict:
    h = round(min(0.4, max(0.08, job.run_height * 0.08)), 3)
    lay = {"id": uuid.uuid4().hex[:8], "kind": "text", "text": text, "font": default_font(), "colour": "#ffffff",
           "outline": "#1e293b", "shadow": True, "x": 0.0, "y": round(job.run_height * 0.6, 3), "h": h,
           "opacity": 1.0}
    lay["x"] = round(max(0.0, (job.run_width - h * aspect(lay)) / 2), 3)
    return lay


def new_image_layer(job: wl.Job, rel_file: str, size: Tuple[int, int]) -> dict:
    h = round(min(1.0, job.run_height * 0.25), 3)
    lay = {"id": uuid.uuid4().hex[:8], "kind": "image", "file": rel_file, "x": 0.0, "y": round(job.run_height * 0.5, 3),
           "h": h, "opacity": 1.0, "_aspect": size[0] / max(1, size[1])}
    lay["x"] = round(max(0.0, (job.run_width - h * lay["_aspect"]) / 2), 3)
    return lay


def _text_box(lay: dict, size: int):
    f = _font(lay.get("font", ""), size)
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    stroke = max(1, size // 18) if lay.get("outline") else 0
    box = d.multiline_textbbox((0, 0), lay.get("text") or " ", font=f, align="center", stroke_width=stroke,
                               spacing=int(size * 0.15))
    return f, box, stroke


def aspect(lay: dict, job_dir: Optional[Path] = None) -> float:
    """Width ÷ height of a layer."""
    if lay.get("kind") == "image":
        a = lay.get("_aspect")
        if not a and job_dir is not None and (job_dir / lay.get("file", "")).is_file():
            with Image.open(job_dir / lay["file"]) as im:
                a = im.width / max(1, im.height)
                lay["_aspect"] = a
        return float(a or 1.0)
    _f, (x0, y0, x1, y1), _s = _text_box(lay, _SIZE_REF)
    return max(0.05, (x1 - x0) / max(1, y1 - y0))


def rect(job: wl.Job, lay: dict, job_dir: Optional[Path] = None) -> Tuple[float, float, float, float]:
    """Layer box in artwork coordinates (x0, y0, x1, y1), y down."""
    h = max(0.01, float(lay.get("h", 0.2)))
    w = h * aspect(lay, job_dir)
    x0 = job.panels.bleed_left + float(lay.get("x", 0.0))
    y1 = job.floor_y - float(lay.get("y", 0.0))
    return x0, y1 - h, x0 + w, y1


def render_layer(lay: dict, w_px: int, h_px: int, job_dir: Optional[Path] = None) -> Image.Image:
    """The layer as RGBA at exactly w_px × h_px."""
    w_px, h_px = max(1, int(w_px)), max(1, int(h_px))
    op = float(lay.get("opacity", 1.0))
    if lay.get("kind") == "image":
        path = (job_dir / lay.get("file", "")) if job_dir else None
        if not path or not path.is_file():
            return Image.new("RGBA", (w_px, h_px), (0, 0, 0, 0))
        with Image.open(path) as im:
            im.draft("RGBA", (w_px, h_px))
            src = ImageOps.exif_transpose(im).convert("RGBA")
        if lay.get("key_white"):          # logo on a white background: make the white see-through
            import numpy as np
            a = np.asarray(src, dtype=np.float32)
            dist = np.sqrt(((255.0 - a[:, :, :3]) ** 2).sum(axis=2))
            alpha = np.clip((dist - 18.0) / 40.0, 0, 1) * a[:, :, 3]
            src.putalpha(Image.fromarray(alpha.astype("uint8")))
        out = src.resize((w_px, h_px), Image.Resampling.LANCZOS)
    else:
        # draw big enough, then scale to the exact box
        _f0, ref_box, _s0 = _text_box(lay, _SIZE_REF)
        size = min(4000, max(8, int(_SIZE_REF * h_px / max(1, ref_box[3] - ref_box[1]))))
        f, (x0, y0, x1, y1), stroke = _text_box(lay, size)
        pad = int(size * 0.12) if lay.get("shadow") else 2
        canvas = Image.new("RGBA", (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), (0, 0, 0, 0))
        d = ImageDraw.Draw(canvas)
        pos = (pad - x0, pad - y0)
        kw = dict(font=f, align="center", spacing=int(size * 0.15))
        if lay.get("shadow"):
            sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).multiline_text((pos[0] + size * 0.04, pos[1] + size * 0.05), lay.get("text") or " ",
                                              fill=(0, 0, 0, 150), stroke_width=stroke, stroke_fill=(0, 0, 0, 150),
                                              **kw)
            canvas = Image.alpha_composite(canvas, sh.filter(ImageFilter.GaussianBlur(size * 0.03)))
            d = ImageDraw.Draw(canvas)
        colour = lay.get("colour") or "#ffffff"
        if lay.get("outline"):
            d.multiline_text(pos, lay.get("text") or " ", fill=colour, stroke_width=stroke,
                             stroke_fill=lay["outline"], **kw)
        else:
            d.multiline_text(pos, lay.get("text") or " ", fill=colour, **kw)
        canvas = canvas.crop((pad, pad, canvas.width - pad, canvas.height - pad))
        out = canvas.resize((w_px, h_px), Image.Resampling.LANCZOS)
    if op < 0.999:
        a = out.getchannel("A").point(lambda v: int(v * op))
        out.putalpha(a)
    return out


class LayeredSource:
    """Wraps a design source (ImageSource / PatternSource) and draws the layers on top."""

    def __init__(self, base, job: wl.Job, job_dir: Optional[Path]):
        self.base = base
        self.job = job
        self.job_dir = job_dir
        self._cache: Dict[tuple, Image.Image] = {}

    def __getattr__(self, name):          # ppi, size_px, rp, bg … come from the design
        return getattr(self.base, name)

    def render(self, x0: float, y0: float, x1: float, y1: float, out_w: int, out_h: int, fast: bool = False):
        img = self.base.render(x0, y0, x1, y1, out_w, out_h, fast=fast)
        if not self.job.layers:
            return img
        sx = out_w / max(1e-9, x1 - x0)
        sy = out_h / max(1e-9, y1 - y0)
        base = img.convert("RGBA")
        for lay in self.job.layers:
            lx0, ly0, lx1, ly1 = rect(self.job, lay, self.job_dir)
            if lx1 <= x0 or lx0 >= x1 or ly1 <= y0 or ly0 >= y1:
                continue
            w_px, h_px = int(round((lx1 - lx0) * sx)), int(round((ly1 - ly0) * sy))
            if w_px < 1 or h_px < 1:
                continue
            key = (lay.get("id"), repr(sorted((k, v) for k, v in lay.items() if not k.startswith("_"))), w_px, h_px)
            li = self._cache.get(key)
            if li is None:
                li = render_layer(lay, w_px, h_px, self.job_dir)
                if len(self._cache) > 6:
                    self._cache.clear()
                self._cache[key] = li
            base.paste(li, (int(round((lx0 - x0) * sx)), int(round((ly0 - y0) * sy))), li)
        return base.convert("RGB")
