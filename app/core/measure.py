"""
Measure a wall from one phone photo.

1. The user marks the 4 wall corners (TL, TR, BR, BL).
2. The wall's shape (width ÷ height) is recovered from the perspective with
   the Zhang & He method (focal length from the two vanishing points), or from
   the photo's EXIF 35 mm focal length when the phone recorded it.
3. One real measurement fixes the scale: wall width, wall height, or a
   reference object flat on the wall (A4 sheet, bank card, a door …).
   Width AND height together give an accuracy check.
4. The photo is straightened ("rectified") so every pixel has a known size.
   Doors / windows (in the wall plane) are measured exactly; furniture in front
   of the wall is measured as the wall area it hides from the camera.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageOps

from app.core import units as u
from app.core import wall as wl

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

REFERENCES = {  # name: (width m, height m)
    "A4 sheet (210 × 297 mm)": (0.210, 0.297),
    "US Letter (8.5 × 11 in)": (0.2159, 0.2794),
    "A3 sheet (297 × 420 mm)": (0.297, 0.420),
    "Bank card (85.6 × 54 mm)": (0.0856, 0.05398),
    "UK door (762 × 1981 mm)": (0.762, 1.981),
    "EU door (800 × 2000 mm)": (0.800, 2.000),
    'US door (36 × 80 in)': (0.9144, 2.032),
    "Plug socket UK (86 × 86 mm)": (0.086, 0.086),
}

Point = Tuple[float, float]


# ======================================================================
# Geometry
# ======================================================================
def order_corners(pts: Sequence[Point]) -> List[Point]:
    """Return TL, TR, BR, BL whatever order the user clicked in."""
    p = np.asarray(pts, dtype=float)
    c = p.mean(axis=0)
    ang = np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0])
    p = p[np.argsort(ang)]                   # clockwise in image coords starting at the left-ish
    s = p.sum(axis=1)
    start = int(np.argmin(s))                 # TL has the smallest x + y
    p = np.roll(p, -start, axis=0)
    # make sure the order is TL, TR, BR, BL (clockwise on screen)
    if p[1][0] < p[3][0]:
        p = p[[0, 3, 2, 1]]
    return [tuple(map(float, q)) for q in p]


def homography(src: Sequence[Point], dst: Sequence[Point]) -> np.ndarray:
    A, b = [], []
    for (x, y), (X, Y) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y])
        A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
        b += [X, Y]
    h = np.linalg.solve(np.asarray(A, float), np.asarray(b, float))
    return np.append(h, 1.0).reshape(3, 3)


def apply_h(H: np.ndarray, pts) -> np.ndarray:
    p = np.asarray(pts, dtype=float).reshape(-1, 2)
    q = np.hstack([p, np.ones((len(p), 1))]) @ H.T
    return q[:, :2] / q[:, 2:3]


def estimate_aspect(corners: Sequence[Point], image_size: Tuple[int, int],
                    focal_px: Optional[float] = None) -> Tuple[float, Optional[float], str]:
    """Width ÷ height of the real rectangle seen at `corners` (TL, TR, BR, BL).

    Returns (aspect, focal length in px or None, method).
    """
    tl, tr, br, bl = [np.array([x, y, 1.0]) for x, y in corners]
    u0, v0 = image_size[0] / 2.0, image_size[1] / 2.0
    m1, m2, m3, m4 = tl, tr, bl, br
    k2 = np.dot(np.cross(m1, m4), m3) / np.dot(np.cross(m2, m4), m3)
    k3 = np.dot(np.cross(m1, m4), m2) / np.dot(np.cross(m3, m4), m2)
    n2 = k2 * m2 - m1
    n3 = k3 * m3 - m1
    affine = math.sqrt((n2[0] ** 2 + n2[1] ** 2) / max(1e-12, n3[0] ** 2 + n3[1] ** 2))
    f = focal_px
    method = "EXIF focal length" if focal_px else "perspective (vanishing points)"
    if f is None:
        den = n2[2] * n3[2]
        if abs(den) > 1e-9:
            f2 = -((n2[0] * n3[0] - (n2[0] * n3[2] + n2[2] * n3[0]) * u0 + n2[2] * n3[2] * u0 ** 2)
                   + (n2[1] * n3[1] - (n2[1] * n3[2] + n2[2] * n3[1]) * v0 + n2[2] * n3[2] * v0 ** 2)) / den
            if f2 > 0:
                f = math.sqrt(f2)
        # unreliable focal (photo taken almost straight on): fall back to a typical phone lens
        if f is None or not (0.4 * max(image_size) < f < 4.0 * max(image_size)):
            f = 0.0
    if not f:
        # no usable perspective: assume a normal phone camera (26 mm equivalent)
        f_typ = 26.0 / 36.0 * max(image_size)
        f, method = f_typ, "typical phone lens (photo is nearly straight on)"
    Ai = np.linalg.inv(np.array([[f, 0, u0], [0, f, v0], [0, 0, 1.0]]))
    a2 = Ai @ n2
    a3 = Ai @ n3
    aspect = math.sqrt(float(a2 @ a2) / max(1e-12, float(a3 @ a3)))
    if not math.isfinite(aspect) or aspect <= 0:
        return affine, None, "side lengths (approximate)"
    return aspect, f, method


def exif_focal_px(img: Image.Image) -> Optional[float]:
    """Focal length in pixels from EXIF 'FocalLengthIn35mmFilm', if the phone wrote it."""
    try:
        ex = img.getexif()
        f35 = ex.get_ifd(0x8769).get(0xA405) or ex.get(0xA405)
        if f35:
            return float(f35) / 36.0 * max(img.size)
    except Exception:
        pass
    return None


def load_photo(path) -> Tuple[Image.Image, Optional[float]]:
    with Image.open(path) as im:
        im.load()
        f = exif_focal_px(im)
        out = ImageOps.exif_transpose(im).convert("RGB")
    return out, f


# ======================================================================
# Survey
# ======================================================================
@dataclass
class Survey:
    image_size: Tuple[int, int]
    corners: List[Point]                     # TL, TR, BR, BL in photo pixels
    width: float = 0.0                       # tape measurements (0 = unknown)
    height: float = 0.0
    reference: str = ""                      # REFERENCES key or "Custom"
    reference_size: Tuple[float, float] = (0.0, 0.0)
    reference_quad: List[Point] = field(default_factory=list)
    focal_px: Optional[float] = None         # from EXIF

    def aspect(self) -> Tuple[float, Optional[float], str]:
        return estimate_aspect(order_corners(self.corners), self.image_size, self.focal_px)


@dataclass
class SurveyResult:
    width: float
    height: float
    aspect_photo: float
    method: str
    scale_from: str                     # what fixed the scale
    accuracy_pct: Optional[float]       # difference photo vs tape / reference (None = not checked)
    predicted: Optional[float]          # the dimension the photo predicted (height or width)
    H: np.ndarray                       # photo px -> wall metres (x right, y down from the top)

    def accuracy_text(self, unit: str = "m") -> str:
        if self.accuracy_pct is None:
            return f"Size from {self.scale_from}. Add the other side to check the accuracy."
        a = self.accuracy_pct
        word = "excellent" if a < 1 else "good" if a < 3 else "fair" if a < 6 else "poor – re-mark the corners"
        return f"Photo vs tape: {a:.1f}% – {word}"


MAX_WALL_W, MAX_WALL_H = 100.0, 30.0      # same limits as the wall size boxes in Wall Studio


def solve(s: Survey) -> SurveyResult:
    corners = order_corners(s.corners)
    aspect, f, method = estimate_aspect(corners, s.image_size, s.focal_px)
    acc = pred = None
    if s.width > 0 and s.height > 0:
        W, H = s.width, s.height
        pred = W / aspect
        acc = abs(pred - H) / H * 100.0
        scale_from = "tape width + height"
    elif s.width > 0:
        W, H = s.width, s.width / aspect
        scale_from = "tape width"
    elif s.height > 0:
        W, H = s.height * aspect, s.height
        scale_from = "tape height"
    elif s.reference_quad and len(s.reference_quad) == 4 and min(s.reference_size) > 0:
        Hu = homography(corners, [(0, 0), (aspect, 0), (aspect, 1), (0, 1)])
        q = apply_h(Hu, order_corners(s.reference_quad))
        rw = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
        rh = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
        a, b = s.reference_size
        if (rw > rh) != (a > b):            # reference held the other way round
            a, b = b, a
        k1, k2 = a / max(rw, 1e-9), b / max(rh, 1e-9)
        k = (k1 + k2) / 2
        W, H = aspect * k, k
        acc = abs(k1 - k2) / k * 100.0
        scale_from = f"reference {s.reference.split(' (')[0] or 'object'}"
    else:
        raise ValueError("Enter the wall width or height, or mark a reference object.")
    Hm = homography(corners, [(0, 0), (W, 0), (W, H), (0, H)])
    return SurveyResult(W, H, aspect, method, scale_from, acc, pred, Hm)


def rectify(photo: Image.Image, res: SurveyResult, ppm: float = 0.0, max_side: int = 2400) -> Tuple[Image.Image, float]:
    """Straightened wall image. Returns (image, pixels per metre)."""
    if ppm <= 0:
        ppm = max_side / max(res.width, res.height)
    W, H = max(1, int(round(res.width * ppm))), max(1, int(round(res.height * ppm)))
    S = np.diag([ppm, ppm, 1.0])
    M = S @ res.H
    if cv2 is not None:
        out = cv2.warpPerspective(np.asarray(photo.convert("RGB")), M, (W, H), flags=cv2.INTER_CUBIC,
                                  borderMode=cv2.BORDER_REPLICATE)
        return Image.fromarray(out), ppm
    inv = np.linalg.inv(M)
    inv /= inv[2, 2]
    return photo.transform((W, H), Image.Transform.PERSPECTIVE, tuple(inv.flatten()[:8]),
                           Image.Resampling.BICUBIC), ppm


def photo_box_to_wall(res: SurveyResult, box: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    """Image box (x, y, w, h) -> wall-coordinate rect (x, y_from_floor, w, h), clipped to the wall."""
    x, y, w, h = box
    q = apply_h(res.H, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
    x0, x1 = float(q[:, 0].min()), float(q[:, 0].max())
    y0, y1 = float(q[:, 1].min()), float(q[:, 1].max())
    x0, x1 = max(0.0, x0), min(res.width, x1)
    y0, y1 = max(0.0, y0), min(res.height, y1)
    return x0, res.height - y1, max(0.0, x1 - x0), max(0.0, y1 - y0)


def wall_to_photo(res: SurveyResult, pts_wall) -> np.ndarray:
    """Wall points (x, y_from_floor) -> photo pixels."""
    p = np.asarray(pts_wall, dtype=float).reshape(-1, 2).copy()
    p[:, 1] = res.height - p[:, 1]
    return apply_h(np.linalg.inv(res.H), p)


# ======================================================================
# Auto-detection
# ======================================================================
def _lab(img: np.ndarray) -> np.ndarray:
    if cv2 is not None:
        return cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    from app.core.colour import srgb_to_lab
    return srgb_to_lab(img)


def opening_mask(flat: Image.Image, ppm: float, avoid: Sequence[Tuple[float, float, float, float]] = ()
                 ) -> np.ndarray:
    """1 where the straightened wall is not bare wall (by colour difference)."""
    a = np.asarray(flat.convert("RGB"))
    H, W = a.shape[:2]
    lab = _lab(a)
    # Room light changes brightness across a wall far more than colour. So:
    # find bare-wall pixels by colour (a, b), fit a smooth brightness surface to
    # them, and compare every pixel with that surface instead of one value.
    L = lab[:, :, 0]
    ab = lab[:, :, 1:3].reshape(-1, 2)
    wab = np.median(ab, axis=0)
    for _ in range(3):
        near = ab[np.linalg.norm(ab - wab, axis=1) < 8]
        if len(near) > 100:
            wab = np.median(near, axis=0)
    cand = (np.linalg.norm(ab - wab, axis=1) < 8).reshape(H, W)
    yy, xx = np.mgrid[0:H, 0:W]
    xn, yn = (xx / max(W - 1, 1) - 0.5), (yy / max(H - 1, 1) - 0.5)
    basis = np.stack([np.ones_like(xn), xn, yn, xn * xn, xn * yn, yn * yn], axis=-1).reshape(-1, 6)
    idx = np.flatnonzero(cand.reshape(-1))
    if idx.size > 50:
        rng = np.random.default_rng(0)
        if idx.size > 20000:
            idx = rng.choice(idx, 20000, replace=False)
        Lv = L.reshape(-1)
        sel = idx
        coef = None
        for _ in range(3):
            coef, *_r = np.linalg.lstsq(basis[sel], Lv[sel], rcond=None)
            res = Lv[idx] - basis[idx] @ coef
            mad = np.median(np.abs(res - np.median(res))) + 1e-3
            sel = idx[np.abs(res) < 3 * 1.4826 * mad]
            if sel.size < 50:
                break
        Lfit = (basis @ coef).reshape(H, W)
    else:
        Lfit = np.full((H, W), float(np.median(L)))
    feat = np.dstack([(L - Lfit) * 0.6, lab[:, :, 1], lab[:, :, 2]]).reshape(-1, 3)
    wallc = np.array([0.0, wab[0], wab[1]], dtype=np.float32)
    for _ in range(3):
        d = np.linalg.norm(feat - wallc, axis=1)
        near = feat[d < 12]
        if len(near) > 100:
            wallc = np.median(near, axis=0)
    dist = np.linalg.norm(feat - wallc, axis=1).reshape(H, W)
    d_wall = dist[dist < 12]
    noise = float(np.median(d_wall)) if d_wall.size else 3.0
    thr = max(9.0, noise * 4.0)
    mask = (dist > thr).astype(np.uint8)
    for (x, yf, w, h) in avoid:   # furniture already found
        x0, x1 = int(x * ppm), int((x + w) * ppm)
        y0, y1 = int((H / ppm - (yf + h)) * ppm), int((H / ppm - yf) * ppm)
        mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 0
    # skirting board and cornice run the whole width: leave them out
    mask[max(0, H - int(0.13 * ppm)):, :] = 0
    mask[:int(0.04 * ppm), :] = 0
    kc = max(3, int(0.06 * ppm)) | 1          # bridge window bars and door panels
    ko = max(3, int(0.04 * ppm)) | 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((kc, kc), np.uint8))
    # fill holes (frames inside a window that match the wall colour): background
    # pieces that do not touch the edge of the wall and are small
    nb, bl, bst, _ = cv2.connectedComponentsWithStats((mask == 0).astype(np.uint8), 4)
    for i in range(1, nb):
        x, y, w, h, area = bst[i]
        if x > 0 and y > 0 and x + w < W and y + h < H and area < 0.25 * W * H:
            mask[bl == i] = 1
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((ko, ko), np.uint8))


def detect_openings(flat: Image.Image, ppm: float, avoid: Sequence[Tuple[float, float, float, float]] = ()
                    ) -> List[wl.Obstacle]:
    """Doors and windows on a straightened wall (by colour difference from the wall)."""
    if cv2 is None:
        return []
    mask = opening_mask(flat, ppm, avoid)
    H, W = mask.shape
    n, _lab_img, stats, _c = cv2.connectedComponentsWithStats(mask, 8)
    out: List[wl.Obstacle] = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        wm, hm = w / ppm, h / ppm
        if wm * hm < 0.12 or w >= W * 0.95 or h >= H * 0.97:
            continue
        fill = area / float(w * h)
        bottom = (H - (y + h)) / ppm             # from the floor
        if bottom < 0.16:                        # reaches the skirting: really goes to the floor
            hm += bottom
            bottom = 0.0
        top_gap = y / ppm
        if fill < 0.45:
            continue
        if bottom < 0.12 and hm >= 1.55 and 0.5 <= wm <= 2.4:
            kind = "door"
        elif bottom >= 0.2 and wm >= 0.3 and hm >= 0.3 and fill >= 0.6 and top_gap >= 0.02:
            kind = "window"
        elif bottom < 0.12 and wm * hm >= 0.3:
            kind = "other"
        else:
            continue
        o = wl.Obstacle.make(kind, x=x / ppm, y=max(0.0, bottom), w=wm, h=hm, source="detected")
        if kind == "other":
            o.in_front = True
            o.label = "Furniture"           # something standing on the floor – check what it is
        out.append(o)
    return out


def auto_detect(photo: Image.Image, res: SurveyResult, flat: Image.Image, ppm: float) -> List[wl.Obstacle]:
    """Furniture (AI) + doors / windows (colour regions) on the measured wall."""
    from app.core import detect
    items: List[wl.Obstacle] = []
    for d in detect.detect_furniture(photo):
        x, yf, w, h = photo_box_to_wall(res, d.box)
        if w * h < 0.02 or w < 0.05 or h < 0.05:
            continue
        o = wl.Obstacle.make(d.kind, x=x, y=yf, w=w, h=h, source="detected")
        o.in_front = True
        o.label = ""
        items.append(o)
    avoid = [(o.x, o.y, o.w, o.h) for o in items]
    for o in detect_openings(flat, ppm, avoid):
        # drop regions that are mostly a piece of furniture we already have
        if any(_overlap_frac(o, f) > 0.5 for f in items):
            continue
        items.append(o)
    items.sort(key=lambda o: (o.x, o.y))
    return items


def _overlap_frac(a: wl.Obstacle, b: wl.Obstacle) -> float:
    x0, x1 = max(a.x, b.x), min(a.x + a.w, b.x + b.w)
    y0, y1 = max(a.y, b.y), min(a.y + a.h, b.y + b.h)
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return inter / max(1e-9, a.w * a.h)


# ======================================================================
# Dimension lines
# ======================================================================
@dataclass
class Dim:
    x0: float          # wall coordinates (x from left, y from floor)
    y0: float
    x1: float
    y1: float
    text: str
    colour: str = "#0f172a"
    level: int = 0     # how far outside the wall / item to draw (0 = on the item)
    side: str = "top"  # top / bottom / left / right / inside


def wall_dimensions(w: wl.Wall, unit: str = "m") -> List[Dim]:
    f = lambda m: u.fmt(m, unit) if unit != "m" else f"{m:.2f} m"
    s = lambda m: u.fmt_short(m, unit)
    dims: List[Dim] = [
        Dim(0, w.height, w.width, w.height,
            f"{f(w.width)}" + (f"  ({u.ft_in(w.width)})" if unit in ("m", "cm", "mm") else ""), level=2, side="top"),
        Dim(0, 0, 0, w.height,
            f"{f(w.height)}" + (f"  ({u.ft_in(w.height)})" if unit in ("m", "cm", "mm") else ""),
            level=2 if w.shaped else 1, side="left"),
    ]
    if w.shaped:
        # heights at the two ends of a sloped / stair / gable wall
        for x, side in ((0.0, "left"), (w.width, "right")):
            lo, hi = w.span(x, x)
            if hi - lo > 0.01 and (abs(hi - w.height) > 0.01 or lo > 0.01):
                dims.append(Dim(x, lo, x, hi, f(hi - lo), "#2563eb", 1, side))
        if w.shape == "stairs":
            lo_r, _h = w.span(w.width, w.width)
            lo_l, _h = w.span(0.0, 0.0)
            if abs(lo_r - lo_l) > 0.01:
                xr = w.width if lo_r > lo_l else 0.0
                dims.append(Dim(xr, 0, xr, max(lo_r, lo_l), f"stairs rise {f(abs(lo_r - lo_l))}", "#b45309", 2,
                                "right" if xr else "left"))
    # chain of openings along the top
    openings = sorted([o for o in w.obstacles if not o.in_front and o.kind != "socket"], key=lambda o: o.x)
    edges = [0.0]
    for o in openings:
        edges += [max(0.0, o.x), min(w.width, o.x + o.w)]
    edges.append(w.width)
    edges = sorted(set(round(e, 4) for e in edges))
    if len(edges) > 2:
        for a, b in zip(edges, edges[1:]):
            if b - a > 0.005:
                dims.append(Dim(a, w.height, b, w.height, s(b - a), level=1, side="top"))
    for o in openings:
        dims.append(Dim(o.x + o.w, o.y, o.x + o.w, o.top, f(o.h), o.colour, 0, "right"))
        if o.kind == "window" or o.y > 0.05:
            dims.append(Dim(o.x, 0, o.x, o.y, f"sill {f(o.y)}" if o.kind == "window" else f(o.y),
                            o.colour, 0, "left"))
        gap = w.height - o.top
        if gap > 0.03:
            dims.append(Dim(o.x + o.w, o.top, o.x + o.w, w.height, s(gap), o.colour, 0, "right"))
    for o in w.obstacles:
        if o.in_front:
            dims.append(Dim(o.x, 0, o.x + o.w, 0, f"{o.name.lower()} {f(o.w)}", o.colour, 1, "bottom"))
            if o.y < 0.02:
                dims.append(Dim(o.x, 0, o.x, o.top, s(o.top), o.colour, 0, "left"))
    return dims


def items_table(w: wl.Wall, unit: str = "m") -> List[List[str]]:
    rows = []
    for o in sorted(w.obstacles, key=lambda o: o.x):
        rows.append([o.name, u.fmt(o.w, unit) + " × " + u.fmt(o.h, unit), u.fmt(o.x, unit),
                     u.fmt(o.y, unit), "in front" if o.in_front else "in wall"])
    return rows


# ======================================================================
# Synthetic photos (self-test, demo)
# ======================================================================
def camera_homography(wall_w: float, wall_h: float, image_size=(1600, 1200), focal_px=1300.0,
                      yaw_deg=18.0, pitch_deg=-4.0, distance=4.5, offset=(0.3, -0.2)) -> np.ndarray:
    """Pinhole camera looking at a wall: maps wall metres (x right, y down from top) -> image px."""
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    Ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    R = Rx @ Ry
    # wall point (X, Y, 0) -> camera: R @ (X - W/2 + ox, Y - H/2 + oy, 0) + (0, 0, distance)
    a, b = -wall_w / 2 + offset[0], -wall_h / 2 + offset[1]
    K = np.array([[focal_px, 0, image_size[0] / 2], [0, focal_px, image_size[1] / 2], [0, 0, 1.0]])
    Hm = K @ np.column_stack([R[:, 0], R[:, 1], R[:, 0] * a + R[:, 1] * b + np.array([0, 0, distance])])
    return Hm / Hm[2, 2]


# ======================================================================
# Automatic corner finding
# ======================================================================
def _segments(gray: np.ndarray) -> np.ndarray:
    """Line segments (x0, y0, x1, y1) in a grey image."""
    if cv2 is None:
        return np.zeros((0, 4))
    try:
        lsd = cv2.createLineSegmentDetector()
        lines = lsd.detect(gray)[0]
    except Exception:
        lines = None
    if lines is None:
        edges = cv2.Canny(gray, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 360, 60, minLineLength=max(20, min(gray.shape) // 15),
                                maxLineGap=6)
    if lines is None:
        return np.zeros((0, 4))
    return lines.reshape(-1, 4).astype(np.float64)


def _line_from(seg) -> np.ndarray:
    """Homogeneous line through a segment."""
    p = np.array([seg[0], seg[1], 1.0])
    q = np.array([seg[2], seg[3], 1.0])
    ln = np.cross(p, q)
    return ln / (np.hypot(ln[0], ln[1]) + 1e-12)


def _cluster_lines(segs: np.ndarray, horizontal: bool, size: Tuple[int, int], k: int = 7) -> List[np.ndarray]:
    """Merge collinear segments; return the k best supported lines (homogeneous)."""
    W, H = size
    if not len(segs):
        return []
    dx, dy = segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1]
    length = np.hypot(dx, dy)
    ang = np.degrees(np.arctan2(dy, dx)) % 180
    if horizontal:
        ok = (np.minimum(ang, 180 - ang) < 35) & (length > 0.04 * W)
    else:
        ok = (np.abs(ang - 90) < 18) & (length > 0.04 * H)
    segs, length = segs[ok], length[ok]
    if not len(segs):
        return []
    if not horizontal:
        # floorboards and table legs make many short near-vertical lines low in the photo:
        # count only the part of a segment in the middle band of the picture
        y0 = np.minimum(segs[:, 1], segs[:, 3])
        y1 = np.maximum(segs[:, 1], segs[:, 3])
        mid = np.clip(np.minimum(y1, 0.8 * H) - np.maximum(y0, 0.2 * H), 0, None)
        length = length * (0.15 + 0.85 * mid / np.maximum(y1 - y0, 1e-6))
    lines = np.array([_line_from(s) for s in segs])
    # position of each line at the image centre (y for horizontal, x for vertical) and its angle
    cx, cy = W / 2, H / 2
    if horizontal:
        pos = np.array([-(ln[0] * cx + ln[2]) / ln[1] if abs(ln[1]) > 1e-9 else 1e9 for ln in lines])
        tol = 0.02 * H
    else:
        pos = np.array([-(ln[1] * cy + ln[2]) / ln[0] if abs(ln[0]) > 1e-9 else 1e9 for ln in lines])
        tol = 0.02 * W
    angs = np.degrees(np.arctan2(segs[:, 3] - segs[:, 1], segs[:, 2] - segs[:, 0])) % 180
    order = np.argsort(-length)
    used = np.zeros(len(segs), bool)
    out = []
    for i in order:
        if used[i]:
            continue
        da = np.abs(((angs - angs[i]) + 90) % 180 - 90)
        grp = (~used) & (np.abs(pos - pos[i]) < tol) & (da < 4)
        used |= grp
        idx = np.flatnonzero(grp)
        # refit the line through all endpoints of the group, weighted by length
        pts = np.vstack([segs[idx, :2], segs[idx, 2:]])
        w = np.concatenate([length[idx], length[idx]])
        m = np.average(pts, axis=0, weights=w)
        cov = np.cov((pts - m).T, aweights=w) if len(pts) > 2 else np.outer(pts[1] - pts[0], pts[1] - pts[0])
        evals, evecs = np.linalg.eigh(cov)
        d = evecs[:, -1]
        ln = np.cross([m[0], m[1], 1.0], [m[0] + d[0], m[1] + d[1], 1.0])
        ln /= np.hypot(ln[0], ln[1]) + 1e-12
        out.append((float(length[idx].sum()), ln))
    out.sort(key=lambda t: -t[0])
    return [ln for _s, ln in out[:k]]


def _edge_support(img: np.ndarray, p: np.ndarray, q: np.ndarray, n: int = 80, off: float = 4.0,
                  thr: float = 10.0) -> float:
    """Fraction of points along p→q where the colour changes across the line (an edge, even a faint one)."""
    H, W = img.shape[:2]
    t = np.linspace(0.04, 0.96, n)
    xs = p[0] + (q[0] - p[0]) * t
    ys = p[1] + (q[1] - p[1]) * t
    d = q - p
    nrm = np.array([-d[1], d[0]]) / (np.hypot(d[0], d[1]) + 1e-9)
    ax, ay = xs + nrm[0] * off, ys + nrm[1] * off
    bx, by = xs - nrm[0] * off, ys - nrm[1] * off
    ok = (ax >= 0) & (ax < W) & (ay >= 0) & (ay < H) & (bx >= 0) & (bx < W) & (by >= 0) & (by < H)
    if not ok.any():
        return 0.0
    ca = img[ay[ok].astype(int), ax[ok].astype(int)].astype(np.float32)
    cb = img[by[ok].astype(int), bx[ok].astype(int)].astype(np.float32)
    diff = np.linalg.norm(ca - cb, axis=-1) if ca.ndim > 1 else np.abs(ca - cb)
    return float((diff > thr).sum()) / n


_DEBUG = None


def find_wall_corners(photo: Image.Image, max_side: int = 900) -> Optional[Tuple[List[Point], float]]:
    """Guess the 4 wall corners (TL, TR, BR, BL) from the straight edges in a photo.

    Returns (corners in photo pixels, confidence 0–1) or None. The user always
    checks and drags the corners afterwards.
    """
    if cv2 is None:
        return None
    k = min(1.0, max_side / max(photo.size))
    small = photo.convert("L")
    if k < 1:
        small = small.resize((round(photo.width * k), round(photo.height * k)), Image.Resampling.BILINEAR)
    g = np.asarray(small)
    H, W = g.shape
    # walls often meet at a faint edge (two similar paint colours): boost local contrast first
    g = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(cv2.GaussianBlur(g, (3, 3), 0))
    segs = _segments(g)
    hs = _cluster_lines(segs, True, (W, H), k=14)
    vs = _cluster_lines(segs, False, (W, H), k=14)
    if len(hs) < 2 or len(vs) < 2:
        return None
    rgb = photo.convert("RGB")
    if k < 1:
        rgb = rgb.resize(small.size, Image.Resampling.BILINEAR)
    col = cv2.GaussianBlur(np.asarray(rgb), (5, 5), 0)

    def x_at(ln, y):
        return -(ln[1] * y + ln[2]) / ln[0] if abs(ln[0]) > 1e-9 else None

    def y_at(ln, x):
        return -(ln[0] * x + ln[2]) / ln[1] if abs(ln[1]) > 1e-9 else None

    tops = [h for h in hs if (y_at(h, W / 2) or 1e9) < H * 0.62]
    bots = [h for h in hs if (y_at(h, W / 2) or -1e9) > H * 0.38]
    lefts = [v for v in vs if (x_at(v, H / 2) or 1e9) < W * 0.62]
    rights = [v for v in vs if (x_at(v, H / 2) or -1e9) > W * 0.38]
    best, best_s = None, 0.0
    margin = 0.03
    if len(segs):
        L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
        A = np.degrees(np.arctan2(segs[:, 3] - segs[:, 1], segs[:, 2] - segs[:, 0])) % 180
        vsegs = segs[(np.abs(A - 90) < 12) & (L > 0.15 * H)]
    else:
        vsegs = []
    vlines: list = []
    for sg in sorted(vsegs, key=lambda q: -abs(q[3] - q[1])):
        ln = _line_from(sg)
        xm = -(ln[1] * H / 2 + ln[2]) / ln[0] if abs(ln[0]) > 1e-9 else None
        if xm is not None and all(abs(xm - o) > 4 for o, _l in vlines):
            vlines.append((xm, ln))
    corner_cache: dict = {}
    for t in tops:
        for b in bots:
            yt, yb = y_at(t, W / 2), y_at(b, W / 2)
            if yb - yt < H * 0.2:
                continue
            for le in lefts:
                for r in rights:
                    xl, xr = x_at(le, H / 2), x_at(r, H / 2)
                    if xr - xl < W * 0.2:
                        continue
                    pts = []
                    for a, c in ((t, le), (t, r), (b, r), (b, le)):
                        p = np.cross(a, c)
                        if abs(p[2]) < 1e-9:
                            break
                        pts.append(p[:2] / p[2])
                    if len(pts) < 4:
                        continue
                    P = np.array(pts)
                    if (P[:, 0] < -margin * W).any() or (P[:, 0] > (1 + margin) * W).any() or \
                            (P[:, 1] < -margin * H).any() or (P[:, 1] > (1 + margin) * H).any():
                        continue
                    sup = [_edge_support(col, P[i], P[(i + 1) % 4]) for i in range(4)]
                    if min(sup) < 0.25:
                        continue
                    area = 0.5 * abs(np.dot(P[:, 0], np.roll(P[:, 1], 1)) - np.dot(P[:, 1], np.roll(P[:, 0], 1)))
                    # big quads win once their edges are well supported
                    s = (area / (W * H)) * min(1.0, np.mean(sup) / 0.7) * min(1.0, min(sup) / 0.45)
                    if s <= best_s:
                        continue
                    # a corner line (colour change from ceiling to floor) inside means the quad spans two walls
                    for j, (xm, vl) in enumerate(vlines):
                        if not (xl + 0.03 * W < xm < xr - 0.03 * W):
                            continue
                        key = (id(t), id(b), j)
                        if key not in corner_cache:
                            a1, a2 = np.cross(t, vl), np.cross(b, vl)
                            if abs(a1[2]) < 1e-9 or abs(a2[2]) < 1e-9:
                                corner_cache[key] = False
                            else:
                                pa, pb = a1[:2] / a1[2], a2[:2] / a2[2]
                                # all the way down, and right up at the ceiling (door frames stop short)
                                corner_cache[key] = (_edge_support(col, pa, pb) >= 0.85 and
                                                     _edge_support(col, pa, pa + (pb - pa) * 0.2, n=24) >= 0.75)
                        if corner_cache[key]:
                            s *= 0.2
                            break
                    if s > best_s:
                        best_s, best = s, P
                        if _DEBUG is not None:
                            _DEBUG.append((s, P.round(0).tolist(), [round(v, 2) for v in sup]))
    if best is None:
        return None
    corners = [(float(x) / k, float(y) / k) for x, y in best]
    corners = [(min(max(0.0, x), photo.width - 1.0), min(max(0.0, y), photo.height - 1.0)) for x, y in corners]
    return order_corners(corners), float(min(1.0, best_s * 2.0))


# ======================================================================
# Wide-angle (barrel) lens correction
# ======================================================================
def _lens_K(size: Tuple[int, int], k1: float, keep_all: bool = True):
    W, H = size
    f = 0.5 * math.hypot(W, H)
    K = np.array([[f, 0, W / 2.0], [0, f, H / 2.0], [0, 0, 1.0]])
    D = np.array([k1, 0.0, 0.0, 0.0])
    newK = K
    if keep_all and k1 < 0:
        newK, _roi = cv2.getOptimalNewCameraMatrix(K, D, (W, H), 1.0, (W, H))
    return K, D, newK


def _lens_maps(size: Tuple[int, int], k1: float, keep_all: bool = True):
    K, D, newK = _lens_K(size, k1, keep_all)
    return cv2.initUndistortRectifyMap(K, D, None, newK, tuple(size), cv2.CV_32FC1)


def lens_undistort_points(pts, size: Tuple[int, int], k1: float) -> np.ndarray:
    """Photo points -> the same points in the straightened (undistorted) photo."""
    p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    if cv2 is None or abs(k1) < 1e-4:
        return p
    K, D, newK = _lens_K(size, k1)
    d = (p - [K[0, 2], K[1, 2]]) / [K[0, 0], K[1, 1]]
    rd = np.hypot(d[:, 0], d[:, 1])
    r = rd.copy()
    for _ in range(30):                       # Newton: r (1 + k1 r²) = rd
        f = r * (1 + k1 * r * r) - rd
        r = r - f / (1 + 3 * k1 * r * r)
    scale = np.where(rd > 1e-12, r / np.maximum(rd, 1e-12), 1.0)[:, None]
    n = d * scale
    return n * [newK[0, 0], newK[1, 1]] + [newK[0, 2], newK[1, 2]]


def lens_distort_points(pts, size: Tuple[int, int], k1: float) -> np.ndarray:
    """Points in the straightened photo -> the original photo."""
    p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    if cv2 is None or abs(k1) < 1e-4:
        return p
    K, D, newK = _lens_K(size, k1)
    n = (np.hstack([p, np.ones((len(p), 1))]) @ np.linalg.inv(newK).T)[:, :2]
    r2 = (n ** 2).sum(axis=1, keepdims=True)
    d = n * (1 + k1 * r2)
    return d * [K[0, 0], K[1, 1]] + [K[0, 2], K[1, 2]]


def undistort(photo: Image.Image, k1: float) -> Image.Image:
    """Straighten lines bent by a wide-angle lens (k1 < 0 = barrel)."""
    if cv2 is None or abs(k1) < 1e-4:
        return photo
    m1, m2 = _lens_maps(photo.size, k1)
    a = cv2.remap(np.asarray(photo.convert("RGB")), m1, m2, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT,
                  borderValue=(236, 239, 243))
    return Image.fromarray(a)


def _straightness(gray: np.ndarray) -> float:
    segs = _segments(gray)
    if not len(segs):
        return 0.0
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    L = L[L > 0.05 * max(gray.shape)]
    return float((L ** 2).sum())


def estimate_lens(photo: Image.Image, max_side: int = 800) -> Tuple[float, float]:
    """Best k1 for straight lines, and how much straighter it makes them (1.0 = no change)."""
    if cv2 is None:
        return 0.0, 1.0
    k = min(1.0, max_side / max(photo.size))
    small = photo.convert("L")
    if k < 1:
        small = small.resize((round(photo.width * k), round(photo.height * k)), Image.Resampling.BILINEAR)
    g0 = np.asarray(small)

    def score(k1):
        if abs(k1) < 1e-6:
            return _straightness(g0)
        m1, m2 = _lens_maps(small.size, k1, keep_all=False)
        return _straightness(cv2.remap(g0, m1, m2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE))

    base = score(0.0)
    grid = np.arange(-0.45, 0.151, 0.05)
    vals = [score(v) for v in grid]
    i = int(np.argmax(vals))
    best, bv = float(grid[i]), vals[i]
    for v in np.arange(best - 0.04, best + 0.041, 0.01):
        s = score(float(v))
        if s > bv:
            best, bv = float(v), s
    return round(best, 3), (bv / base if base > 0 else 1.0)


def exif_focal_35(img: Image.Image) -> Optional[float]:
    try:
        ex = img.getexif()
        f35 = ex.get_ifd(0x8769).get(0xA405) or ex.get(0xA405)
        return float(f35) if f35 else None
    except Exception:
        return None
