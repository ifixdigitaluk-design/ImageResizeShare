"""
Wall plan, design placement and panel layout for murals / custom wallpaper.

Coordinates (all in metres)
  * Wall coordinates: x from the wall's LEFT edge, y from the FLOOR (up).
  * Artwork coordinates: origin at the top-left of the print area including
    bleed, x to the right, y DOWN. The wall run starts at (bleed_left,
    bleed_top) and the floor line is at y = bleed_top + tallest wall height.

A job can cover several walls in a row (a "run"), e.g. a design that wraps
round an inside corner. Walls stand side by side on the same floor line.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.core import units as u

OUTSIDE_CORNER_CLEARANCE = 0.15   # 6": each panel needs this much past an outside corner
INSIDE_CORNER_CLEARANCE = 0.03

# kind: (label, in front of the wall by default, colour)
OBSTACLE_KINDS: Dict[str, Tuple[str, bool, str]] = {
    "door": ("Door", False, "#e8890c"),
    "window": ("Window", False, "#2f7de1"),
    "opening": ("Opening / arch", False, "#0891b2"),
    "fireplace": ("Fireplace", False, "#b45309"),
    "socket": ("Socket / switch", False, "#64748b"),
    "radiator": ("Radiator", True, "#94a3b8"),
    "sofa": ("Sofa", True, "#7c4ddb"),
    "bed": ("Bed / headboard", True, "#db2777"),
    "tv": ("TV / screen", True, "#1f2937"),
    "table": ("Table / desk", True, "#a16207"),
    "chair": ("Chair", True, "#9333ea"),
    "cabinet": ("Cabinet / shelf", True, "#57534e"),
    "plant": ("Plant", True, "#12a37a"),
    "other": ("Other", True, "#475569"),
}

# Typical sizes used when the user adds an item by hand (w, h, y from floor)
DEFAULT_SIZES = {
    "door": (0.84, 2.04, 0.0), "window": (1.20, 1.20, 0.90), "opening": (1.00, 2.10, 0.0),
    "fireplace": (1.20, 1.10, 0.0), "socket": (0.09, 0.09, 0.30), "radiator": (1.00, 0.60, 0.15),
    "sofa": (2.00, 0.85, 0.0), "bed": (1.60, 1.10, 0.0), "tv": (1.25, 0.72, 1.00),
    "table": (1.20, 0.75, 0.0), "chair": (0.50, 0.90, 0.0), "cabinet": (1.00, 0.90, 0.0),
    "plant": (0.45, 1.10, 0.0), "other": (0.60, 0.60, 0.0),
}

MEDIA_WIDTHS = [  # (label, printable width m)
    ("53 cm wallpaper", 0.53), ("70 cm wallpaper", 0.70), ("1.00 m roll", 1.00),
    ('42" roll (1.07 m)', 1.067), ('54" roll (1.37 m)', 1.372), ('60" roll (1.52 m)', 1.524),
    ('64" roll (1.63 m)', 1.626), ("3.20 m wide roll", 3.20),
]

STATUSES = ["Enquiry", "Measured", "Designing", "Proof sent", "Approved", "Printing",
            "Printed", "Installed", "Completed", "On hold", "Cancelled"]
STATUS_COLOURS = {"Enquiry": "#64748b", "Measured": "#0891b2", "Designing": "#7c3aed",
                  "Proof sent": "#d97706", "Approved": "#16a34a", "Printing": "#2563eb",
                  "Printed": "#1d4ed8", "Installed": "#15803d", "Completed": "#166534",
                  "On hold": "#a16207", "Cancelled": "#b91c1c"}


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _from_dict(cls, d: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (d or {}).items() if k in names})


# ======================================================================
# Wall shapes (sloped ceilings, gables, staircases, arches)
# ======================================================================
SHAPES = {
    "rect": "Rectangle",
    "slope": "Sloped ceiling (attic)",
    "gable": "Pitched / gable end",
    "stairs": "Staircase",
    "arch": "Arched top",
}


def default_shape_params(shape: str, width: float, height: float) -> dict:
    W, H = width, height
    if shape == "slope":
        return {"left_h": round(H, 3), "right_h": round(H * 0.45, 3), "break_x": round(W * 0.35, 3), "mirror": False}
    if shape == "gable":
        return {"side_h": round(H * 0.55, 3), "peak_x": round(W / 2, 3)}
    if shape == "stairs":
        return {"start_x": 0.0, "end_x": round(W, 3), "rise": round(min(H * 0.6, 2.6), 3),
                "top_left": round(H, 3), "top_right": round(H, 3), "mirror": False}
    if shape == "arch":
        return {"side_h": round(H * 0.75, 3)}
    return {}


def shape_height(shape: str, p: dict, current: float) -> float:
    """Bounding height implied by the shape parameters."""
    if shape == "slope":
        return max(float(p.get("left_h", current)), float(p.get("right_h", current)))
    if shape == "stairs":
        return max(float(p.get("top_left", current)), float(p.get("top_right", current)))
    return current


def shape_outline(shape: str, p: dict, W: float, H: float, arc_points: int = 48) -> List[Tuple[float, float]]:
    p = p or {}
    if shape == "slope":
        lh = min(H, max(0.05, float(p.get("left_h", H))))
        rh = min(H, max(0.05, float(p.get("right_h", H * 0.45))))
        bx = min(W, max(0.0, float(p.get("break_x", 0.0))))
        pts = [(0.0, 0.0), (W, 0.0), (W, rh), (bx, lh), (0.0, lh)]
        if bx <= 1e-6:
            pts = [(0.0, 0.0), (W, 0.0), (W, rh), (0.0, lh)]
        return _mirror(pts, W) if p.get("mirror") else pts
    if shape == "gable":
        sh = min(H, max(0.0, float(p.get("side_h", H * 0.55))))
        px = min(W, max(0.0, float(p.get("peak_x", W / 2))))
        return [(0.0, 0.0), (W, 0.0), (W, sh), (px, H), (0.0, sh)]
    if shape == "stairs":
        a = min(W, max(0.0, float(p.get("start_x", 0.0))))
        b = min(W, max(a, float(p.get("end_x", W))))
        r = min(H - 0.05, max(0.0, float(p.get("rise", 0.0))))
        tl = min(H, max(r + 0.05, float(p.get("top_left", H))))
        tr = min(H, max(r + 0.05, float(p.get("top_right", H))))
        pts = [(0.0, 0.0)]
        if a > 1e-6:
            pts.append((a, 0.0))
        pts.append((b, r))
        if b < W - 1e-6:
            pts.append((W, r))
        pts += [(W, tr), (0.0, tl)]
        return _mirror(pts, W) if p.get("mirror") else pts
    if shape == "arch":
        sh = min(H, max(0.0, float(p.get("side_h", H * 0.75))))
        pts = [(0.0, 0.0), (W, 0.0), (W, sh)]
        for k in range(1, arc_points):
            t = math.pi * k / arc_points
            pts.append((W / 2 + W / 2 * math.cos(t), sh + (H - sh) * math.sin(t)))
        pts.append((0.0, sh))
        return pts
    return [(0.0, 0.0), (W, 0.0), (W, H), (0.0, H)]


def _mirror(pts, W):
    return [(W - x, y) for x, y in reversed(pts)]


def polygon_area(pts) -> float:
    a = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def _vertical_hits(pts, x: float) -> List[float]:
    """y values where the polygon outline crosses the vertical line at x."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        if x0 == x1:
            if abs(x - x0) < 1e-9:
                out += [y0, y1]
            continue
        if min(x0, x1) - 1e-9 <= x <= max(x0, x1) + 1e-9:
            t = (x - x0) / (x1 - x0)
            out.append(y0 + (y1 - y0) * t)
    return out


