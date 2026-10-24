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


def test_room_for_a_tall_narrow_wall_stays_a_sensible_size():
    from app.core import mockup as mk
    from app.core import wall as wl
    w = wl.Wall(width=0.1, height=30.0)
    img = mk.render_room([w], None, "living", ppm=4000 / (0.1 + 1.6))
    assert img.width * img.height <= mk.MAX_ROOM_PX * 1.01


def test_tiny_design_on_a_big_wall_renders_without_a_huge_picture():
    import resource
    from PIL import Image
    from app.core import production as pr
    from app.core import wall as wl
    j = wl.Job(job_no="T")
    j.walls[0].width, j.walls[0].height = 20.0, 3.0
    src = pr.ImageSource(Image.new("RGB", (2, 2), (200, 30, 30)), j)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    cx, cy = j.art_width / 2, j.art_height / 2
    sw = src.render(cx - 0.075, cy - 0.075, cx + 0.075, cy + 0.075, 600, 600)     # the Room View swatch
    assert sw.size == (600, 600)
    grown_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
    assert grown_mb < 300


def test_proof_of_an_extreme_shape_stays_a_sensible_page():
    from PIL import Image
    from app.core import proof
    from app.core import sheets as sh
    img = Image.new("RGB", (640, 480), (30, 90, 160))
    for w_in, h_in, fill in ((1.0, 500.0, False), (500.0, 1.0, False), (1.0, 500.0, True), (500.0, 1.0, True)):
        ps = proof.ProofSettings(width_in=w_in, height_in=h_in, fill=fill, watermark="PROOF")
        page = proof.render_proof(img, ps)
        assert page.width == ps.width_px and page.height < ps.width_px * 6
        shaped = sh.shape_to_print(img, w_in, h_in, fill)
        assert shaped.width * shaped.height <= 61e6 and min(shaped.size) >= 1


def test_colour_changes_in_strips_match():
    import numpy as np
    from PIL import Image
    from app.core import colour as col
    img = Image.fromarray(np.random.default_rng(2).integers(0, 255, (2100, 2000, 3), dtype=np.uint8))
    small_steps = col.adjust.__wrapped__(img, hue=20, saturation=1.2)           # all at once
    assert np.array_equal(np.asarray(col.adjust(img, hue=20, saturation=1.2)), np.asarray(small_steps))
