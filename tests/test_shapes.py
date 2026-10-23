"""Shaped walls, panel trimming and the measure-from-photo helpers added in 3.1."""
import math

import numpy as np
import pytest

from app.core import measure as ms
from app.core import wall as wl


def shaped_job(shape, W=4.0, H=3.0, **params):
    j = wl.Job(job_no="T")
    w = j.walls[0]
    w.width, w.height = W, H
    w.shape = shape
    w.shape_params = {**wl.default_shape_params(shape, W, H), **params}
    w.height = wl.shape_height(shape, w.shape_params, H)
    return j


def test_rect_unchanged():
    j = wl.Job(job_no="T")
    j.walls[0].width, j.walls[0].height = 4.0, 2.5
    assert j.walls[0].area() == pytest.approx(10.0)
    assert not j.uneven
    assert all(p.y0 == 0 and p.y1 == pytest.approx(j.art_height) for p in wl.compute_panels(j))


def test_gable_area_and_panels():
    j = shaped_job("gable", 4.0, 3.0, side_h=2.0, peak_x=2.0)
    w = j.walls[0]
    assert w.area() == pytest.approx(4.0 * 2.0 + 0.5 * 4.0 * 1.0)
    panels = wl.compute_panels(j)
    # the middle panel reaches the peak, the outer ones stop lower (plus bleed)
    mid = min(panels, key=lambda p: abs((p.x0 + p.x1) / 2 - j.art_width / 2))
    outer = panels[0]
    assert mid.y0 < outer.y0
    assert outer.y1 == pytest.approx(j.art_height)
    assert wl.media_area(j, panels) < sum(p.width for p in panels) * j.art_height


def test_slope_span_and_height():
    j = shaped_job("slope", 4.0, 3.0, left_h=3.0, right_h=1.2, break_x=1.0)
    w = j.walls[0]
    assert w.height == pytest.approx(3.0)
    assert w.span(0.5, 0.5) == pytest.approx((0.0, 3.0))
    lo, hi = w.span(4.0, 4.0)
    assert hi == pytest.approx(1.2)
    # halfway down the slope
    assert w.span(2.5, 2.5)[1] == pytest.approx(3.0 - 1.8 * 0.5)
    w.shape_params["mirror"] = True
    assert w.span(0.0, 0.0)[1] == pytest.approx(1.2)


def test_stairs_area_and_bottoms():
    j = shaped_job("stairs", 4.0, 4.5, start_x=0.0, end_x=4.0, rise=2.0, top_left=4.5, top_right=4.5)
    w = j.walls[0]
    assert w.area() == pytest.approx(4.0 * 4.5 - 0.5 * 4.0 * 2.0)
    panels = sorted(wl.compute_panels(j), key=lambda p: p.x0)
    # panels get shorter as the stairs rise (bottom edge moves up = smaller y1 in artwork coords)
    assert panels[0].y1 > panels[-1].y1
    assert all(p.y0 == pytest.approx(0.0) for p in panels)


def test_arch_area():
    j = shaped_job("arch", 4.0, 3.0, side_h=2.0)
    a = j.walls[0].area()
    assert a == pytest.approx(4.0 * 2.0 + math.pi * 2.0 * 1.0 / 2, rel=0.01)


def test_lower_wall_panels_trimmed():
    j = wl.Job(job_no="T")
    j.walls = [wl.Wall("A", 3.0, 2.6), wl.Wall("B", 2.0, 1.2)]
    panels = sorted(wl.compute_panels(j), key=lambda p: p.x0)
    assert panels[-1].y0 > panels[0].y0 + 1.0


def test_openings_clipped_to_shape():
    j = shaped_job("slope", 4.0, 3.0, left_h=3.0, right_h=1.0, break_x=0.0)
    w = j.walls[0]
    o = wl.Obstacle.make("window", x=3.0, y=0.5, w=1.0, h=2.0)
    w.obstacles = [o]
    # the window rectangle sticks out above the slope: only the part under it counts
    assert w.openings_area() < 2.0
    assert w.openings_area() > 0.4


def test_lens_points_round_trip():
    pts = np.array([[100, 100], [800, 600], [1500, 1100]], float)
    u = ms.lens_undistort_points(pts, (1600, 1200), -0.2)
    back = ms.lens_distort_points(u, (1600, 1200), -0.2)
    assert np.abs(back - pts).max() < 1e-6
    assert np.abs(ms.lens_undistort_points(pts, (1600, 1200), 0.0) - pts).max() == 0


def _room_photo(W=4.2, H=2.7, yaw=20, pitch=-5, dist=4.6, off=(0.2, -0.15)):
    cv2 = pytest.importorskip("cv2")
    from PIL import Image
    from app.core import mockup as mk
    w = wl.Wall(width=W, height=H, obstacles=[wl.Obstacle.make("door", x=0.35, w=0.9, h=2.1),
                                              wl.Obstacle.make("window", x=W * 0.47, y=1.05, w=1.4, h=1.15)])
    ppm = 200
    front = mk.render_room([w], None, "living", ppm=ppm)
    side = max(0.8, W * 0.16)
    A = np.array([[ppm, 0, side * ppm], [0, ppm, 0.45 * ppm], [0, 0, 1.0]])
    Hc = ms.camera_homography(W, H, (1600, 1200), 1350, yaw, pitch, dist, off)
    photo = Image.fromarray(cv2.warpPerspective(np.asarray(front), Hc @ np.linalg.inv(A), (1600, 1200),
                                                flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT))
    return photo, ms.apply_h(Hc, [(0, 0), (W, 0), (W, H), (0, H)])


@pytest.mark.parametrize("case", [(4.2, 2.7, 20, -5, 4.6, (0.2, -0.15)), (3.0, 2.5, 5, -2, 3.8, (0, 0)),
                                  (3.6, 2.4, -10, 8, 4.2, (0.1, 0.2))])
def test_find_wall_corners(case):
    photo, true = _room_photo(*case)
    r = ms.find_wall_corners(photo)
    assert r is not None
    err = np.linalg.norm(np.array(r[0]) - true, axis=1).max()
    assert err < 25          # px on a 1600 px photo; the user fine-tunes with the magnifier


def test_estimate_lens():
    cv2 = pytest.importorskip("cv2")
    from PIL import Image
    photo, _true = _room_photo()
    W, H = photo.size
    k1 = -0.18
    K, D, _n = ms._lens_K((W, H), k1, keep_all=False)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float64)
    und = ms.lens_undistort_points(np.stack([xs.ravel(), ys.ravel()], -1), (W, H), 0.0)  # identity grid
    # make a barrel-distorted photo: each distorted pixel looks up its straight position
    d = (und - [K[0, 2], K[1, 2]]) / [K[0, 0], K[1, 1]]
    rd = np.hypot(d[:, 0], d[:, 1])
    r = rd.copy()
    for _ in range(30):
        r = r - (r * (1 + k1 * r * r) - rd) / (1 + 3 * k1 * r * r)
    n = d * (r / np.maximum(rd, 1e-12))[:, None]
    src = (n * [K[0, 0], K[1, 1]] + [K[0, 2], K[1, 2]]).astype(np.float32).reshape(H, W, 2)
    bent = Image.fromarray(cv2.remap(np.asarray(photo), src[..., 0], src[..., 1], cv2.INTER_LINEAR,
                                     borderMode=cv2.BORDER_REFLECT))
    est, gain = ms.estimate_lens(bent)
    assert abs(est - k1) <= 0.04 and gain > 1.05
    est0, _g = ms.estimate_lens(photo)
    assert abs(est0) <= 0.03