# ======================================================================
# Model
# ======================================================================
@dataclass
class Obstacle:
    kind: str = "other"
    x: float = 0.0        # from the wall's left edge (m)
    y: float = 0.0        # bottom of the item, from the floor (m)
    w: float = 0.5
    h: float = 0.5
    in_front: bool = True  # furniture in front of the wall (True) or opening/fixture in the wall
    label: str = ""
    blank_print: bool = False   # leave unprinted in the panel files (big windows)
    source: str = "manual"      # manual / detected
    id: str = field(default_factory=_uid)

    @classmethod
    def make(cls, kind: str, x: float = 0.0, y: Optional[float] = None, w: Optional[float] = None,
             h: Optional[float] = None, **kw) -> "Obstacle":
        dw, dh, dy = DEFAULT_SIZES.get(kind, DEFAULT_SIZES["other"])
        return cls(kind=kind, x=x, y=dy if y is None else y, w=dw if w is None else w,
                   h=dh if h is None else h, in_front=OBSTACLE_KINDS.get(kind, OBSTACLE_KINDS["other"])[1], **kw)

    @property
    def name(self) -> str:
        return self.label or OBSTACLE_KINDS.get(self.kind, OBSTACLE_KINDS["other"])[0]

    @property
    def colour(self) -> str:
        return OBSTACLE_KINDS.get(self.kind, OBSTACLE_KINDS["other"])[2]

    @property
    def top(self) -> float:
        return self.y + self.h

    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def clamp(self, wall_w: float, wall_h: float) -> None:
        self.w = min(max(0.02, self.w), wall_w)
        self.h = min(max(0.02, self.h), wall_h)
        self.x = min(max(0.0, self.x), wall_w - self.w)
        self.y = min(max(0.0, self.y), wall_h - self.h)


