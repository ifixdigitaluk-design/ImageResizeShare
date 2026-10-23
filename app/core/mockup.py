"""
Room previews for customers.

* render_room()      – the customer's wall at TRUE scale inside a simple room
                       (their doors, windows and furniture, or a scene's
                       default furniture), with the design on the wall.
* photo_mockup()     – the design placed on the customer's own wall photo in
                       perspective, keeping their furniture in front and the
                       room's light and shadows.
* material_swatch()  – close-up of the design on the chosen wallpaper material.

All drawing is procedural (no stock photos), so it can be used freely.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.core import wall as wl

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

SCENES = {
    "living": "Living room",
    "bedroom": "Bedroom",
    "office": "Office",
    "cafe": "Café / restaurant",
    "empty": "Empty room",
}

MATERIALS = {   # name: (texture kind, strength, sheen)
    "Non-woven (smooth)": ("fibre", 0.05, 0.0),
    "Vinyl (textured)": ("emboss", 0.10, 0.10),
    "Canvas": ("canvas", 0.16, 0.0),
    "Sand / stucco": ("sand", 0.16, 0.0),
    "Silk": ("silk", 0.08, 0.18),
    "Linen": ("linen", 0.14, 0.0),
    "Self-adhesive (peel & stick)": ("fibre", 0.03, 0.12),
}
FINISHES = {"Matte": 0.0, "Satin": 0.10, "Gloss": 0.22}

PAINT = (226, 220, 210)
CEILING = (244, 242, 238)
SIDE_L = (206, 199, 188)
SIDE_R = (212, 205, 194)


def _rgb(hex_or_tuple):
    if isinstance(hex_or_tuple, str):
        h = hex_or_tuple.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(hex_or_tuple)


def _grad(size, top, bottom) -> Image.Image:
    w, h = max(1, size[0]), max(1, size[1])
    a = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    arr = np.array(top, np.float32)[None, None, :] * (1 - a) + np.array(bottom, np.float32)[None, None, :] * a
    return Image.fromarray(np.repeat(arr, w, axis=1).astype("uint8"), "RGB")


# ======================================================================
# Furniture / opening drawings (front elevation, true scale)
# ======================================================================
def _box(xy):
    """[x0, y0, x1, y1] in the right order (tiny or odd-sized items can flip them)."""
    if len(xy) == 2 and not isinstance(xy[0], (int, float)):
        (x0, y0), (x1, y1) = xy
    else:
        x0, y0, x1, y1 = xy
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


class _SafeDraw:
    """ImageDraw that never fails on a too-small box (e.g. a 2 cm door or a very short sofa)."""

    def __init__(self, img: Image.Image):
        self._d = ImageDraw.Draw(img)

    def rectangle(self, xy, *a, **k):
        self._d.rectangle(_box(xy), *a, **k)

    def ellipse(self, xy, *a, **k):
        self._d.ellipse(_box(xy), *a, **k)

    def rounded_rectangle(self, xy, radius=0, *a, **k):
        b = _box(xy)
        radius = max(0, min(radius, (b[2] - b[0]) / 2, (b[3] - b[1]) / 2))
        self._d.rounded_rectangle(b, radius, *a, **k)

    def __getattr__(self, name):
        return getattr(self._d, name)


class _Painter:
    def __init__(self, img: Image.Image, ppm: float, ox: float, floor_y: float):
        self.img, self.d = img, _SafeDraw(img)
        self.ppm, self.ox, self.fy = ppm, ox, floor_y

    def X(self, m):
        return self.ox + m * self.ppm

    def Y(self, h):
        return self.fy - h * self.ppm

    def r(self, x, y, w, h):          # wall coords -> pixel box
        return [self.X(x), self.Y(y + h), self.X(x + w), self.Y(y)]

    def px(self, m):
        return max(1, int(round(m * self.ppm)))

    # ------------------------------------------------------------------
    def door(self, o: wl.Obstacle):
        d, p = self.d, self.px
        fr = p(0.06)
        x0, y0, x1, y1 = self.r(o.x, o.y, o.w, o.h)
        d.rectangle([x0 - fr, y0 - fr, x1 + fr, y1], fill=(250, 250, 248))
        self.img.paste(_grad((int(x1 - x0), int(y1 - y0)), (184, 140, 98), (160, 118, 80)), (int(x0), int(y0)))
        ins = p(0.09)
        mid = y0 + (y1 - y0) * 0.47
        for (a, b) in ((y0 + ins, mid - ins / 2), (mid + ins / 2, y1 - ins)):
            d.rectangle([x0 + ins, a, x1 - ins, b], outline=(140, 100, 66), width=max(1, p(0.012)))
        hx = x1 - p(0.09)
        hy = self.Y(1.0)
        d.ellipse([hx - p(0.02), hy - p(0.02), hx + p(0.02), hy + p(0.02)], fill=(214, 190, 120))

    def window(self, o: wl.Obstacle):
        d, p = self.d, self.px
        x0, y0, x1, y1 = self.r(o.x, o.y, o.w, o.h)
        fr = p(0.05)
        d.rectangle([x0 - fr, y0 - fr, x1 + fr, y1 + p(0.04)], fill=(250, 250, 248))
        sky = _grad((int(x1 - x0), int(y1 - y0)), (120, 172, 224), (206, 228, 246))
        sd = _SafeDraw(sky)
        wpx, hpx = sky.size
        rng = np.random.default_rng(int(o.x * 100 + o.w * 10))
        for i in range(6):
            cx = (i + 0.5) / 6 * wpx + rng.normal(0, wpx * 0.03)
            r = wpx * (0.12 + rng.random() * 0.06)
            sd.ellipse([cx - r, hpx * 0.62 - r * 0.6, cx + r, hpx * 1.2], fill=(78, 126, 80))
        self.img.paste(sky, (int(x0), int(y0)))
        bar = max(2, p(0.04))
        d.rectangle([x0, y0, x1, y1], outline=(250, 250, 248), width=bar)
        d.line([((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1)], fill=(250, 250, 248), width=bar)
        if o.h > 0.9:
            yy = y0 + (y1 - y0) * 0.38
            d.line([(x0, yy), (x1, yy)], fill=(250, 250, 248), width=max(2, bar * 2 // 3))
        d.rectangle([x0 - fr - p(0.03), y1, x1 + fr + p(0.03), y1 + p(0.05)], fill=(246, 246, 243))

    def opening(self, o: wl.Obstacle):
        x0, y0, x1, y1 = self.r(o.x, o.y, o.w, o.h)
        self.img.paste(_grad((int(x1 - x0), int(y1 - y0)), (120, 112, 100), (90, 82, 72)), (int(x0), int(y0)))
        self.d.rectangle([x0, y0, x1, y1], outline=(250, 250, 248), width=self.px(0.04))

    def fireplace(self, o: wl.Obstacle):
        d, p = self.d, self.px
        x0, y0, x1, y1 = self.r(o.x, o.y, o.w, o.h)
        d.rectangle([x0, y0, x1, y1], fill=(240, 236, 228))
        d.rectangle([x0 - p(0.05), y0, x1 + p(0.05), y0 + p(0.07)], fill=(232, 226, 216))
        fx0, fx1 = x0 + (x1 - x0) * 0.25, x1 - (x1 - x0) * 0.25
        d.rectangle([fx0, y0 + (y1 - y0) * 0.35, fx1, y1], fill=(40, 34, 30))

    def socket(self, o: wl.Obstacle):
        x0, y0, x1, y1 = self.r(o.x, o.y, o.w, o.h)
        self.d.rounded_rectangle([x0, y0, x1, y1], radius=self.px(0.008), fill=(250, 250, 250),
                                 outline=(200, 200, 200))

    def radiator(self, o: wl.Obstacle):
        d, p = self.d, self.px
        x0, y0, x1, y1 = self.r(o.x, o.y, o.w, o.h)
        d.rounded_rectangle([x0, y0, x1, y1], radius=p(0.02), fill=(246, 246, 246), outline=(214, 214, 214))
        n = max(4, int(o.w / 0.06))
        for i in range(1, n):
            xx = x0 + (x1 - x0) * i / n
            d.line([(xx, y0 + p(0.03)), (xx, y1 - p(0.03))], fill=(222, 222, 222), width=max(1, p(0.006)))

    def sofa(self, o: wl.Obstacle, colour=(96, 104, 120)):
        d, p = self.d, self.px
        x, y, w, h = o.x, o.y, o.w, o.h
        dark = tuple(max(0, c - 14) for c in colour)
        light = tuple(min(255, c + 14) for c in colour)
        leg = min(0.12, h * 0.14)
        d.rounded_rectangle(self.r(x, y + leg, w, h - leg), radius=p(0.07), fill=colour)
        arm_w = min(0.24, w * 0.12)
        d.rounded_rectangle(self.r(x - 0.01, y + leg, arm_w, (h - leg) * 0.62), radius=p(0.05), fill=dark)
        d.rounded_rectangle(self.r(x + w - arm_w + 0.01, y + leg, arm_w, (h - leg) * 0.62), radius=p(0.05), fill=dark)
        n = max(1, min(4, int((w - 2 * arm_w) / 0.6)))
        cw = (w - 2 * arm_w) / n
        for i in range(n):
            cx = x + arm_w + i * cw
            d.rounded_rectangle(self.r(cx + 0.015, y + leg + 0.03, cw - 0.03, (h - leg) * 0.32), radius=p(0.035), fill=light)
            d.rounded_rectangle(self.r(cx + 0.03, y + leg + (h - leg) * 0.40, cw - 0.06, (h - leg) * 0.52),
                                radius=p(0.045), fill=tuple(min(255, c + 8) for c in colour))
        if w > 1.2:
            d.rounded_rectangle(self.r(x + arm_w + 0.25, y + leg + (h - leg) * 0.40, 0.32, 0.30), radius=p(0.03),
                                fill=(214, 168, 92))
        for lx in (x + 0.08, x + w - 0.12):
            d.rectangle(self.r(lx, y, 0.04, leg), fill=(56, 42, 30))

    def bed(self, o: wl.Obstacle):
        d, p = self.d, self.px
        x, y, w, h = o.x, o.y, o.w, o.h
        d.rounded_rectangle(self.r(x, y + 0.25, w, h - 0.25), radius=p(0.06), fill=(150, 128, 112))
        d.rounded_rectangle(self.r(x + 0.05, y + 0.32, w - 0.1, h - 0.42), radius=p(0.05), fill=(166, 144, 126))
        d.rounded_rectangle(self.r(x - 0.04, y, w + 0.08, 0.55), radius=p(0.05), fill=(240, 238, 232))
        d.rounded_rectangle(self.r(x - 0.04, y + 0.36, w + 0.08, 0.16), radius=p(0.05), fill=(214, 206, 196))
        pw = (w - 0.3) / 2
        for i in range(2):
            d.rounded_rectangle(self.r(x + 0.1 + i * (pw + 0.1), y + 0.5, pw, 0.22), radius=p(0.06), fill=(250, 249, 246))
        d.rectangle(self.r(x - 0.04, y, w + 0.08, 0.08), fill=(110, 92, 80))

    def tv(self, o: wl.Obstacle):
        d, p = self.d, self.px
        d.rounded_rectangle(self.r(o.x, o.y, o.w, o.h), radius=p(0.01), fill=(24, 26, 30))
        d.rectangle(self.r(o.x + 0.02, o.y + 0.02, o.w - 0.04, o.h - 0.04), fill=(36, 40, 48))

    def table(self, o: wl.Obstacle, colour=(150, 112, 78)):
        d = self.d
        d.rectangle(self.r(o.x, o.top - 0.04, o.w, 0.04), fill=colour)
        for lx in (o.x + 0.04, o.x + o.w - 0.08):
            d.rectangle(self.r(lx, o.y, 0.04, o.h - 0.04), fill=tuple(c - 30 for c in colour))

    def chair(self, o: wl.Obstacle):
        d = self.d
        seat = o.y + o.h * 0.5
        d.rectangle(self.r(o.x, seat, o.w, 0.05), fill=(60, 60, 64))
        d.rectangle(self.r(o.x + o.w * 0.1, seat, o.w * 0.8, o.h * 0.5), outline=(60, 60, 64), width=self.px(0.025))
        for lx in (o.x + 0.03, o.x + o.w - 0.06):
            d.rectangle(self.r(lx, o.y, 0.03, o.h * 0.5), fill=(60, 60, 64))

    def cabinet(self, o: wl.Obstacle):
        d, p = self.d, self.px
        d.rectangle(self.r(o.x, o.y, o.w, o.h), fill=(236, 232, 224), outline=(196, 190, 180), width=p(0.01))
        n = max(1, int(o.w / 0.5))
        for i in range(1, n):
            xx = self.X(o.x + o.w * i / n)
            d.line([(xx, self.Y(o.top)), (xx, self.Y(o.y))], fill=(196, 190, 180), width=p(0.01))

    def plant(self, o: wl.Obstacle):
        d = self.d
        x, y, w, h = o.x, o.y, o.w, o.h
        pot_h = min(0.42, h * 0.38)
        d.polygon([(self.X(x + w * 0.15), self.Y(y + pot_h)), (self.X(x + w * 0.85), self.Y(y + pot_h)),
                   (self.X(x + w * 0.75), self.Y(y)), (self.X(x + w * 0.25), self.Y(y))], fill=(232, 228, 220))
        rng = np.random.default_rng(int(x * 1000) % 997)
        for _ in range(9):
            cx = x + w * (0.25 + rng.random() * 0.5)
            cy = y + pot_h + (h - pot_h) * (0.25 + rng.random() * 0.6)
            r = w * (0.18 + rng.random() * 0.12)
            g = (int(56 + rng.random() * 20), int(112 + rng.random() * 25), int(66 + rng.random() * 15))
            d.ellipse([self.X(cx - r), self.Y(cy + r), self.X(cx + r), self.Y(cy - r)], fill=g)

    def lamp(self, x: float, h: float = 1.6):
        d = self.d
        d.rectangle(self.r(x - 0.01, 0, 0.02, h - 0.3), fill=(60, 56, 52))
        d.ellipse(self.r(x - 0.14, 0, 0.28, 0.03), fill=(60, 56, 52))
        d.polygon([(self.X(x - 0.16), self.Y(h - 0.3)), (self.X(x + 0.16), self.Y(h - 0.3)),
                   (self.X(x + 0.1), self.Y(h)), (self.X(x - 0.1), self.Y(h))], fill=(244, 232, 206))

    def other(self, o: wl.Obstacle):
        self.d.rounded_rectangle(self.r(o.x, o.y, o.w, o.h), radius=self.px(0.03), fill=(170, 160, 150))

    def draw(self, o: wl.Obstacle):
        if o.w <= 0 or o.h <= 0:
            return
        fn = getattr(self, o.kind, None) or self.other
        try:
            fn(o)
        except (ValueError, ZeroDivisionError):          # odd sizes: a plain box is fine
            self.other(o)


def _shadow(img: Image.Image, boxes, blur: float, strength: int = 80) -> Image.Image:
    sh = Image.new("L", img.size, 0)
    sd = _SafeDraw(sh)
    for b in boxes:
        sd.rectangle(b, fill=strength)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    return Image.composite(Image.new("RGB", img.size, (40, 36, 32)), img, sh)


def scene_furniture(scene: str, wall_w: float, wall_h: float) -> List[wl.Obstacle]:
    """Default furniture for a scene, sized for the wall."""
    c = wall_w / 2
    items: List[wl.Obstacle] = []
    if scene == "living":
        sw = min(2.2, wall_w * 0.5)
        items.append(wl.Obstacle.make("sofa", x=c - sw / 2, w=sw, h=0.85))
        if wall_w > 2.6:
            items.append(wl.Obstacle.make("plant", x=min(wall_w - 0.55, c + sw / 2 + 0.3), w=0.45, h=1.1))
    elif scene == "bedroom":
        bw = min(1.8, wall_w * 0.5)
        items.append(wl.Obstacle.make("bed", x=c - bw / 2, w=bw, h=1.15))
        for sx in (c - bw / 2 - 0.55, c + bw / 2 + 0.1):
            if 0 <= sx <= wall_w - 0.45:
                items.append(wl.Obstacle.make("cabinet", x=sx, w=0.45, h=0.55))
    elif scene == "office":
        dw = min(1.6, wall_w * 0.45)
        items.append(wl.Obstacle.make("table", x=c - dw / 2, w=dw, h=0.75))
        items.append(wl.Obstacle.make("chair", x=c - 0.25, w=0.5, h=0.95))
        if wall_w > 2.6:
            items.append(wl.Obstacle.make("cabinet", x=0.2, w=0.8, h=1.0))
    elif scene == "cafe":
        n = max(1, int(wall_w / 1.6))
        for i in range(n):
            tx = (i + 0.5) * wall_w / n
            items.append(wl.Obstacle.make("table", x=tx - 0.35, w=0.7, h=0.75))
            items.append(wl.Obstacle.make("chair", x=tx - 0.75, w=0.42, h=0.9))
            items.append(wl.Obstacle.make("chair", x=tx + 0.33, w=0.42, h=0.9))
    for o in items:
        o.in_front = True
    return items


def render_room(walls: Sequence[wl.Wall], wall_img: Optional[Image.Image], scene: str = "living",
                ppm: float = 160.0, use_wall_items: bool = True, finish: str = "Matte",
                show_corners: bool = True) -> Image.Image:
    """A room with the given wall(s) at true scale and the design (`wall_img`) on it."""
    W = sum(w.width for w in walls)
    H = max(w.height for w in walls)
    side, ceil_m, floor_m = max(0.8, W * 0.16), 0.45, 0.85
    ppm = float(ppm)
    cw, ch = int((W + 2 * side) * ppm), int((H + ceil_m + floor_m) * ppm)
    img = Image.new("RGB", (cw, ch), CEILING)
    d = _SafeDraw(img)
    wx0, wy0 = side * ppm, ceil_m * ppm
    wx1, wy1 = wx0 + W * ppm, wy0 + H * ppm
    # side walls, ceiling, floor (one-point perspective box)
    d.polygon([(0, 0), (wx0, wy0), (wx0, wy1), (0, ch)], fill=SIDE_L)
    d.polygon([(cw, 0), (wx1, wy0), (wx1, wy1), (cw, ch)], fill=SIDE_R)
    d.polygon([(0, 0), (cw, 0), (wx1, wy0), (wx0, wy0)], fill=CEILING)
    floor = _grad((cw, ch - int(wy1)), (164, 122, 84) if scene != "cafe" else (150, 150, 146),
                  (118, 84, 54) if scene != "cafe" else (110, 110, 106))
    fm = Image.new("L", img.size, 0)
    _SafeDraw(fm).polygon([(wx0, wy1), (wx1, wy1), (cw, ch), (0, ch)], fill=255)
    fl = Image.new("RGB", img.size)
    fl.paste(floor, (0, int(wy1)))
    img = Image.composite(fl, img, fm)
    d = _SafeDraw(img)
    vx = cw / 2
    for i in range(-14, 15):
        xb = vx + i * cw / 14
        xt = vx + (xb - vx) * (W * ppm) / cw
        d.line([(xt, wy1), (xb, ch)], fill=(108, 76, 50) if scene != "cafe" else (132, 132, 128), width=max(1, int(ppm / 100)))
    # back wall
    if wall_img is not None:
        img.paste(wall_img.convert("RGB").resize((int(wx1 - wx0), int(wy1 - wy0)), Image.Resampling.LANCZOS),
                  (int(wx0), int(wy0)))
    else:
        d.rectangle([wx0, wy0, wx1, wy1], fill=PAINT)
    # lower walls and shaped walls: ceiling above them, stairs below a stair line
    xx = wx0
    lw_ = max(1, int(ppm / 120))
    for w in walls:
        if w.height < H - 1e-6 or w.shaped:
            pts = [(xx + x * ppm, wy1 - y * ppm) for x, y in w.outline()]
            m = Image.new("L", img.size, 0)
            md = _SafeDraw(m)
            md.rectangle([xx, wy0, xx + w.width * ppm, wy1], fill=255)
            md.polygon(pts, fill=0)
            img.paste(Image.new("RGB", img.size, (234, 231, 226)), (0, 0), m)
            d = _SafeDraw(img)
            if w.shape == "stairs":
                _draw_stairs(d, w, xx, wy1, ppm)
            # trim line along the top / sloped edges
            d.line(pts + pts[:1], fill=(250, 249, 246), width=max(2, int(ppm * 0.02)))
        xx += w.width * ppm
    # cornice + skirting (straight walls)
    xx = wx0
    for w in walls:
        x1_ = xx + w.width * ppm
        if not w.shaped:
            top_ = wy1 - w.height * ppm
            d.rectangle([xx, top_ - max(2, ppm * 0.03), x1_, top_], fill=(250, 249, 246))
        if w.shape != "stairs":
            d.rectangle([xx, wy1 - ppm * 0.08, x1_, wy1], fill=(248, 247, 244))
            d.line([(xx, wy1 - ppm * 0.08), (x1_, wy1 - ppm * 0.08)], fill=(205, 200, 192), width=lw_)
        xx = x1_
    # corners between walls
    if show_corners:
        xx = wx0
        for w in walls[:-1]:
            xx += w.width * ppm
            shade = 30 if w.corner_after == "inside" else -20
            band = Image.new("L", (max(2, int(ppm * 0.08)), int(wy1 - wy0)), 0)
            arr = np.linspace(0, abs(shade), band.width, dtype=np.float32)[None, :].repeat(band.height, 0)
            band = Image.fromarray(arr.astype("uint8"))
            col = (0, 0, 0) if shade > 0 else (255, 255, 255)
            img.paste(Image.new("RGB", band.size, col), (int(xx) - band.width, int(wy0)), band)
    # openings, then furniture with shadows
    painter = _Painter(img, ppm, 0, wy1)
    xx_m = side
    front: List[Tuple[float, wl.Obstacle]] = []
    for w in walls:
        items = list(w.obstacles) if use_wall_items else []
        if not any(o.in_front for o in items) and scene != "empty" and w.shape != "stairs":
            items += scene_furniture(scene, w.width, w.height)
        for o in items:
            oo = wl.Obstacle(**{**o.__dict__, "x": o.x + xx_m})
            if o.in_front:
                front.append((xx_m, oo))
            else:
                painter.draw(oo)
        xx_m += w.width
    boxes = []
    for _x, o in front:
        b = painter.r(o.x, o.y, o.w, o.h)
        boxes.append([b[0] + ppm * 0.05, b[1] + ppm * 0.04, b[2] - ppm * 0.02, b[3]])
    if boxes:
        img = _shadow(img, boxes, ppm * 0.09, 70)
        painter = _Painter(img, ppm, 0, wy1)
    for _x, o in sorted(front, key=lambda t: t[1].h):
        painter.draw(o)
    if scene == "living" and use_wall_items is not None and W > 2.5 and not any(
            o.kind == "plant" for _x, o in front):
        painter.lamp(side + 0.35, 1.6)
    # light: soft vignette + finish sheen
    img = _vignette(img, 0.18)
    s = FINISHES.get(finish, 0.0)
    if s:
        img = _sheen(img, (int(wx0), int(wy0), int(wx1), int(wy1)), s)
    return img


def _draw_stairs(d: ImageDraw.ImageDraw, w: wl.Wall, x0: float, floor_px: float, ppm: float) -> None:
    """Wooden stairs under the stair line of a staircase wall."""
    n = max(2, int(w.width / 0.02))
    xs = [w.width * k / n for k in range(n + 1)]
    lows = [w.span(x, x)[0] for x in xs]
    if max(lows) < 0.05:
        return
    under = [(x0 + x * ppm, floor_px - lo * ppm) for x, lo in zip(xs, lows)]
    d.polygon(under + [(x0 + w.width * ppm, floor_px), (x0, floor_px)], fill=(150, 112, 78))
    # steps: about 18 cm rise, cut into the stair line
    rise = 0.18
    k = 1
    while k * rise < max(lows):
        h = k * rise
        cross = [x for x, lo, lo2 in zip(xs, lows, lows[1:] + [lows[-1]]) if (lo - h) * (lo2 - h) <= 0 and lo != lo2]
        for xc in cross[:1]:
            d.rectangle([x0 + (xc - 0.27) * ppm, floor_px - h * ppm, x0 + (xc + 0.02) * ppm,
                         floor_px - (h - 0.035) * ppm], fill=(176, 134, 94))
        k += 1
    d.line(under, fill=(248, 247, 244), width=max(3, int(ppm * 0.05)))      # skirting along the stairs


def _vignette(img: Image.Image, strength: float) -> Image.Image:
    w, h = img.size
    y, x = np.ogrid[:h, :w]
    r = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h * 0.4) / (h * 0.6)) ** 2)
    f = 1 - strength * np.clip(r - 0.4, 0, 1) ** 1.5
    a = np.asarray(img, dtype=np.float32) * f[:, :, None]
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


def _sheen(img: Image.Image, box, strength: float) -> Image.Image:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w < 2 or h < 2:
        return img
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    band = np.exp(-(((xx / w) - 0.3 - 0.4 * (yy / h)) ** 2) / 0.02)
    a = np.asarray(img, dtype=np.float32).copy()
    reg = a[y0:y1, x0:x1]
    a[y0:y1, x0:x1] = reg + (255 - reg) * (band[:, :, None] * strength)
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


# ======================================================================
# Customer photo mockup
# ======================================================================
def photo_mockup(photo: Image.Image, H_photo_to_wall: np.ndarray, wall_w: float, wall_h: float,
                 wall_img: Image.Image, obstacles: Sequence[wl.Obstacle] = (), light: float = 0.85,
                 finish: str = "Matte", outline: Optional[Sequence[Tuple[float, float]]] = None) -> Image.Image:
    """Place `wall_img` (the wall area of the design) on the wall in the photo."""
    if cv2 is None:
        raise RuntimeError("OpenCV is needed for photo mockups")
    P = np.asarray(photo.convert("RGB"))
    Hh, Ww = P.shape[:2]
    dw, dh = wall_img.size
    # design px -> wall metres -> photo px
    D2W = np.diag([wall_w / dw, wall_h / dh, 1.0])
    M = np.linalg.inv(H_photo_to_wall) @ D2W
    warped = cv2.warpPerspective(np.asarray(wall_img.convert("RGB")), M, (Ww, Hh), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT)
    quad = cv2.warpPerspective(np.full((dh, dw), 255, np.uint8), M, (Ww, Hh), flags=cv2.INTER_LINEAR)
    mask = quad.astype(np.float32) / 255.0
    W2P = np.linalg.inv(H_photo_to_wall)
    if outline:          # shaped wall: the design only inside the outline
        pts = np.array([(x, wall_h - y, 1.0) for x, y in outline]) @ W2P.T
        shape_m = np.zeros((Hh, Ww), np.uint8)
        cv2.fillPoly(shape_m, [(pts[:, :2] / pts[:, 2:3]).astype(np.int32)], 255)
        mask = mask * (cv2.GaussianBlur(shape_m, (0, 0), 1.0).astype(np.float32) / 255.0)

    def poly(o: wl.Obstacle, grow: float = 0.0):
        pts = np.array([(o.x - grow, wall_h - o.top - grow), (o.x + o.w + grow, wall_h - o.top - grow),
                        (o.x + o.w + grow, wall_h - o.y + grow), (o.x - grow, wall_h - o.y + grow)], float)
        q = np.hstack([pts, np.ones((4, 1))]) @ W2P.T
        return (q[:, :2] / q[:, 2:3]).astype(np.int32)

    lab = cv2.cvtColor(P, cv2.COLOR_RGB2LAB).astype(np.float32)
    inside = quad > 127
    keep = np.zeros((Hh, Ww), np.uint8)
    for o in obstacles:
        if not o.in_front:
            cv2.fillPoly(keep, [poly(o)], 255)            # door / window: show the photo
    item_mask = np.zeros((Hh, Ww), np.uint8)
    for o in obstacles:
        if o.in_front:
            cv2.fillPoly(item_mask, [poly(o, 0.03)], 255)
    wall_px = inside & (keep == 0) & (item_mask == 0)
    if wall_px.sum() > 100:
        wall_lab = np.median(lab[wall_px], axis=0)
    else:
        wall_lab = np.median(lab[inside], axis=0) if inside.any() else np.array([200, 128, 128], np.float32)
    if item_mask.any():
        dist = np.linalg.norm(lab - wall_lab, axis=2)
        fg = ((dist > 16) & (item_mask > 0)).astype(np.uint8) * 255
        k = max(3, int(min(Hh, Ww) * 0.006)) | 1
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
        keep = np.maximum(keep, fg)
    keep = cv2.GaussianBlur(keep, (0, 0), 1.2).astype(np.float32) / 255.0
    # lighting: blurred photo brightness relative to the bare wall
    L = lab[:, :, 0]
    ref = float(np.median(L[wall_px])) if wall_px.sum() > 100 else float(L[inside].mean() if inside.any() else 128)
    sigma = max(3.0, 0.015 * max(Hh, Ww))
    Lb = cv2.GaussianBlur(L, (0, 0), sigma)
    shade = np.clip(Lb / max(ref, 1.0), 0.45, 1.35) ** light
    out = warped.astype(np.float32) * shade[:, :, None]
    s = FINISHES.get(finish, 0.0)
    if s:
        hi = np.clip((L - ref) / 60.0, 0, 1)[:, :, None]
        out = out + (255 - out) * hi * s * 2
    a = (mask * (1.0 - keep))[:, :, None]
    res = P.astype(np.float32) * (1 - a) + np.clip(out, 0, 255) * a
    return Image.fromarray(res.astype("uint8"))


# ======================================================================
# Material close-up
# ======================================================================
def _noise(size, sigma_px: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = Image.fromarray((rng.random((size[1], size[0])) * 255).astype("uint8"))
    if sigma_px > 0:
        n = n.filter(ImageFilter.GaussianBlur(sigma_px))
    a = np.asarray(n, dtype=np.float32)
    a = (a - a.mean()) / (a.std() + 1e-6)
    return a


def material_texture(size, kind: str, px_per_mm: float, seed: int = 7) -> np.ndarray:
    """Relief map (mean 0, std ~1) for a wallpaper material."""
    w, h = size
    if kind == "canvas" or kind == "linen":
        pitch = (0.6 if kind == "canvas" else 0.45) * px_per_mm
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        jitter = _noise(size, pitch * 2, seed) * (0.6 if kind == "linen" else 0.2)
        t = np.sin(2 * np.pi * xx / pitch + jitter) * np.sin(2 * np.pi * yy / pitch)
        t += 0.35 * _noise(size, 0.6, seed + 1)
        if kind == "linen":
            slub = _noise((w, h), px_per_mm * 0.3, seed + 3)
            t += 0.6 * np.repeat(slub[:, :1], w, axis=1)
    elif kind == "sand":
        t = _noise(size, 0.25 * px_per_mm, seed) + 0.6 * _noise(size, 1.2 * px_per_mm, seed + 1)
    elif kind == "emboss":
        base = _noise(size, 0.8 * px_per_mm, seed)
        gy, gx = np.gradient(base)
        t = (gx + gy) * 4 + 0.3 * _noise(size, 0.3, seed + 2)
    elif kind == "silk":
        streak = _noise((w, h), 0.3 * px_per_mm, seed)
        t = np.repeat(streak[:, :1], w, axis=1) * 0.7 + 0.3 * _noise(size, 0.4, seed + 1)
    else:   # fibre
        a = _noise(size, 0.5 * px_per_mm, seed)
        t = a + 0.4 * _noise(size, 0.15 * px_per_mm, seed + 1)
    return (t - t.mean()) / (t.std() + 1e-6)


def apply_material(img: Image.Image, material: str, finish: str = "Matte", px_per_mm: float = 4.0) -> Image.Image:
    kind, strength, sheen = MATERIALS.get(material, MATERIALS["Non-woven (smooth)"])
    tex = material_texture(img.size, kind, px_per_mm)
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    out = a * (1 + strength * 0.5 * tex[:, :, None])
    sh = sheen + FINISHES.get(finish, 0.0)
    if sh:
        h, w = tex.shape
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        band = np.exp(-(((xx / w) - 0.25 - 0.5 * (yy / h)) ** 2) / 0.05)
        out = out + (255 - out) * (band * sh * 0.6)[:, :, None] * (0.6 + 0.4 * np.clip(tex, 0, 2)[:, :, None] / 2)
    return Image.fromarray(np.clip(out, 0, 255).astype("uint8"))


def material_swatch(design_crop: Image.Image, material: str, finish: str, size_mm: float = 150.0,
                    px: int = 900) -> Image.Image:
    """Close-up (`size_mm` square at real scale) of the design on the material."""
    sq = ImageOps.fit(design_crop.convert("RGB"), (px, px), Image.Resampling.LANCZOS)
    return apply_material(sq, material, finish, px_per_mm=px / size_mm)
