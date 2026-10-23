import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import units as u
from app.core import wall as wl


def make_job(widths=(4.2,), height=2.7, media=1.0, overlap=0.025, bleed=0.05, corners=None):
    walls = [wl.Wall(name=f"Wall {i + 1}", width=w, height=height) for i, w in enumerate(widths)]
    for i, c in enumerate(corners or []):
        walls[i].corner_after = c
    j = wl.Job(job_no="T-1", walls=walls)
    j.panels = wl.PanelSpec(media_width=media, overlap=overlap, bleed_top=bleed, bleed_bottom=bleed,
                            bleed_left=bleed, bleed_right=bleed)
    return j


def test_units_format_and_parse():
    assert u.fmt(4.2, "m") == "4.20 m"
    assert u.fmt(4.2, "cm") == "420.0 cm"
    assert u.ft_in(4.2) == "13' 9\""
    assert u.ft_in(0.0254 * 7.5, frac=2) == '7 1/2"'
    assert abs(u.parse_length("13' 9\"") - (13 * 0.3048 + 9 * 0.0254)) < 1e-9
    assert abs(u.parse_length("420cm") - 4.2) < 1e-9
    assert abs(u.parse_length("165 in") - 4.191) < 1e-9
    assert abs(u.parse_length("4.2") - 4.2) < 1e-9
    assert abs(u.parse_length("12", "ftin") - 12 * 0.3048) < 1e-9
    assert u.fmt_area(10, "sqft") == "107.6 sq ft"
    with pytest.raises(ValueError):
        u.parse_length("abc")


def test_artwork_geometry_and_areas():
    j = make_job((3.0, 1.5), height=2.5)
    j.walls[1].height = 2.4
    j.walls[0].obstacles.append(wl.Obstacle.make("door", x=0.3))
    j.walls[1].obstacles.append(wl.Obstacle.make("sofa", x=0.2))
    assert abs(j.art_width - 4.6) < 1e-9 and abs(j.art_height - 2.6) < 1e-9
    assert j.wall_rect(1) == pytest.approx((3.05, 2.55 - 2.4, 4.55, 2.55))
    x0, y0, x1, y1 = j.obstacle_rect(0, j.walls[0].obstacles[0])
    assert (x0, y1) == pytest.approx((0.35, 2.55)) and y1 - y0 == pytest.approx(2.04)
    assert j.openings_area() == pytest.approx(0.84 * 2.04)
    assert j.hidden_area() == pytest.approx(2.0 * 0.85) or j.hidden_area() == pytest.approx(1.3 * 0.85)
    assert j.corners() == [(pytest.approx(3.05), "inside")]


def test_equal_panels_cover_and_fit_media():
    j = make_job((4.2,))
    panels = wl.compute_panels(j)
    assert len(panels) == 5
    assert panels[0].x0 == 0 and panels[-1].x1 == pytest.approx(j.art_width)
    widths = [p.width for p in panels]
    assert max(widths) <= 1.0 + 1e-9 and max(widths) - min(widths) < 1e-9
    # neighbours overlap by exactly the overlap
    for a, b in zip(panels, panels[1:]):
        assert a.x1 - b.x0 == pytest.approx(0.025)
        assert a.seam_right == b.seam_left
    assert not [i for i in wl.panel_issues(j) if i.level == "error"]


def test_full_panels_and_sliver_rebalance():
    j = make_job((2.0,), media=1.0, overlap=0.02, bleed=0.0)
    j.panels.mode = "full"
    p = wl.compute_panels(j)
    # 1.0 + 1.0 would leave a 4 cm sliver, so the last two panels are shared
    assert [round(x.width, 3) for x in p] == [1.0, 0.52, 0.52]
    j2 = make_job((1.99,), media=1.0, overlap=0.0, bleed=0.0)
    j2.panels.mode = "full"
    assert [round(x.width, 3) for x in wl.compute_panels(j2)] == [1.0, 0.99]


def test_single_panel_and_right_to_left():
    j = make_job((0.8,))
    assert len(wl.compute_panels(j)) == 1
    j = make_job((4.2,))
    j.panels.right_to_left = True
    p = wl.compute_panels(j)
    assert p[0].index == 1 and p[0].x1 == pytest.approx(j.art_width)


def test_move_seam_respects_media_width():
    j = make_job((4.2,))
    seams = wl.current_seams(j)
    pos = wl.move_seam(j, 0, seams[0] + 0.5)      # would make panel 2 too narrow / panel 1 too wide
    p = wl.compute_panels(j)
    assert j.panels.mode == "manual" and pos <= 1.0 - 0.0125 + 1e-9
    assert all(x.width <= 1.0 + 1e-9 for x in p)


def test_outside_corner_warning_and_optimiser_avoids_risk():
    j = make_job((1.5, 2.0), media=1.0, corners=["outside"])
    corner_x = j.corners()[0][0]
    wl.set_manual_seams(j, [corner_x + 0.05] + wl.current_seams(j)[1:])
    assert any("outside corner" in i.text for i in wl.panel_issues(j))
    # optimiser: big risk in the middle third, must not put seams there; avoid the corner
    aw = j.art_width
    risk = np.zeros(int(aw / 0.01) + 1)
    risk[int(1.9 / 0.01):int(2.2 / 0.01)] = 10
    seams = wl.optimise_seams(j, risk)
    assert all(not (1.9 <= s <= 2.2) for s in seams)
    assert all(abs(s - corner_x) >= wl.OUTSIDE_CORNER_CLEARANCE - 1e-9 for s in seams)
    wl.set_manual_seams(j, seams)
    assert not [i for i in wl.panel_issues(j) if i.level == "error"]


def test_placement_fill_and_zoom():
    j = make_job((4.2,), height=2.7)
    rp = wl.resolve_placement(j, (6000, 3000))
    assert rp.covers(j.art_width, j.art_height)
    assert rp.dpi == pytest.approx(3000 / j.art_height * 0.0254)
    wl.zoom_placement(j, (6000, 3000), 1.2, j.art_width / 2, j.art_height / 2)
    rp2 = wl.resolve_placement(j, (6000, 3000))
    assert rp2.design_w_m == pytest.approx(rp.design_w_m * 1.2)
    assert rp2.covers(j.art_width, j.art_height)


def test_job_roundtrip_and_status_history():
    j = make_job((3.0, 2.0))
    j.walls[0].obstacles.append(wl.Obstacle.make("window", x=1.0))
    j.set_status("Measured")
    d = j.to_dict()
    k = wl.Job.from_dict(d)
    assert k.walls[0].obstacles[0].kind == "window" and isinstance(k.placement, wl.Placement)
    assert k.status == "Measured" and k.history[-1]["event"] == "Status → Measured"
    assert k.to_dict() == d


def test_ppi_quality_and_rolls():
    assert wl.required_ppi(1.0) == pytest.approx(87.3, abs=0.2)
    assert wl.ppi_quality(150, 1.5)[0] == "excellent"
    assert wl.ppi_quality(70, 1.5)[0] == "good"
    assert wl.ppi_quality(30, 1.5)[0] == "low"
    r = wl.rolls_needed(4.2, 2.6, 0.53, 10.05)
    assert r.strips == 8 and r.strips_per_roll == 3 and r.rolls == 3
    r2 = wl.rolls_needed(4.2, 2.6, 0.53, 10.05, repeat=0.64, drop="half")
    assert r2.strip_length == pytest.approx(3.52) and r2.strips_per_roll == 2 and r2.rolls == 5