@dataclass
class Wall:
    name: str = "Wall 1"
    width: float = 3.0
    height: float = 2.5
    obstacles: List[Obstacle] = field(default_factory=list)
    corner_after: str = "inside"     # corner to the next wall: inside / outside / flat
    photo: str = ""                  # survey photo (path relative to the job folder)
    corners: list = field(default_factory=list)   # wall corners in the photo TL, TR, BR, BL
    survey: dict = field(default_factory=dict)    # extra survey data (accuracy, reference …)
    shape: str = "rect"              # rect / slope / gable / stairs / arch (see SHAPES)
    shape_params: dict = field(default_factory=dict)
    id: str = field(default_factory=_uid)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Wall":
        w = _from_dict(cls, d)
        w.obstacles = [_from_dict(Obstacle, o) for o in (d or {}).get("obstacles", [])]
        return w

    # ---------------- shape ----------------
    @property
    def shaped(self) -> bool:
        return self.shape in SHAPES and self.shape != "rect"

    def outline(self) -> List[Tuple[float, float]]:
        """Wall outline in wall coordinates (x from the left, y up from the floor), anticlockwise."""
        return shape_outline(self.shape, self.shape_params, self.width, self.height)

    def area(self) -> float:
        if not self.shaped:
            return self.width * self.height
        return polygon_area(self.outline())

    def span(self, x0: float, x1: float) -> Tuple[float, float]:
        """(lowest bottom, highest top) of the wall between x0 and x1 (wall coordinates)."""
        if not self.shaped:
            return 0.0, self.height
        a, b = max(0.0, min(x0, x1)), min(self.width, max(x0, x1))
        if b <= a:
            a = b = min(max(0.0, x0), self.width)
        pts = self.outline()
        xs = [a, b] + [x for x, _y in pts if a < x < b]
        lo, hi = float("inf"), float("-inf")
        for x in xs:
            for y in _vertical_hits(pts, x):
                lo, hi = min(lo, y), max(hi, y)
        if lo == float("inf"):
            return 0.0, self.height
        return lo, hi

    def openings_area(self) -> float:
        return sum(_clipped_area(o, self) for o in self.obstacles if not o.in_front)

    def hidden_area(self) -> float:
        """Wall area hidden behind furniture (as seen from the front)."""
        return sum(_clipped_area(o, self) for o in self.obstacles if o.in_front)


def _clipped_area(o: Obstacle, w: Wall) -> float:
    x0, x1 = max(0.0, o.x), min(w.width, o.x + o.w)
    y0, y1 = max(0.0, o.y), min(w.height, o.y + o.h)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    if not w.shaped:
        return (x1 - x0) * (y1 - y0)
    # shaped wall: only the part of the item inside the outline (strips across the item)
    n = 40
    dx = (x1 - x0) / n
    total = 0.0
    for k in range(n):
        lo, hi = w.span(x0 + (k + 0.5) * dx, x0 + (k + 0.5) * dx)
        total += max(0.0, min(y1, hi) - max(y0, lo)) * dx
    return total


@dataclass
class Placement:
    mode: str = "fill"        # fill / fit_width / fit_height / custom
    anchor_x: str = "center"  # left / center / right
    anchor_y: str = "center"  # top / center / bottom
    scale: float = 0.0        # design pixels per metre (custom mode)
    ox: float = 0.0           # design top-left in artwork metres (custom mode)
    oy: float = 0.0
    flip_h: bool = False
    background: str = "#ffffff"


