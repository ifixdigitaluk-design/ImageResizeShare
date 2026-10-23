"""
Colour management and colour tools.

* ICC profiles: free profiles in assets/icc (sRGB, Adobe RGB, FOGRA39/29,
  GRACoL, SWOP – CC0 / CGATS-derived), plus the printer / media profiles the
  user adds (from their printer or RIP supplier).
* Soft-proof, out-of-gamut map, CMYK conversion.
* Palette extraction, colour matching (CIEDE2000) against palettes the user
  imports (CSV / JSON), colour replacement and colourways.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageCms

from app.core.paths import resource_path, sub_dir

INTENTS = {"Perceptual": 0, "Relative colorimetric": 1, "Saturation": 2, "Absolute colorimetric": 3}

BUNDLED = {   # file: display name
    "sRGB.icc": "sRGB IEC61966-2.1",
    "AdobeRGB1998.icc": "Adobe RGB (1998)",
    "FOGRA39L_coated.icc": "CMYK – FOGRA39 coated (Europe)",
    "FOGRA29L_uncoated.icc": "CMYK – FOGRA29 uncoated (Europe)",
    "GRACoL_TR006_coated.icc": "CMYK – GRACoL coated (USA)",
    "SWOP_TR005_coated_5.icc": "CMYK – SWOP coated (USA)",
}


# ======================================================================
# Profiles
# ======================================================================
@dataclass
class Profile:
    name: str
    path: Path
    colour_space: str        # RGB / CMYK / GRAY …
    user: bool = False


def user_profile_dir() -> Path:
    return sub_dir("Profiles")


def list_profiles() -> List[Profile]:
    out: List[Profile] = []
    for f, name in BUNDLED.items():
        p = resource_path(f"assets/icc/{f}")
        if p.is_file():
            out.append(Profile(name, p, "CMYK" if name.startswith("CMYK") else "RGB"))
    try:
        for p in sorted(user_profile_dir().glob("*.ic*")):
            try:
                prof = ImageCms.getOpenProfile(str(p))
                desc = ImageCms.getProfileDescription(prof).strip() or p.stem
                cs = prof.profile.xcolor_space.strip()
                out.append(Profile(f"{desc} (yours)", p, cs, True))
            except Exception:
                continue
    except Exception:
        pass
    return out


def find_profile(name: str) -> Optional[Profile]:
    for p in list_profiles():
        if p.name == name:
            return p
    return None


def add_user_profile(path: str | Path) -> Profile:
    src = Path(path)
    prof = ImageCms.getOpenProfile(str(src))         # raises if not a valid profile
    dst = user_profile_dir() / src.name
    shutil.copyfile(src, dst)
    desc = ImageCms.getProfileDescription(prof).strip() or src.stem
    return Profile(f"{desc} (yours)", dst, prof.profile.xcolor_space.strip(), True)


_srgb_cache = None


def srgb_profile():
    global _srgb_cache
    if _srgb_cache is None:
        p = resource_path("assets/icc/sRGB.icc")
        _srgb_cache = ImageCms.getOpenProfile(str(p)) if p.is_file() else ImageCms.createProfile("sRGB")
    return _srgb_cache


def srgb_bytes() -> Optional[bytes]:
    p = resource_path("assets/icc/sRGB.icc")
    return p.read_bytes() if p.is_file() else None


def to_srgb(img: Image.Image, icc: Optional[bytes]) -> Image.Image:
    """Convert an image with an embedded profile (Adobe RGB, Display P3, CMYK …) to sRGB."""
    if not icc:
        return img
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if "srgb" in ImageCms.getProfileDescription(src).lower():
            return img
        alpha = img.getchannel("A") if img.mode == "RGBA" else None
        mode = img.mode if img.mode in ("RGB", "CMYK", "L") else "RGB"
        base = img.convert(mode)
        out = ImageCms.profileToProfile(base, src, srgb_profile(), outputMode="RGB",
                                        renderingIntent=0)
        if alpha is not None:
            out.putalpha(alpha)
        return out
    except Exception:
        return img


_tf_cache: Dict[tuple, object] = {}


def _transform(key, factory):
    t = _tf_cache.get(key)
    if t is None:
        t = factory()
        if len(_tf_cache) > 16:
            _tf_cache.clear()
        _tf_cache[key] = t
    return t


def to_cmyk(img: Image.Image, profile: Profile, intent: str = "Relative colorimetric",
            bpc: bool = True) -> Image.Image:
    dst = ImageCms.getOpenProfile(str(profile.path))
    flags = ImageCms.Flags.BLACKPOINTCOMPENSATION if bpc else ImageCms.Flags.NONE
    tf = _transform(("cmyk", str(profile.path), intent, bpc), lambda: ImageCms.buildTransform(
        srgb_profile(), dst, "RGB", "CMYK", renderingIntent=INTENTS[intent], flags=flags))
    return ImageCms.applyTransform(img.convert("RGB"), tf)


def to_rgb_profile(img: Image.Image, profile: Profile, intent: str = "Relative colorimetric") -> Image.Image:
    if "srgb" in profile.name.lower():
        return img.convert("RGB")
    dst = ImageCms.getOpenProfile(str(profile.path))
    tf = _transform(("rgb", str(profile.path), intent), lambda: ImageCms.buildTransform(
        srgb_profile(), dst, "RGB", "RGB", renderingIntent=INTENTS[intent]))
    return ImageCms.applyTransform(img.convert("RGB"), tf)


def soft_proof(img: Image.Image, profile: Profile, intent: str = "Relative colorimetric",
               paper_white: bool = False) -> Image.Image:
    """How the image will look printed with `profile` (shown on an sRGB screen)."""
    if profile.colour_space not in ("CMYK", "RGB") or "srgb" in profile.name.lower():
        return img.convert("RGB")
    prof = ImageCms.getOpenProfile(str(profile.path))
    flags = ImageCms.Flags.SOFTPROOFING | ImageCms.Flags.BLACKPOINTCOMPENSATION
    tf = _transform(("proof", str(profile.path), intent, paper_white), lambda: ImageCms.buildProofTransform(
        srgb_profile(), srgb_profile(), prof, "RGB", "RGB", renderingIntent=0,
        proofRenderingIntent=3 if paper_white else INTENTS[intent], flags=flags))
    return ImageCms.applyTransform(img.convert("RGB"), tf)


# ======================================================================
# Lab / ΔE
# ======================================================================
def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (…, 3) uint8/float 0-255 -> CIE Lab D65 (…, 3)."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ M.T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def lab_to_srgb(lab: np.ndarray) -> np.ndarray:
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    e, k = 216 / 24389, 24389 / 27

    def inv(f):
        return np.where(f ** 3 > e, f ** 3, (116 * f - 16) / k)
    xyz = np.stack([inv(fx), np.where(lab[..., 0] > k * e, fy ** 3, lab[..., 0] / k), inv(fz)], axis=-1)
    xyz *= np.array([0.95047, 1.0, 1.08883])
    M = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560],
                  [0.0556434, -0.2040259, 1.0572252]])
    c = xyz @ M.T
    c = np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.clip(c, 0, None) ** (1 / 2.4) - 0.055)
    return np.clip(c * 255.0, 0, 255)


def delta_e2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    L1, a1, b1 = np.moveaxis(np.asarray(lab1, float), -1, 0)
    L2, a2, b2 = np.moveaxis(np.asarray(lab2, float), -1, 0)
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    dh = h2p - h1p
    dh = np.where(C1p * C2p == 0, 0, np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh)))
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lpm = (L1 + L2) / 2
    Cpm = (C1p + C2p) / 2
    hs = h1p + h2p
    hpm = np.where(C1p * C2p == 0, hs,
                   np.where(np.abs(h1p - h2p) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    T = (1 - 0.17 * np.cos(np.radians(hpm - 30)) + 0.24 * np.cos(np.radians(2 * hpm))
         + 0.32 * np.cos(np.radians(3 * hpm + 6)) - 0.20 * np.cos(np.radians(4 * hpm - 63)))
    dtheta = 30 * np.exp(-(((hpm - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cpm ** 7 / (Cpm ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lpm - 50) ** 2 / np.sqrt(20 + (Lpm - 50) ** 2)
    Sc = 1 + 0.045 * Cpm
    Sh = 1 + 0.015 * Cpm * T
    Rt = -np.sin(np.radians(2 * dtheta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def gamut_map(img: Image.Image, profile: Profile, intent: str = "Relative colorimetric",
              threshold: float = 4.0, max_side: int = 900) -> Tuple[Image.Image, float]:
    """Pixels the printer can't reproduce (ΔE2000 > threshold after printing).

    Returns (mask image 'L' at the reduced size, fraction of the picture out of gamut).
    """
    small = img.convert("RGB")
    if max(small.size) > max_side:
        small = small.copy()
        small.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    proof = soft_proof(small, profile, intent)
    d = delta_e2000(srgb_to_lab(np.asarray(small)), srgb_to_lab(np.asarray(proof)))
    m = d > threshold
    return Image.fromarray((m * 255).astype("uint8")), float(m.mean())


def gamut_overlay(img: Image.Image, mask: Image.Image, colour=(255, 0, 200)) -> Image.Image:
    base = img.convert("RGB").resize(mask.size, Image.Resampling.BILINEAR)
    over = Image.new("RGB", mask.size, colour)
    return Image.composite(over, base, mask.point(lambda v: 160 if v else 0))


# ======================================================================
# Palette + matching
# ======================================================================
def extract_palette(img: Image.Image, n: int = 8) -> List[Tuple[Tuple[int, int, int], float]]:
    small = img.convert("RGB").copy()
    small.thumbnail((300, 300), Image.Resampling.BILINEAR)
    q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = q.getpalette()[: n * 3]
    counts = sorted(q.getcolors(), reverse=True)
    total = sum(c for c, _ in counts) or 1
    out = []
    for c, idx in counts:
        rgb = tuple(pal[idx * 3: idx * 3 + 3])
        out.append((rgb, c / total))
    return out


def hex_of(rgb) -> str:
    return "#%02X%02X%02X" % tuple(int(v) for v in rgb[:3])


def rgb_of(hexs: str) -> Tuple[int, int, int]:
    h = hexs.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# A generic palette (CSS / X11 colour names, public) so matching works out of
# the box. Paint-brand fan decks are licensed: import your supplier's list.
CSS_COLOURS = {
    "Alice Blue": "#F0F8FF", "Antique White": "#FAEBD7", "Aqua": "#00FFFF", "Aquamarine": "#7FFFD4",
    "Azure": "#F0FFFF", "Beige": "#F5F5DC", "Bisque": "#FFE4C4", "Black": "#000000",
    "Blanched Almond": "#FFEBCD", "Blue": "#0000FF", "Blue Violet": "#8A2BE2", "Brown": "#A52A2A",
    "Burlywood": "#DEB887", "Cadet Blue": "#5F9EA0", "Chartreuse": "#7FFF00", "Chocolate": "#D2691E",
    "Coral": "#FF7F50", "Cornflower Blue": "#6495ED", "Cornsilk": "#FFF8DC", "Crimson": "#DC143C",
    "Dark Blue": "#00008B", "Dark Cyan": "#008B8B", "Dark Goldenrod": "#B8860B", "Dark Grey": "#A9A9A9",
    "Dark Green": "#006400", "Dark Khaki": "#BDB76B", "Dark Magenta": "#8B008B", "Dark Olive Green": "#556B2F",
    "Dark Orange": "#FF8C00", "Dark Orchid": "#9932CC", "Dark Red": "#8B0000", "Dark Salmon": "#E9967A",
    "Dark Sea Green": "#8FBC8F", "Dark Slate Blue": "#483D8B", "Dark Slate Grey": "#2F4F4F",
    "Dark Turquoise": "#00CED1", "Dark Violet": "#9400D3", "Deep Pink": "#FF1493", "Deep Sky Blue": "#00BFFF",
    "Dim Grey": "#696969", "Dodger Blue": "#1E90FF", "Firebrick": "#B22222", "Floral White": "#FFFAF0",
    "Forest Green": "#228B22", "Gainsboro": "#DCDCDC", "Ghost White": "#F8F8FF", "Gold": "#FFD700",
    "Goldenrod": "#DAA520", "Grey": "#808080", "Green": "#008000", "Green Yellow": "#ADFF2F",
    "Honeydew": "#F0FFF0", "Hot Pink": "#FF69B4", "Indian Red": "#CD5C5C", "Indigo": "#4B0082",
    "Ivory": "#FFFFF0", "Khaki": "#F0E68C", "Lavender": "#E6E6FA", "Lavender Blush": "#FFF0F5",
    "Lawn Green": "#7CFC00", "Lemon Chiffon": "#FFFACD", "Light Blue": "#ADD8E6", "Light Coral": "#F08080",
    "Light Cyan": "#E0FFFF", "Light Goldenrod": "#FAFAD2", "Light Grey": "#D3D3D3", "Light Green": "#90EE90",
    "Light Pink": "#FFB6C1", "Light Salmon": "#FFA07A", "Light Sea Green": "#20B2AA", "Light Sky Blue": "#87CEFA",
    "Light Slate Grey": "#778899", "Light Steel Blue": "#B0C4DE", "Light Yellow": "#FFFFE0", "Lime": "#00FF00",
    "Lime Green": "#32CD32", "Linen": "#FAF0E6", "Maroon": "#800000", "Medium Aquamarine": "#66CDAA",
    "Medium Blue": "#0000CD", "Medium Orchid": "#BA55D3", "Medium Purple": "#9370DB", "Medium Sea Green": "#3CB371",
    "Medium Slate Blue": "#7B68EE", "Medium Spring Green": "#00FA9A", "Medium Turquoise": "#48D1CC",
    "Medium Violet Red": "#C71585", "Midnight Blue": "#191970", "Mint Cream": "#F5FFFA", "Misty Rose": "#FFE4E1",
    "Moccasin": "#FFE4B5", "Navajo White": "#FFDEAD", "Navy": "#000080", "Old Lace": "#FDF5E6",
    "Olive": "#808000", "Olive Drab": "#6B8E23", "Orange": "#FFA500", "Orange Red": "#FF4500",
    "Orchid": "#DA70D6", "Pale Goldenrod": "#EEE8AA", "Pale Green": "#98FB98", "Pale Turquoise": "#AFEEEE",
    "Pale Violet Red": "#DB7093", "Papaya Whip": "#FFEFD5", "Peach Puff": "#FFDAB9", "Peru": "#CD853F",
    "Pink": "#FFC0CB", "Plum": "#DDA0DD", "Powder Blue": "#B0E0E6", "Purple": "#800080", "Rebecca Purple": "#663399",
    "Red": "#FF0000", "Rosy Brown": "#BC8F8F", "Royal Blue": "#4169E1", "Saddle Brown": "#8B4513",
    "Salmon": "#FA8072", "Sandy Brown": "#F4A460", "Sea Green": "#2E8B57", "Seashell": "#FFF5EE",
    "Sienna": "#A0522D", "Silver": "#C0C0C0", "Sky Blue": "#87CEEB", "Slate Blue": "#6A5ACD",
    "Slate Grey": "#708090", "Snow": "#FFFAFA", "Spring Green": "#00FF7F", "Steel Blue": "#4682B4",
    "Tan": "#D2B48C", "Teal": "#008080", "Thistle": "#D8BFD8", "Tomato": "#FF6347", "Turquoise": "#40E0D0",
    "Violet": "#EE82EE", "Wheat": "#F5DEB3", "White": "#FFFFFF", "White Smoke": "#F5F5F5", "Yellow": "#FFFF00",
    "Yellow Green": "#9ACD32",
}


def palette_dir() -> Path:
    return sub_dir("Palettes")


def list_palettes() -> Dict[str, Dict[str, str]]:
    out = {"Basic colour names (built in)": dict(CSS_COLOURS)}
    try:
        for p in sorted(palette_dir().glob("*.json")):
            try:
                out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    except Exception:
        pass
    return out


def import_palette(path: str | Path, name: Optional[str] = None) -> Tuple[str, int]:
    """Import a palette from CSV ('name,#hex' or 'name,r,g,b' or 'name,L,a,b' with a header) or JSON."""
    p = Path(path)
    colours: Dict[str, str] = {}
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data.items() if isinstance(data, dict) else ((d.get("name"), d.get("hex")) for d in data)
        for k, v in items:
            if k and v:
                colours[str(k)] = hex_of(rgb_of(str(v)))
    else:
        text = p.read_text(encoding="utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        lab_mode = rows and any(h.strip().lower() in ("l", "l*") for h in rows[0])
        for r in rows:
            r = [c.strip() for c in r if c.strip() != ""]
            if len(r) < 2:
                continue
            try:
                if len(r) >= 4 and not r[1].startswith("#"):
                    vals = [float(x) for x in r[1:4]]
                    if lab_mode:
                        rgb = lab_to_srgb(np.array(vals))
                    else:
                        rgb = vals
                    colours[r[0]] = hex_of([round(v) for v in rgb])
                else:
                    colours[r[0]] = hex_of(rgb_of(r[1]))
            except (ValueError, IndexError):
                continue      # header row or bad line
    if not colours:
        raise ValueError("No colours found. Use rows like: Name,#AABBCC  or  Name,R,G,B")
    name = name or p.stem
    (palette_dir() / f"{name}.json").write_text(json.dumps(colours, indent=1), encoding="utf-8")
    return name, len(colours)


def match_colour(rgb, palette: Dict[str, str], k: int = 3) -> List[Tuple[str, str, float]]:
    names = list(palette)
    if not names:
        return []
    labs = srgb_to_lab(np.array([rgb_of(palette[n]) for n in names], dtype=float))
    target = srgb_to_lab(np.array(rgb, dtype=float))[None, :]
    d = delta_e2000(np.repeat(target, len(names), axis=0), labs)
    order = np.argsort(d)[:k]
    return [(names[i], palette[names[i]], float(d[i])) for i in order]


# ======================================================================
# Recolouring
# ======================================================================
def replace_colour(img: Image.Image, src_rgb, dst_rgb, tolerance: float = 18.0,
                   softness: float = 0.5) -> Image.Image:
    """Move pixels near `src_rgb` (ΔE76 < tolerance) towards `dst_rgb`, keeping shading."""
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    a = np.asarray(img.convert("RGB"), dtype=np.float64)
    lab = srgb_to_lab(a)
    s = srgb_to_lab(np.array(src_rgb, float))
    d = srgb_to_lab(np.array(dst_rgb, float))
    dist = np.linalg.norm(lab - s, axis=-1)
    inner = tolerance * (1 - softness)
    w = np.clip((tolerance - dist) / max(tolerance - inner, 1e-6), 0, 1)
    out = lab + (d - s)[None, None, :] * w[..., None]
    res = Image.fromarray(lab_to_srgb(out).astype("uint8"))
    if alpha is not None:
        res.putalpha(alpha)
    return res


COLOURWAYS = ["Original", "Warm", "Cool", "Monochrome", "Sepia", "Soft pastel", "Deep & moody",
              "Sage green", "Navy blue", "Terracotta", "Blush pink", "Charcoal"]
_TINTS = {"Sage green": (156, 175, 136), "Navy blue": (31, 58, 96), "Terracotta": (196, 98, 64),
          "Blush pink": (222, 168, 168), "Charcoal": (64, 66, 70)}


def adjust(img: Image.Image, hue: float = 0.0, saturation: float = 1.0, brightness: float = 1.0,
           warmth: float = 0.0) -> Image.Image:
    """Hue shift (degrees), saturation ×, brightness ×, warmth (-1 cool … +1 warm)."""
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    lab = srgb_to_lab(np.asarray(img.convert("RGB"), dtype=np.float64))
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    if hue:
        c, s = np.cos(np.radians(hue)), np.sin(np.radians(hue))
        a, b = a * c - b * s, a * s + b * c
    a, b = a * saturation, b * saturation
    b = b + warmth * 12
    a = a + warmth * 4
    L = np.clip(L * brightness, 0, 100)
    res = Image.fromarray(lab_to_srgb(np.stack([L, a, b], -1)).astype("uint8"))
    if alpha is not None:
        res.putalpha(alpha)
    return res


def colourway(img: Image.Image, name: str) -> Image.Image:
    if name == "Original":
        return img.copy()
    if name == "Warm":
        return adjust(img, warmth=0.8, saturation=1.05)
    if name == "Cool":
        return adjust(img, warmth=-0.8)
    if name == "Monochrome":
        return adjust(img, saturation=0.0)
    if name == "Sepia":
        return _tint(img, (112, 76, 44), 0.9)
    if name == "Soft pastel":
        return adjust(img, saturation=0.55, brightness=1.12)
    if name == "Deep & moody":
        return adjust(img, saturation=0.85, brightness=0.72, warmth=-0.2)
    if name in _TINTS:
        return _tint(img, _TINTS[name], 0.85)
    raise KeyError(name)


def _tint(img: Image.Image, rgb, amount: float) -> Image.Image:
    """Duotone-style recolour: keep lightness, take colour from `rgb`."""
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    lab = srgb_to_lab(np.asarray(img.convert("RGB"), dtype=np.float64))
    t = srgb_to_lab(np.array(rgb, float))
    L = lab[..., 0]
    a = lab[..., 1] * (1 - amount) + t[1] * amount * (0.35 + 0.65 * (1 - np.abs(L - 50) / 50))
    b = lab[..., 2] * (1 - amount) + t[2] * amount * (0.35 + 0.65 * (1 - np.abs(L - 50) / 50))
    L = L * (1 - amount * 0.3) + (L * t[0] / 60.0) * amount * 0.3
    res = Image.fromarray(lab_to_srgb(np.stack([np.clip(L, 0, 100), a, b], -1)).astype("uint8"))
    if alpha is not None:
        res.putalpha(alpha)
    return res


# ======================================================================
# Colour bars for test strips
# ======================================================================
CONTROL_PATCHES = [  # (label, sRGB) – read with a spectro or by eye against the proof
    ("C", (0, 174, 239)), ("M", (236, 0, 140)), ("Y", (255, 242, 0)), ("K", (35, 31, 32)),
    ("R", (237, 28, 36)), ("G", (0, 166, 81)), ("B", (46, 49, 146)),
    ("Skin", (229, 182, 156)), ("Sky", (128, 170, 216)), ("Foliage", (88, 128, 72)),
]
