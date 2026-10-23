"""
Installation tools: WhatsApp reminder messages and before / after posts for social media.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.core import wall as wl
from app.core.proof import get_font

SIZES = {"square": (1080, 1080), "story": (1080, 1920), "landscape": (1200, 628)}
SIZE_NAMES = {"square": "Square 1080 × 1080 (Instagram / Facebook post)",
              "story": "Story 1080 × 1920 (WhatsApp Status / Reels)",
              "landscape": "Landscape 1200 × 628 (Facebook / website)"}

DEFAULT_REMINDER = (
    "Hello {customer}, this is {business}.\n"
    "Reminder: we are fitting your wallpaper on {day} {date}{at_time}.\n"
    "Please clear about 1 metre in front of the wall and take down pictures and shelves if you can.\n"
    "Reply OK to confirm, or let us know if you need another time. Thank you!")

DEFAULT_CAPTION = ("Another wall transformed ✨ {room_text}custom {material} by {business}. "
                   "Measured, printed and fitted for {area}.\n"
                   "Want one too? Message us{phone_text}.\n#wallpaper #mural #interiordesign #homedecor")


def nice_date(iso: str) -> tuple:
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return "", ""
    return d.strftime("%A"), d.strftime("%d %B %Y").lstrip("0")


def reminder_text(job: wl.Job, business: Dict[str, str], template: str = DEFAULT_REMINDER) -> str:
    day, dt = nice_date(job.install_date)
    vals = {
        "customer": (job.customer or "").split(" ")[0] if job.customer else "there",
        "business": business.get("name") or "your wallpaper fitter",
        "day": day, "date": dt or "the agreed day",
        "at_time": f" at {job.install_time}" if job.install_time else "",
        "time": job.install_time, "room": job.room or "", "job_no": job.job_no,
        "installer": job.installer or "", "phone": business.get("phone", ""),
    }
    try:
        return template.format(**vals)
    except (KeyError, IndexError, ValueError):
        return template


def caption_text(job: wl.Job, business: Dict[str, str], template: str = DEFAULT_CAPTION) -> str:
    vals = {"room_text": f"{job.room} · " if job.room else "", "material": job.material.split(" (")[0].lower(),
            "business": business.get("name") or "us", "area": f"{job.wall_area():.1f} m² of wall",
            "phone_text": f" on {business['phone']}" if business.get("phone") else "", "customer": job.customer}
    try:
        return template.format(**vals)
    except (KeyError, IndexError, ValueError):
        return template


def upcoming(summaries, today: Optional[date] = None):
    """Jobs with an installation date (soonest first) and jobs ready to book (approved / printing / printed)."""
    today = today or date.today()
    dated, to_book = [], []
    for s in summaries:
        if s.status in ("Completed", "Cancelled"):
            continue
        if s.install_date:
            try:
                d = datetime.strptime(s.install_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if d >= today or s.status not in ("Installed",):
                dated.append((d, s))
        elif s.status in ("Approved", "Printing", "Printed"):
            to_book.append(s)
    dated.sort(key=lambda t: (t[0], t[1].install_time or "99"))
    return dated, to_book


def _fit(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (max(1, w), max(1, h)), Image.Resampling.LANCZOS)


def _chip(d: ImageDraw.ImageDraw, xy, text: str, size: int, bg=(255, 255, 255), fg=(15, 23, 42)):
    f = get_font(size, True)
    x, y = xy
    bb = d.textbbox((0, 0), text, font=f)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    pad = int(size * 0.55)
    d.rounded_rectangle([x, y, x + w + 2 * pad, y + h + 2 * pad], radius=int(size * 0.6), fill=bg)
    d.text((x + pad - bb[0], y + pad - bb[1]), text, font=f, fill=fg)


def make_post(after: Image.Image, business: Dict[str, str], size: str = "square",
              before: Optional[Image.Image] = None, title: str = "", accent=(26, 115, 232)) -> Image.Image:
    """A ready-to-share picture: before/after (or after only) with your name and phone."""
    W, H = SIZES.get(size, SIZES["square"])
    page = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(page)
    foot = int(H * (0.13 if size != "story" else 0.09))
    area_h = H - foot
    s = max(18, W // 36)
    if before is not None:
        if W >= H * 1.4:                       # landscape: side by side
            half = W // 2
            page.paste(_fit(before, half - 2, area_h), (0, 0))
            page.paste(_fit(after, W - half - 2, area_h), (half + 2, 0))
            _chip(d, (int(s * 0.8), int(s * 0.8)), "BEFORE", s)
            _chip(d, (half + int(s * 0.8), int(s * 0.8)), "AFTER", s, accent, (255, 255, 255))
        else:                                  # square / story: one above the other
            half = area_h // 2
            page.paste(_fit(before, W, half - 3), (0, 0))
            page.paste(_fit(after, W, area_h - half - 3), (0, half + 3))
            _chip(d, (int(s * 0.8), int(s * 0.8)), "BEFORE", s)
            _chip(d, (int(s * 0.8), half + 3 + int(s * 0.8)), "AFTER", s, accent, (255, 255, 255))
    else:
        page.paste(_fit(after, W, area_h), (0, 0))
        if title:
            # soft dark band behind the title
            band_h = int(s * 3.2)
            band = page.crop((0, area_h - band_h, W, area_h)).filter(ImageFilter.GaussianBlur(2))
            dark = Image.new("RGB", band.size, (0, 0, 0))
            page.paste(Image.blend(band, dark, 0.45), (0, area_h - band_h))
    if title:
        f = get_font(int(s * 1.25), True)
        tb = d.textbbox((0, 0), title, font=f)
        tx = (W - (tb[2] - tb[0])) // 2
        ty = area_h - int(s * 2.3)
        d.text((tx + 2, ty + 2), title, font=f, fill=(0, 0, 0))
        d.text((tx, ty), title, font=f, fill=(255, 255, 255))
    # footer: logo, name, phone
    d.rectangle([0, area_h, W, H], fill=(15, 23, 42))
    x = int(s * 1.0)
    logo = business.get("logo")
    if logo and Path(logo).is_file():
        try:
            with Image.open(logo) as lg:
                lg = lg.convert("RGBA")
                lg.thumbnail((int(foot * 1.6), int(foot * 0.7)))
                page.paste(lg, (x, area_h + (foot - lg.height) // 2), lg)
                x += lg.width + int(s * 0.8)
        except Exception:
            pass
    name = business.get("name") or "Custom wallpaper & murals"
    f1 = get_font(int(s * 1.15), True)
    f2 = get_font(int(s * 0.85), False)
    contact = "  ·  ".join(v for v in (business.get("phone"), business.get("website")) if v)
    if contact:
        d.text((x, area_h + foot * 0.22), name, font=f1, fill=(255, 255, 255))
        d.text((x, area_h + foot * 0.58), contact, font=f2, fill=(203, 213, 225))
    else:
        d.text((x, area_h + foot * 0.36), name, font=f1, fill=(255, 255, 255))
    return page