@dataclass
class PanelSpec:
    media_width: float = 1.00
    overlap: float = 0.025     # total overlap at each seam (half on each panel)
    bleed_top: float = 0.05
    bleed_bottom: float = 0.05
    bleed_left: float = 0.05
    bleed_right: float = 0.05
    mode: str = "equal"        # equal / full / manual
    seams: List[float] = field(default_factory=list)   # manual seams (artwork metres)
    right_to_left: bool = False
    roll_length: float = 50.0
    min_panel: float = 0.20
    trim_to_shape: bool = True   # shorter panels where the wall is lower (slopes, stairs, lower walls)


@dataclass
class Panel:
    index: int                # 1-based, in hanging order
    x0: float                 # artwork metres incl. overlaps
    x1: float
    y0: float
    y1: float
    seam_left: Optional[float] = None
    seam_right: Optional[float] = None

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class ResolvedPlacement:
    scale: float     # design px per metre
    ox: float        # design top-left (artwork m)
    oy: float
    flip_h: bool
    design_w_m: float
    design_h_m: float

    @property
    def dpi(self) -> float:
        return self.scale * u.M_PER_IN

    def covers(self, aw: float, ah: float, tol: float = 1e-4) -> bool:
        return (self.ox <= tol and self.oy <= tol and self.ox + self.design_w_m >= aw - tol
                and self.oy + self.design_h_m >= ah - tol)

    def to_design_px(self, x: float, y: float, design_w_px: int) -> Tuple[float, float]:
        px = (x - self.ox) * self.scale
        if self.flip_h:
            px = design_w_px - px
        return px, (y - self.oy) * self.scale


@dataclass
class Job:
    job_no: str = ""
    customer: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    room: str = ""
    status: str = "Enquiry"
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)
    walls: List[Wall] = field(default_factory=lambda: [Wall()])
    design: str = ""                # current design (path relative to the job folder)
    design_name: str = ""
    design_kind: str = "image"      # image / pattern
    pattern: dict = field(default_factory=dict)
    placement: Placement = field(default_factory=Placement)
    panels: PanelSpec = field(default_factory=PanelSpec)
    material: str = "Non-woven (smooth)"
    finish: str = "Matte"
    view_distance: float = 1.5
    unit: str = "m"
    print_dpi: int = 100
    colour_profile: str = "sRGB IEC61966-2.1"
    output_preset: str = "Print house – TIFF RGB 100 dpi"
    notes: str = ""
    proof_version: int = 0
    proof_file: str = ""
    mockup_file: str = ""
    approved_by: str = ""
    approved_on: str = ""
    history: list = field(default_factory=list)
    layers: list = field(default_factory=list)          # text / logo on top of the design (app.core.layers)
    install_date: str = ""                              # YYYY-MM-DD
    install_time: str = ""                              # e.g. 10:00
    installer: str = ""
    installed_photos: list = field(default_factory=list)  # job-relative paths
    schema: int = 1

    # ---------------- serialisation ----------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["walls"] = [w.to_dict() for w in self.walls]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        j = _from_dict(cls, d)
        j.walls = [Wall.from_dict(w) for w in d.get("walls", [])] or [Wall()]
        j.placement = _from_dict(Placement, d.get("placement", {}))
        j.panels = _from_dict(PanelSpec, d.get("panels", {}))
        j.history = list(d.get("history", []))
        return j

    def copy(self) -> "Job":
        return Job.from_dict(self.to_dict())

    def log(self, event: str) -> None:
        self.history.append({"time": _now(), "event": event})
        self.updated = _now()

    def set_status(self, status: str) -> None:
        if status != self.status:
            self.status = status
            self.log(f"Status → {status}")

    # ---------------- geometry ----------------
    @property
    def run_width(self) -> float:
        return sum(w.width for w in self.walls)

    @property
    def run_height(self) -> float:
        return max((w.height for w in self.walls), default=0.0)

    @property
    def art_width(self) -> float:
        return self.run_width + self.panels.bleed_left + self.panels.bleed_right

    @property
    def art_height(self) -> float:
        return self.run_height + self.panels.bleed_top + self.panels.bleed_bottom

    def wall_x(self, index: int) -> float:
        """Left edge of wall `index` in artwork coordinates."""
        return self.panels.bleed_left + sum(w.width for w in self.walls[:index])

    @property
    def floor_y(self) -> float:
        return self.panels.bleed_top + self.run_height

    def wall_rect(self, index: int) -> Tuple[float, float, float, float]:
        """(x0, y0, x1, y1) of a wall in artwork coordinates (y down)."""
        w = self.walls[index]
        x0 = self.wall_x(index)
        return x0, self.floor_y - w.height, x0 + w.width, self.floor_y

    def obstacle_rect(self, wall_index: int, o: Obstacle) -> Tuple[float, float, float, float]:
        x = self.wall_x(wall_index) + o.x
        return x, self.floor_y - o.top, x + o.w, self.floor_y - o.y

    def all_obstacles(self):
        for i, w in enumerate(self.walls):
            for o in w.obstacles:
                yield i, o

    def corners(self) -> List[Tuple[float, str]]:
        """Corner positions between walls (artwork x, 'inside'/'outside'/'flat')."""
        out = []
        for i, w in enumerate(self.walls[:-1]):
            out.append((self.wall_x(i + 1), w.corner_after))
        return out

    def wall_outline(self, index: int) -> List[Tuple[float, float]]:
        """Outline of a wall in artwork coordinates (y down)."""
        x0 = self.wall_x(index)
        return [(x0 + x, self.floor_y - y) for x, y in self.walls[index].outline()]

    @property
    def uneven(self) -> bool:
        """True when the walls don't fill the whole print rectangle (shapes or different heights)."""
        return any(w.shaped for w in self.walls) or len({round(w.height, 4) for w in self.walls}) > 1

    def coverage(self, x0: float, x1: float) -> Tuple[float, float]:
        """Artwork y range (top, bottom) the walls need between artwork x0 and x1, without bleed."""
        top, bottom = float("inf"), float("-inf")
        for i, w in enumerate(self.walls):
            wx = self.wall_x(i)
            a, b = max(x0, wx), min(x1, wx + w.width)
            if b < a:
                continue
            lo, hi = w.span(a - wx, b - wx)
            top = min(top, self.floor_y - hi)
            bottom = max(bottom, self.floor_y - lo)
        if top == float("inf"):          # only bleed at the side: use the nearest wall
            i = 0 if x1 <= self.panels.bleed_left + 1e-9 else len(self.walls) - 1
            w = self.walls[i]
            edge = 0.0 if i == 0 else w.width
            lo, hi = w.span(edge, edge)
            return self.floor_y - hi, self.floor_y - lo
        return top, bottom

    def wall_area(self) -> float:
        return sum(w.area() for w in self.walls)

    def openings_area(self) -> float:
        return sum(w.openings_area() for w in self.walls)

    def hidden_area(self) -> float:
        return sum(w.hidden_area() for w in self.walls)


