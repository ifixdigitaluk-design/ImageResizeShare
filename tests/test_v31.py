"""Expand design, text & logo layers, posts and backup (3.1)."""
from datetime import date
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.core import backup as bk
from app.core import expand as ex
from app.core import jobs
from app.core import layers as ly
from app.core import posts
from app.core import production as pr
from app.core import wall as wl


@pytest.fixture()
def home(tmp_path, monkeypatch):
    from app.core import paths
    monkeypatch.setenv("IRS_HOME", str(tmp_path / "home"))
    paths.set_base_dir(None)
    return tmp_path / "home"


def picture(w=600, h=800):
    img = Image.new("RGB", (w, h), (40, 110, 180))
    d = ImageDraw.Draw(img)
    for i in range(0, w, 30):
        d.line([(i, 0), (w - i, h)], fill=(240, 200, 60), width=4)
    return img


def test_expand_plan_wider_and_taller():
    p = ex.plan((600, 800), 2.0)
    assert p.top == p.bottom == 0 and p.left + p.right == 1000 and abs(p.left - p.right) <= 1
    assert p.out_size == (1600, 800)
    p = ex.plan((1600, 400), 2.0, where="top")
    assert p.top == 400 and p.bottom == 0 and p.out_size == (1600, 800)
    assert ex.plan((1000, 500), 2.0).empty
    assert ex.crop_fraction((600, 800), 2.0) == pytest.approx(1 - 0.75 / 2.0)


@pytest.mark.parametrize("method", ["mirror", "stretch", "blur"])
def test_expand_keeps_original(method):
    img = picture()
    p = ex.plan(img.size, 2.0)
    out = ex.expand_offline(img, p, method)
    assert out.size == p.out_size
    m = 20       # outside the feathered edge the original is untouched
    a = out.crop((p.left + m, m, p.left + img.width - m, img.height - m))
    assert a.tobytes() == img.crop((m, m, img.width - m, img.height - m)).tobytes()


