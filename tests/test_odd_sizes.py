"""Odd sizes a real user can type (a 1 cm door, a sofa taller than the wall, items off the wall)
must never break the room view, the proof or the installer sheet."""
import itertools

from PIL import Image

from app.core import documents as docs
from app.core import mockup as mk
from app.core import production as pr
from app.core import wall as wl

SIZES = (0.004, 0.03, 0.2, 1.1, 6.0)


def _job(items):
    j = wl.Job(job_no="JOB-T-0001", customer="Test")
    j.walls[0].width, j.walls[0].height = 3.0, 2.4
    j.walls[0].obstacles = items
    return j


def _items(kind):
    out = []
    for w, h in itertools.product(SIZES, SIZES):
        out.append(wl.Obstacle.make(kind, x=0.2, y=0.0, w=w, h=h))
    out.append(wl.Obstacle.make(kind, x=-0.5, y=-0.2, w=0.4, h=0.4))      # partly off the wall
    out.append(wl.Obstacle.make(kind, x=2.9, y=2.3, w=0.8, h=0.8))
    return out


def test_room_view_every_kind_every_size():
    design = Image.new("RGB", (300, 240), (200, 180, 160))
    for kind in wl.OBSTACLE_KINDS:
        for o in _items(kind):
            j = _job([o])
            img = mk.render_room(j.walls, design, "living", ppm=60)
            assert img.width > 10 and img.height > 10, kind


def test_sheets_with_odd_items():
    design = Image.new("RGB", (300, 240), (120, 140, 160))
    items = []
    for kind in wl.OBSTACLE_KINDS:
        items += _items(kind)[:6]
    j = _job(items)
    design = pr.ImageSource(design, j)
    page = Image.new("RGB", (1200, 900), "white")
    docs.draw_elevation(page, (20, 20, 1180, 880), j, design)
    panels = wl.compute_panels(j)
    pages = docs.installer_sheet(j, design, panels, [f"p{i}.tif" for i in range(len(panels))], {})
    assert pages
    assert docs.proof_sheet(j, design, {}).width > 100


def test_shaped_walls_with_items():
    design = Image.new("RGB", (300, 240), (200, 180, 160))
    for shape in wl.SHAPES:
        for ww, hh in ((0.3, 0.3), (3.0, 2.4), (12.0, 5.0)):
            j = _job([wl.Obstacle.make(k, x=0.1, w=0.5, h=0.5) for k in ("door", "window", "sofa", "bed")])
            wa = j.walls[0]
            wa.width, wa.height = ww, hh
            wa.shape = shape
            wa.shape_params = wl.default_shape_params(shape, ww, hh)
            assert mk.render_room(j.walls, design, "bedroom", ppm=40).width > 10
            src = pr.ImageSource(design, j)
            assert docs.proof_sheet(j, src, {}).width > 100