# ======================================================================
# Placement
# ======================================================================
def resolve_placement(job: Job, design_px: Tuple[int, int]) -> ResolvedPlacement:
    """Where the design sits on the artwork (scale in design px per metre)."""
    dw, dh = max(1, design_px[0]), max(1, design_px[1])
    aw, ah = max(1e-6, job.art_width), max(1e-6, job.art_height)
    pl = job.placement
    if pl.mode == "custom" and pl.scale > 0:
        s = pl.scale
        return ResolvedPlacement(s, pl.ox, pl.oy, pl.flip_h, dw / s, dh / s)
    if pl.mode == "fit_width":
        s = dw / aw
    elif pl.mode == "fit_height":
        s = dh / ah
    else:   # fill: largest scale that still covers the whole artwork
        s = min(dw / aw, dh / ah)
    W, H = dw / s, dh / s
    ox = {"left": 0.0, "right": aw - W}.get(pl.anchor_x, (aw - W) / 2)
    oy = {"top": 0.0, "bottom": ah - H}.get(pl.anchor_y, (ah - H) / 2)
    return ResolvedPlacement(s, ox, oy, pl.flip_h, W, H)


def to_custom(job: Job, design_px) -> None:
    """Freeze the current automatic placement so it can be moved by hand."""
    r = resolve_placement(job, design_px)
    job.placement = replace(job.placement, mode="custom", scale=r.scale, ox=r.ox, oy=r.oy)


def zoom_placement(job: Job, design_px, factor: float, cx: float, cy: float) -> None:
    """Scale the design by `factor` around artwork point (cx, cy)."""
    to_custom(job, design_px)
    p = job.placement
    new_scale = p.scale / factor            # fewer px per metre = design looks bigger
    p.ox = cx - (cx - p.ox) * factor
    p.oy = cy - (cy - p.oy) * factor
    p.scale = new_scale