def test_expand_ai_uses_mask(monkeypatch):
    from app.core import cloud
    seen = {}

    def fake(img, mask, token, prompt="", progress=None, **kw):
        seen["sizes"] = (img.size, mask.size)
        seen["corner"] = mask.getpixel((0, 0))
        seen["centre"] = mask.getpixel((mask.width // 2, mask.height // 2))
        return img
    monkeypatch.setattr(cloud, "outpaint", fake)
    img = picture()
    p = ex.plan(img.size, 2.0)
    out = ex.expand_ai(img, p, "token")
    assert out.size == p.out_size
    assert seen["sizes"][0] == seen["sizes"][1]
    assert seen["corner"] == 255 and seen["centre"] == 0


def test_text_layer_rect_and_render():
    j = wl.Job(job_no="T")
    j.walls[0].width, j.walls[0].height = 4.0, 2.5
    lay = ly.new_text_layer(j, "HELLO")
    lay.update(x=1.0, y=1.0, h=0.2)
    x0, y0, x1, y1 = ly.rect(j, lay)
    assert x0 == pytest.approx(j.panels.bleed_left + 1.0)
    assert y1 == pytest.approx(j.floor_y - 1.0) and y1 - y0 == pytest.approx(0.2)
    assert (x1 - x0) / 0.2 == pytest.approx(ly.aspect(lay), rel=1e-6) and x1 - x0 > 0.4
    img = ly.render_layer(lay, 400, 80)
    assert img.size == (400, 80) and img.getchannel("A").getextrema()[1] == 255


def test_layered_source_draws_on_print(tmp_path):
    j = wl.Job(job_no="T")
    j.walls[0].width, j.walls[0].height = 2.0, 2.0
    logo = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    (tmp_path / "layers").mkdir()
    logo.save(tmp_path / "layers" / "logo.png")
    lay = ly.new_image_layer(j, "layers/logo.png", logo.size)
    lay.update(x=0.5, y=0.5, h=0.5)
    j.layers = [lay]
    base = pr.ImageSource(Image.new("RGB", (400, 400), (255, 255, 255)), j)
    src = ly.LayeredSource(base, j, tmp_path)
    assert src.ppi == base.ppi and src.size_px == base.size_px      # passes through
    x0, y0, x1, y1 = ly.rect(j, lay, tmp_path)
    img = src.render(x0, y0, x1, y1, 50, 50)
    assert img.getpixel((25, 25)) == (255, 0, 0)
    img2 = src.render(0, 0, 0.3, 0.3, 30, 30)
    assert img2.getpixel((15, 15)) == (255, 255, 255)


def test_logo_white_background_removed(tmp_path):
    logo = Image.new("RGB", (100, 60), (255, 255, 255))
    ImageDraw.Draw(logo).rectangle([30, 20, 70, 40], fill=(0, 0, 200))
    logo.save(tmp_path / "logo.jpg")
    lay = {"kind": "image", "file": "logo.jpg", "h": 0.1, "x": 0, "y": 0, "key_white": True}
    out = ly.render_layer(lay, 100, 60, tmp_path)
    assert out.getpixel((5, 5))[3] == 0 and out.getpixel((50, 30))[3] > 200


def test_reminder_and_upcoming(home):
    j = wl.Job(job_no="JOB-1", customer="Sara Khan", phone="+44 7700 900000", status="Approved")
    j.install_date, j.install_time = "2031-03-04", "09:30"
    text = posts.reminder_text(j, {"name": "Wall Studio Ltd"})
    assert "Sara" in text and "Tuesday" in text and "09:30" in text and "Wall Studio Ltd" in text
    jobs.save_job(j)
    k = wl.Job(job_no="JOB-2", customer="Ali", status="Printed")
    jobs.save_job(k)
    dated, to_book = posts.upcoming(jobs.list_jobs(), today=date(2031, 3, 1))
    assert [s.job_no for _d, s in dated] == ["JOB-1"]
    assert [s.job_no for s in to_book] == ["JOB-2"]


@pytest.mark.parametrize("size", ["square", "story", "landscape"])
def test_post_sizes(size):
    img = posts.make_post(picture(), {"name": "Shop", "phone": "123"}, size, before=picture(300, 300), title="Hi")
    assert img.size == posts.SIZES[size]


def test_backup_restore_round_trip(home, tmp_path):
    j = wl.Job(job_no="JOB-9", customer="Backup")
    jobs.save_job(j)
    jobs.add_design(j, picture(), "design")
    jobs.save_job(j)
    (jobs.folder_for(j) / "print").mkdir()
    (jobs.folder_for(j) / "print" / "big.tif").write_bytes(b"x" * 1000)
    r = bk.backup(tmp_path / "bk")
    import zipfile
    names = zipfile.ZipFile(r.path).namelist()
    assert any(n.endswith("job.json") for n in names) and not any("/print/" in n for n in names)
    dest = tmp_path / "other"
    res = bk.restore(r.path, dest=dest)
    assert res.jobs_added == 1
    assert (dest / "Jobs").is_dir() and list((dest / "Jobs").glob("*/design/*"))
    res = bk.restore(r.path, dest=dest)
    assert res.jobs_added == 0 and res.jobs_kept == 1
    assert bk.last_backup(tmp_path / "bk") is not None
    assert bk.prune(tmp_path / "bk", keep=0) == 1
    with pytest.raises(ValueError):
        bad = tmp_path / "bad.zip"
        zipfile.ZipFile(bad, "w").writestr("x.txt", "x")
        bk.restore(bad, dest=dest)
    assert Path(r.path).name.startswith(bk.PREFIX)


def test_expand_to_a_long_wall_is_held_to_the_limit():
    pl = ex.plan((4000, 3000), 30 / 3)                       # a 30 m × 3 m wall
    big = ex.expand_offline(Image.new("RGB", (4000, 3000), (20, 90, 160)), pl, "mirror", max_px=20e6)
    assert big.width * big.height <= 20e6 * 1.01
    assert abs(big.width / big.height - 10) < 0.05           # still the wall's shape


@pytest.mark.parametrize("size,aspect", [((3000, 2), 1.0), ((2, 1500), 1000.0), ((1, 1), 0.001),
                                         ((1400, 9), 33.3), ((7, 2000), 0.01)])
def test_expand_extreme_shapes(size, aspect):
    img = Image.new("RGB", size, (10, 120, 200))
    pl = ex.plan(size, aspect, "even", 0.02)
    for m in ("mirror", "edge", "blur"):
        out = ex.expand_offline(img, pl, m, max_px=4_000_000)
        assert out.width * out.height <= 4_100_000


def test_layer_window_matches_the_whole_layer():
    import numpy as np
    lay = ly.new_text_layer(wl.Job(job_no="T"), "SALE 50%")
    whole = np.asarray(ly.render_layer(lay, 900, 200), dtype=np.int16)
    for win in ((0, 0, 300, 100), (450, 50, 900, 200), (120, 30, 610, 170)):
        part = np.asarray(ly.render_layer(lay, 900, 200, window=win), dtype=np.int16)
        ref = whole[win[1]:win[3], win[0]:win[2]]
        assert part.shape == ref.shape and np.abs(part - ref).mean() < 3


def test_huge_text_layer_renders_only_what_is_shown():
    import resource
    j = wl.Job(job_no="T")
    j.walls[0].width, j.walls[0].height = 4.0, 2.6
    lay = ly.new_text_layer(j, "HUGE")
    lay["h"] = 30.0                                          # 30 m tall text on a 2.6 m wall
    j.layers = [lay]

    class Plain:
        bg = (255, 255, 255)

        def render(self, x0, y0, x1, y1, w, h, fast=False):
            return Image.new("RGB", (w, h), (200, 200, 200))
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    out = ly.LayeredSource(Plain(), j, None).render(0, 0, j.art_width, j.art_height, 2400, 1600)
    assert out.size == (2400, 1600)
    assert (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024 < 600