def cover_scale(job: Job, design_px) -> float:
    dw, dh = design_px
    return min(dw / job.art_width, dh / job.art_height)


# ======================================================================
# Panels
# ======================================================================
def auto_seams(spec: PanelSpec, aw: float) -> List[float]:
    mw, o = spec.media_width, max(0.0, spec.overlap)
    if aw <= mw + 1e-9 or mw <= o:
        return []
    if spec.mode == "full":
        # full-width panels from the left, the last one takes what is left
        seams, s = [], mw - o / 2
        while True:
            seams.append(s)
            if aw <= s - o / 2 + mw + 1e-9:
                break
            s += mw - o
        last = aw - seams[-1] + o / 2
        if last < spec.min_panel:
            # share the last two panels equally instead of a thin sliver
            start = (seams[-2] - o / 2) if len(seams) > 1 else 0.0
            p = (aw - start + o) / 2
            seams[-1] = start + p - o / 2
        return seams
    n = max(1, math.ceil((aw - o) / (mw - o) - 1e-9))
    p = (aw + (n - 1) * o) / n
    seams = []
    pos = p - o / 2
    for _ in range(n - 1):
        seams.append(pos)
        pos += p - o
    return seams


def current_seams(job: Job) -> List[float]:
    sp = job.panels
    if sp.mode == "manual" and sp.seams:
        aw = job.art_width
        return sorted(s for s in sp.seams if 0.01 < s < aw - 0.01)
    return auto_seams(sp, job.art_width)


def panels_from_seams(seams: List[float], aw: float, ah: float, overlap: float,
                      right_to_left: bool = False) -> List[Panel]:
    edges = [0.0] + sorted(seams) + [aw]
    o = max(0.0, overlap)
    out = []
    for i in range(len(edges) - 1):
        sl = edges[i] if i > 0 else None
        sr = edges[i + 1] if i + 1 < len(edges) - 1 else None
        x0 = edges[i] - (o / 2 if sl is not None else 0.0)
        x1 = edges[i + 1] + (o / 2 if sr is not None else 0.0)
        out.append(Panel(i + 1, x0, x1, 0.0, ah, sl, sr))
    if right_to_left:
        for k, p in enumerate(reversed(out)):
            p.index = k + 1
        out.sort(key=lambda p: p.index)
    return out


def compute_panels(job: Job) -> List[Panel]:
    panels = panels_from_seams(current_seams(job), job.art_width, job.art_height, job.panels.overlap,
                               job.panels.right_to_left)
    if job.panels.trim_to_shape and job.uneven:
        sp = job.panels
        for p in panels:
            top, bottom = job.coverage(p.x0, p.x1)
            p.y0 = max(0.0, round(top - sp.bleed_top, 4))
            p.y1 = min(job.art_height, round(bottom + sp.bleed_bottom, 4))
    return panels


def set_manual_seams(job: Job, seams: List[float]) -> None:
    job.panels.mode = "manual"
    job.panels.seams = sorted(seams)


def move_seam(job: Job, index: int, new_pos: float) -> float:
    """Drag one seam; keeps panels within the media width. Returns the position used."""
    seams = current_seams(job)
    if not 0 <= index < len(seams):
        return new_pos
    sp, aw = job.panels, job.art_width
    o, mw = sp.overlap, sp.media_width
    left = seams[index - 1] if index > 0 else None
    right = seams[index + 1] if index + 1 < len(seams) else None
    # panel to the left: width = pos - left + o  (or pos + o/2 for the first)
    lo = (left + sp.min_panel - o) if left is not None else (sp.min_panel - o / 2)
    hi_l = (left + mw - o) if left is not None else (mw - o / 2)
    # panel to the right
    hi = (right - sp.min_panel + o) if right is not None else (aw - sp.min_panel + o / 2)
    lo_r = (right - mw + o) if right is not None else (aw - mw + o / 2)
    lo, hi = max(lo, lo_r), min(hi, hi_l)
    pos = min(max(new_pos, lo), hi) if lo <= hi else new_pos
    seams[index] = pos
    set_manual_seams(job, seams)
    return pos


def add_seam(job: Job, pos: float) -> None:
    s = current_seams(job) + [pos]
    set_manual_seams(job, s)


def remove_seam(job: Job, index: int) -> None:
    s = current_seams(job)
    if 0 <= index < len(s):
        s.pop(index)
        set_manual_seams(job, s)


@dataclass
class Issue:
    level: str      # error / warn / info
    text: str
    x: Optional[float] = None   # artwork x for highlighting


def panel_issues(job: Job, panels: Optional[List[Panel]] = None) -> List[Issue]:
    sp = job.panels
    panels = panels if panels is not None else compute_panels(job)
    out: List[Issue] = []
    for p in panels:
        if p.width > sp.media_width + 1e-6:
            out.append(Issue("error", f"Panel {p.index} is {p.width * 100:.1f} cm wide – wider than the "
                                      f"{sp.media_width * 100:.0f} cm media.", (p.x0 + p.x1) / 2))
        elif p.width < sp.min_panel - 1e-6:
            out.append(Issue("warn", f"Panel {p.index} is only {p.width * 100:.1f} cm wide – hard to hang. "
                                     "Move the seams or use Equal panels.", (p.x0 + p.x1) / 2))
    if job.art_height > sp.roll_length + 1e-6:
        out.append(Issue("error", f"Panels are {job.art_height:.2f} m long – longer than the "
                                  f"{sp.roll_length:.1f} m roll."))
    seams = current_seams(job)
    for cx, kind in job.corners():
        for s in seams:
            d = abs(s - cx)
            if kind == "outside" and d < OUTSIDE_CORNER_CLEARANCE:
                out.append(Issue("warn", f"A seam is {d * 100:.0f} cm from an outside corner – keep at least "
                                         f"{OUTSIDE_CORNER_CLEARANCE * 100:.0f} cm (6\") of one panel round "
                                         "the corner.", s))
            elif kind == "inside" and INSIDE_CORNER_CLEARANCE < d < 0.06:
                out.append(Issue("info", "A seam is just next to an inside corner – put it right in the corner "
                                         "or move it away.", s))
    return out


# ======================================================================
# Seam placement that avoids faces and fine detail
# ======================================================================
def optimise_seams(job: Job, risk: np.ndarray, step: float = 0.01, keep_count: bool = False) -> List[float]:
    """Choose seam positions that avoid high-risk columns.

    `risk` is sampled every `step` metres across the artwork width (len ≈ aw/step).
    Constraints: every panel ≤ media width and ≥ min panel. Outside corners are
    avoided (± clearance). Ties are broken towards equal panel widths.
    """
    sp, aw = job.panels, job.art_width
    o, mw, mn = sp.overlap, sp.media_width, sp.min_panel
    n_auto = len(auto_seams(replace(sp, mode="equal"), aw))
    if n_auto == 0:
        return []
    G = int(round(aw / step)) + 1
    r = np.zeros(G, dtype=float)
    if risk is not None and len(risk):
        xs = np.linspace(0, len(risk) - 1, G)
        r = np.interp(xs, np.arange(len(risk)), risk.astype(float))
    pos = np.arange(G) * step
    cost = r.copy()
    for cx, kind in job.corners():
        if kind == "outside":
            cost[np.abs(pos - cx) < OUTSIDE_CORNER_CLEARANCE] += 50.0
        elif kind == "inside":
            near = (np.abs(pos - cx) > INSIDE_CORNER_CLEARANCE) & (np.abs(pos - cx) < 0.06)
            cost[near] += 2.0
    best = None
    counts = [n_auto] if keep_count else [n_auto, n_auto + 1]
    for n in counts:
        res = _dp_seams(cost, pos, n, aw, o, mw, mn, step)
        if res is None:
            continue
        seams, total = res
        total += 0.15 * (n - n_auto)          # a bit of cost for an extra panel
        if best is None or total < best[1] - 1e-9:
            best = (seams, total)
    return best[0] if best else auto_seams(sp, aw)


def _dp_seams(cost, pos, n, aw, o, mw, mn, step):
    G = len(pos)
    ideal = (aw + n * o) / (n + 1)                # equal panel width for n seams
    inf = 1e18
    # first seam: first panel width = s + o/2
    first_w = pos + o / 2
    valid = (first_w <= mw + 1e-9) & (first_w >= mn - 1e-9)
    D = np.where(valid, cost + 0.02 * ((first_w - ideal) / max(ideal, 1e-6)) ** 2, inf)
    back = []
    dmin = max(1, int(math.ceil((mn - o) / step - 1e-9)))
    dmax = int(math.floor((mw - o) / step + 1e-9))
    if dmax < dmin:
        return None
    for _ in range(1, n):
        newD = np.full(G, inf)
        arg = np.zeros(G, dtype=int)
        for d in range(dmin, dmax + 1):
            prev = np.full(G, inf)
            prev[d:] = D[:G - d]
            better = prev < newD
            newD = np.where(better, prev, newD)
            arg = np.where(better, np.arange(G) - d, arg)
        w = (np.arange(G) - arg) * step + o
        newD = newD + cost + 0.02 * ((w - ideal) / max(ideal, 1e-6)) ** 2
        back.append(arg)
        D = newD
    last_w = aw - pos + o / 2
    ok = (last_w <= mw + 1e-9) & (last_w >= mn - 1e-9)
    D = np.where(ok, D + 0.02 * ((last_w - ideal) / max(ideal, 1e-6)) ** 2, inf)
    g = int(np.argmin(D))
    if D[g] >= inf / 2:
        return None
    total = float(D[g])
    idx = [g]
    for arg in reversed(back):
        g = int(arg[g])
        idx.append(g)
    idx.reverse()
    return [float(pos[i]) for i in idx], total


# ======================================================================
# Resolution / viewing distance
# ======================================================================
def required_ppi(view_distance_m: float) -> float:
    """Pixels per inch the eye can resolve at this distance (1 arc-minute), 50…150."""
    d_in = max(0.1, view_distance_m) / u.M_PER_IN
    return max(50.0, min(150.0, 3438.0 / d_in))


def ppi_quality(ppi: float, view_distance_m: float) -> Tuple[str, str]:
    req = required_ppi(view_distance_m)
    if ppi >= max(100.0, req * 1.5):
        return "excellent", f"{ppi:.0f} ppi at full size – excellent"
    if ppi >= req:
        return "good", f"{ppi:.0f} ppi at full size – good for {view_distance_m:.1f} m viewing"
    need = max(100.0, req) / max(ppi, 1e-6)
    return "low", (f"{ppi:.0f} ppi at full size – soft up close. AI-upscale about {math.ceil(need)}× "
                   f"(needs {req:.0f}+ ppi at {view_distance_m:.1f} m)")


# ======================================================================
# Rolls & area
# ======================================================================
@dataclass
class RollEstimate:
    strips: int
    strip_length: float
    strips_per_roll: int
    rolls: int
    waste_pct: float


def rolls_needed(width: float, height: float, roll_width: float = 0.53, roll_length: float = 10.05,
                 repeat: float = 0.0, drop: str = "straight", trim: float = 0.10,
                 extra_pct: float = 10.0) -> RollEstimate:
    """Standard wallpaper rolls needed for a wall (pattern repeat aware)."""
    strips = max(1, math.ceil(width / roll_width - 1e-9))
    length = height + trim
    if repeat > 0:
        length = math.ceil(length / repeat - 1e-9) * repeat
        if drop == "half":
            length += repeat / 2
    per_roll = max(0, int(roll_length // length))
    if per_roll == 0:
        return RollEstimate(strips, length, 0, 0, 0.0)
    rolls = math.ceil(strips * (1 + extra_pct / 100.0) / per_roll - 1e-9)
    used = strips * height * roll_width
    bought = rolls * roll_length * roll_width
    return RollEstimate(strips, length, per_roll, rolls, max(0.0, (1 - used / bought) * 100) if bought else 0.0)


def media_area(job: Job, panels: Optional[List[Panel]] = None) -> float:
    panels = panels if panels is not None else compute_panels(job)
    return sum(p.width * p.height for p in panels)


def job_summary(job: Job, design_px: Optional[Tuple[int, int]] = None) -> dict:
    panels = compute_panels(job)
    d = {
        "walls": len(job.walls), "run_width": job.run_width, "height": job.run_height,
        "art_width": job.art_width, "art_height": job.art_height,
        "wall_area": job.wall_area(), "openings_area": job.openings_area(),
        "net_area": job.wall_area() - job.openings_area(), "hidden_area": job.hidden_area(),
        "panels": len(panels), "panel_widths": [p.width for p in panels],
        "media_area": media_area(job, panels),
    }
    if design_px:
        rp = resolve_placement(job, design_px)
        d["ppi"] = rp.dpi
        d["covers"] = rp.covers(job.art_width, job.art_height)
    return d
