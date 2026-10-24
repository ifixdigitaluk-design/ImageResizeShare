"""Tests for the Wall Studio engine: measuring, detection, production, documents, colour, jobs."""
import io
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import colour as col
from app.core import documents as docs
from app.core import measure as ms
from app.core import mockup as mk
from app.core import paths
from app.core import pattern as pt
from app.core import preflight as pf
from app.core import production as pr
from app.core import wall as wl


@pytest.fixture(autouse=True)
def home(tmp_path):
    paths.set_base_dir(tmp_path / "home")
    yield tmp_path / "home"
    paths.set_base_dir(None)


def photo(w=1200, h=800, seed=3):
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 1, w)[None, :, None]
    y = np.linspace(0, 1, h)[:, None, None]
    a = np.concatenate([x * 200 + 30 + 0 * y, y * 180 + 40 + 0 * x, (x + y) * 90 + 30], axis=2)
    a = a + rng.normal(0, 6, a.shape)
    img = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    d = ImageDraw.Draw(img)
    for i in range(0, w, 37):
        d.line([(i, 0), (i, h)], fill=(20, 20, 20), width=2)
    return img


def job(widths=(4.2,), h=2.7):
    j = wl.Job(job_no="JOB-2026-0001", customer="Test Customer", room="Lounge")
    j.walls = [wl.Wall(name=f"W{i}", width=w, height=h) for i, w in enumerate(widths)]
    return j


# ----------------------------------------------------------------------
# Measuring
# ----------------------------------------------------------------------
def room_photo(W=4.2, H=2.7, yaw=20, pitch=-5):
    w = wl.Wall(width=W, height=H)
    w.obstacles = [wl.Obstacle.make("door", x=0.35, w=0.90, h=2.10),
                   wl.Obstacle.make("window", x=1.95, y=1.05, w=1.40, h=1.15)]
    ppm = 160
    front = mk.render_room([w], None, "empty", ppm=ppm)
    side = max(0.8, W * 0.16)
    A = np.array([[ppm, 0, side * ppm], [0, ppm, 0.45 * ppm], [0, 0, 1.0]])
    Hc = ms.camera_homography(W, H, (1600, 1200), 1350, yaw, pitch, 4.6, (0.2, -0.15))
    import cv2
    img = Image.fromarray(cv2.warpPerspective(np.asarray(front), Hc @ np.linalg.inv(A), (1600, 1200),
                                              flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT))
    corners = ms.apply_h(Hc, [(0, 0), (W, 0), (W, H), (0, H)])
    return img, [tuple(p) for p in corners], Hc


@pytest.mark.parametrize("yaw,pitch", [(20, -5), (-30, 6), (3, -1)])
def test_aspect_from_perspective(yaw, pitch):
    Hc = ms.camera_homography(4.2, 2.7, (1600, 1200), 1350, yaw, pitch, 4.6)
    c = ms.apply_h(Hc, [(0, 0), (4.2, 0), (4.2, 2.7), (0, 2.7)])
    a, f, method = ms.estimate_aspect([tuple(p) for p in c], (1600, 1200))
    assert abs(a - 4.2 / 2.7) / (4.2 / 2.7) < 0.002


def test_order_corners_any_click_order():
    pts = [(100, 100), (900, 120), (880, 700), (120, 680)]
    for order in ([2, 0, 3, 1], [3, 2, 1, 0], [1, 3, 0, 2]):
        assert ms.order_corners([pts[i] for i in order]) == [tuple(map(float, p)) for p in pts]


def test_solve_with_tape_and_reference():
    img, corners, Hc = room_photo()
    r = ms.solve(ms.Survey(img.size, corners, width=4.2, height=2.7))
    assert r.accuracy_pct is not None and r.accuracy_pct < 0.5
    r2 = ms.solve(ms.Survey(img.size, corners, width=4.2))
    assert abs(r2.height - 2.7) < 0.02
    # an A4 sheet on the wall as the only reference
    a4 = [(1.0, 1.2), (1.21, 1.2), (1.21, 1.497), (1.0, 1.497)]
    q = ms.apply_h(Hc, a4)
    r3 = ms.solve(ms.Survey(img.size, corners, reference="A4 sheet (210 × 297 mm)",
                            reference_size=(0.21, 0.297), reference_quad=[tuple(p) for p in q]))
    assert abs(r3.width - 4.2) < 0.05 and abs(r3.height - 2.7) < 0.05 and r3.accuracy_pct < 2
    with pytest.raises(ValueError):
        ms.solve(ms.Survey(img.size, corners))


def test_rectify_and_detect_openings():
    img, corners, _ = room_photo()
    r = ms.solve(ms.Survey(img.size, corners, width=4.2, height=2.7))
    flat, ppm = ms.rectify(img, r, ppm=150)
    assert flat.size == (630, 405)
    items = ms.detect_openings(flat, ppm)
    kinds = {o.kind: o for o in items}
    assert "door" in kinds and "window" in kinds
    d, w = kinds["door"], kinds["window"]
    assert abs(d.x - 0.29) < 0.06 and abs(d.w - 1.02) < 0.08 and abs(d.h - 2.16) < 0.08
    assert abs(w.x + w.w / 2 - 2.65) < 0.08 and abs(w.y - 1.0) < 0.1


def test_photo_box_to_wall_and_back():
    img, corners, _ = room_photo()
    r = ms.solve(ms.Survey(img.size, corners, width=4.2, height=2.7))
    pts = ms.wall_to_photo(r, [(1.0, 0.5), (3.0, 2.0)])
    x, yf, w, h = ms.photo_box_to_wall(r, (min(pts[:, 0]), min(pts[:, 1]),
                                           abs(pts[1, 0] - pts[0, 0]), abs(pts[1, 1] - pts[0, 1])))
    assert x <= 1.0 + 1e-6 and x + w >= 3.0 - 1e-6 and yf <= 0.5 + 1e-6


def test_wall_dimensions_and_table():
    w = wl.Wall(width=4.2, height=2.7, obstacles=[wl.Obstacle.make("door", x=0.35, w=0.9, h=2.1),
                                                  wl.Obstacle.make("window", x=1.95, y=0.95, w=1.4, h=1.2),
                                                  wl.Obstacle.make("sofa", x=1.7, w=1.95, h=0.85)])
    dims = ms.wall_dimensions(w)
    texts = [d.text for d in dims]
    assert texts[0].startswith("4.20 m") and "13' 9\"" in texts[0]
    assert "0.35" in texts and "0.90" in texts and "0.70" in texts and "1.40" in texts and "0.85" in texts
    assert any(t.startswith("sill 0.95") for t in texts)
    rows = ms.items_table(w)
    assert rows[0][0] == "Door" and rows[-1][-1] == "in wall"


# ----------------------------------------------------------------------
# Detection
# ----------------------------------------------------------------------
def test_seam_risk_profile_prefers_plain_areas():
    from app.core import detect
    img = Image.new("RGB", (1000, 300), (200, 210, 220))
    d = ImageDraw.Draw(img)
    for x in range(400, 600, 6):
        d.line([(x, 0), (x + 30, 300)], fill=(10, 10, 10), width=2)
        d.line([(400, x - 350), (600, x - 340)], fill=(10, 10, 10), width=2)
    risk, faces = detect.seam_risk(img, 5.0, faces=[])
    assert len(risk) == 501
    assert risk[250] > 5 * risk[50] and risk[250] > 5 * risk[450]


def test_models_present_and_face_detector_runs():
    from app.core import detect
    assert detect.available() and detect.faces_available()
    assert detect.detect_faces(Image.new("RGB", (320, 240), (128, 128, 128))) == []


# ----------------------------------------------------------------------
# Sources / production
# ----------------------------------------------------------------------
def test_image_source_tiles_match_whole_render():
    j = job((3.0,), 2.5)
    src = pr.ImageSource(photo(), j)
    whole = np.asarray(src.render(0, 0, 3.1, 2.6, 620, 520)).astype(int)
    left = np.asarray(src.render(0, 0, 1.55, 2.6, 310, 520)).astype(int)
    right = np.asarray(src.render(1.55, 0, 3.1, 2.6, 310, 520)).astype(int)
    joined = np.concatenate([left, right], axis=1)
    assert np.abs(joined - whole).mean() < 2.0


def test_upscaled_panels_line_up():
    j = job((2.0,), 2.0)
    j.panels.media_width = 0.8
    src = pr.ImageSource(photo(300, 200), j)       # forces enlargement
    pre = pr.OutputPreset("t", "TIFF", dpi=60, slug=False)
    panels = wl.compute_panels(j)
    a = pr.render_panel(src, j, panels[0], panels, pre)
    b = pr.render_panel(src, j, panels[1], panels, pre)
    ppm = 60 / 0.0254
    ov = int(round(j.panels.overlap * ppm))
    ea = np.asarray(a)[:, -ov:].astype(int)
    eb = np.asarray(b)[:, :ov].astype(int)
    assert ea.shape == eb.shape and np.abs(ea - eb).mean() < 6


def test_panel_with_slug_marks_and_formats(tmp_path):
    j = job((1.5,), 2.4)
    src = pr.ImageSource(photo(), j)
    panels = wl.compute_panels(j)
    pre = pr.OutputPreset("t", "TIFF", dpi=40)
    img = pr.render_panel(src, j, panels[0], panels, pre)
    slug = int(round(pr.SLUG_MM * 40 / 25.4))
    assert img.height == int(round(panels[0].y1 * 40 / 0.0254)) - int(round(panels[0].y0 * 40 / 0.0254)) + 2 * slug
    top = np.asarray(img.crop((0, 0, img.width, slug)).convert("L"))
    assert top.min() < 80                       # text printed in the slug
    for fmt, colour in (("TIFF", "sRGB IEC61966-2.1"), ("TIFF", "CMYK – FOGRA39 coated (Europe)"),
                        ("PDF", "CMYK – FOGRA39 coated (Europe)"), ("JPG", "Adobe RGB (1998)"), ("PNG", "sRGB IEC61966-2.1")):
        p = tmp_path / f"x.{fmt.lower()}"
        pr.save_image(img, p, pr.OutputPreset("t", fmt, colour, dpi=40))
        assert p.stat().st_size > 1000
        if fmt != "PDF":
            r = Image.open(p)
            assert r.size == img.size
            assert r.mode == ("CMYK" if "CMYK" in colour else "RGB")
            assert round(r.info["dpi"][0]) == 40


def test_package(tmp_path):
    j = job((2.2,), 2.4)
    j.proof_version = 2
    src = pr.ImageSource(photo(), j)
    pre = pr.OutputPreset("t", "TIFF", dpi=30, hot_folder=str(tmp_path / "hot"))
    (tmp_path / "hot").mkdir()
    steps = []
    res = pr.make_package(j, tmp_path / "job", src, pre, preflight_text="ok", progress=lambda f, m: steps.append(f))
    panels = sorted((res.folder / "panels").iterdir())
    assert len(panels) == len(wl.compute_panels(j)) == 3
    assert (res.folder / "installation_sheet.pdf").stat().st_size > 10000
    t = json.loads((res.folder / "job_ticket.json").read_text())
    assert t["panels"][0]["file"] == panels[0].name and t["proof_version"] == 2
    assert res.zip_path.is_file() and res.hot_folder_copy and len(list(res.hot_folder_copy.iterdir())) == 4
    assert steps[-1] == 1.0


def test_pattern_source_is_continuous():
    tile = photo(200, 150)
    spec = pt.PatternSpec(repeat_w=0.5, repeat_type="half_drop", seamless=True)
    src = pt.PatternSource(tile, spec)
    whole = np.asarray(src.render(0, 0, 2.0, 1.0, 800, 400)).astype(int)
    a = np.asarray(src.render(0, 0, 1.0, 1.0, 400, 400)).astype(int)
    b = np.asarray(src.render(1.0, 0, 2.0, 1.0, 400, 400)).astype(int)
    assert np.abs(np.concatenate([a, b], axis=1) - whole).mean() < 3
    # half drop: column 1 is shifted by half a repeat
    assert src.repeat_file(50).size == (round(1.0 / 0.0254 * 50), round(src.rh / 0.0254 * 50))
    for r in pt.REPEATS:
        pt.PatternSource(tile, pt.PatternSpec(repeat_w=0.4, repeat_type=r)).render(0, 0, 1, 1, 100, 100)


def test_make_seamless_edges_match():
    from PIL import ImageFilter
    src = photo(300, 200).filter(ImageFilter.GaussianBlur(3))
    raw = np.asarray(src).astype(int)
    a = np.asarray(pt.make_seamless(src, 0.3)).astype(int)
    # opposite edges now continue into each other (they were very different before)
    assert np.abs(raw[:, 0] - raw[:, -1]).mean() > 40
    assert np.abs(a[:, 0] - a[:, -1]).mean() < 6 and np.abs(a[0] - a[-1]).mean() < 6


# ----------------------------------------------------------------------
# Mockups + documents
# ----------------------------------------------------------------------
def test_room_render_and_photo_mockup():
    j = job((4.2,), 2.7)
    j.walls[0].obstacles = [wl.Obstacle.make("door", x=0.35, w=0.9, h=2.1)]
    design = photo(840, 540)
    for scene in mk.SCENES:
        r = mk.render_room(j.walls, design, scene, ppm=60)
        assert r.size[0] > 4.2 * 60
    img, corners, Hc = room_photo()
    res = ms.solve(ms.Survey(img.size, corners, width=4.2, height=2.7))
    out = mk.photo_mockup(img, res.H, 4.2, 2.7, design, j.walls[0].obstacles)
    a, b = np.asarray(out).astype(int), np.asarray(img).astype(int)
    cx, cy = [int(v) for v in ms.wall_to_photo(res, [(3.0, 2.3)])[0]]
    assert np.abs(a[cy, cx] - b[cy, cx]).sum() > 30          # wall now shows the design
    dx, dy = [int(v) for v in ms.wall_to_photo(res, [(0.8, 1.0)])[0]]
    assert np.abs(a[dy, dx] - b[dy, dx]).sum() < 20          # the door stays the door
    sw = mk.material_swatch(design, "Canvas", "Satin", 150, 300)
    assert sw.size == (300, 300)


def test_documents_render():
    j = job((3.0, 1.0), 2.6)
    j.walls[0].corner_after = "outside"
    j.walls[0].obstacles = [wl.Obstacle.make("window", x=1.0), wl.Obstacle.make("sofa", x=0.5)]
    src = pr.ImageSource(photo(), j)
    panels = wl.compute_panels(j)
    pages = docs.installer_sheet(j, src, panels, ["a.tif"] * len(panels), {"name": "Shop"})
    assert len(pages) == 2 and pages[0].size == docs.A3
    assert docs.proof_sheet(j, src, {"name": "Shop"}, mockup=photo(400, 300), ppi=src.ppi).size == docs.A3
    assert docs.options_sheet(j, [("A", photo(300, 200)), ("B", photo(300, 200, 4))], {}).size == docs.A3
    assert docs.survey_sheet(j, 0, photo(600, 400), photo(800, 600), [(10, 10), (790, 20), (780, 590), (20, 580)],
                             {}, "Photo vs tape: 0.4%").size == docs.A3
    ts = docs.test_strip(src, j, (1.5, 1.3), (0.3, 0.2), 50)
    assert ts.width == round(0.3 / 0.0254 * 50)


# ----------------------------------------------------------------------
# Colour
# ----------------------------------------------------------------------
def test_delta_e2000_reference_values():
    pairs = [((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
             ((50, 3.1571, -77.2803), (50, 0, -82.7485), 2.8615),
             ((50, 2.5, 0), (50, 0, -2.5), 4.3065),
             ((2.0776, 0.0795, -1.135), (0.9033, -0.0636, -0.5514), 0.9082)]
    for a, b, e in pairs:
        assert abs(float(col.delta_e2000(np.array(a), np.array(b))) - e) < 1e-3


def test_lab_roundtrip_and_matching():
    rgb = np.array([[12, 200, 90], [240, 240, 240], [70, 20, 160]], float)
    assert np.abs(col.lab_to_srgb(col.srgb_to_lab(rgb)) - rgb).max() < 0.6
    m = col.match_colour((250, 128, 114), col.CSS_COLOURS, 2)
    assert m[0][0] == "Salmon" and m[0][2] < 0.5


def test_profiles_softproof_gamut_and_cmyk():
    names = [p.name for p in col.list_profiles()]
    assert "CMYK – FOGRA39 coated (Europe)" in names and "sRGB IEC61966-2.1" in names
    fogra = col.find_profile("CMYK – FOGRA39 coated (Europe)")
    img = Image.new("RGB", (60, 20))
    img.paste((0, 255, 0), (0, 0, 20, 20))       # vivid green: out of gamut
    img.paste((128, 128, 128), (20, 0, 60, 20))  # grey: printable
    mask, frac = col.gamut_map(img, fogra)
    assert 0.25 < frac < 0.45
    assert col.to_cmyk(img, fogra).mode == "CMYK"
    sp = col.soft_proof(img, fogra)
    assert sp.getpixel((5, 5))[1] < 230          # the green gets duller on paper


def test_palette_import_replace_and_colourways(tmp_path):
    p = tmp_path / "paints.csv"
    p.write_text("Name,Hex\nMy Sage,#9CAF88\nMy Navy,#1F3A60\nbad line\nRGB one,10,20,30\n")
    name, n = col.import_palette(p)
    assert n == 3 and name in col.list_palettes()
    img = Image.new("RGB", (40, 10), (200, 30, 30))
    img.paste((30, 30, 200), (20, 0, 40, 10))
    out = col.replace_colour(img, (200, 30, 30), (30, 160, 60), tolerance=20)
    assert out.getpixel((2, 2))[1] > 120 and out.getpixel((30, 5))[2] > 180
    for cw in col.COLOURWAYS:
        assert col.colourway(img, cw).size == img.size
    pal = col.extract_palette(img, 4)
    assert abs(sum(f for _c, f in pal) - 1) < 1e-6


# ----------------------------------------------------------------------
# Jobs, library, preflight, cloud
# ----------------------------------------------------------------------
def test_jobs_lifecycle(tmp_path):
    from app.core import jobs
    j = jobs.new_job("Sarah Khan", "077", "Lounge")
    assert j.job_no.endswith("-0001")
    j.walls[0].width = 4.2
    rel = jobs.add_design(j, photo(), "upscaled")
    jobs.save_job(j)
    jobs.save_thumb(j, photo())
    k = jobs.load_job(jobs.folder_for(j))
    assert k.walls[0].width == 4.2 and (jobs.folder_for(j) / rel).is_file()
    lst = jobs.list_jobs()
    assert lst[0].job_no == j.job_no and lst[0].thumb is not None
    dup = jobs.duplicate_job(k)
    assert dup.job_no.endswith("-0002") and (jobs.folder_for(dup) / rel).is_file()
    moved = jobs.delete_job(jobs.folder_for(dup))
    assert moved.is_dir() and len(jobs.list_jobs()) == 1
    jobs.save_business({"name": "Shop", "phone": "1"})
    assert jobs.load_business()["name"] == "Shop"


def test_library(tmp_path):
    from app.core import jobs
    f = tmp_path / "forest_mural.jpg"
    photo().save(f)
    it = jobs.library_add(f, tags=["Nature", "green"])
    assert it.name == "Forest Mural" and jobs.library_thumb(it).is_file()
    assert jobs.library_search("forest") and jobs.library_search(tag="nature") and not jobs.library_search("city")
    it.tags.append("kids")
    jobs.library_update(it)
    assert "kids" in jobs.library_tags()
    jobs.library_remove(it)
    assert jobs.load_library() == []


def test_preflight_levels():
    j = job((4.2,), 2.7)
    src = pr.ImageSource(photo(400, 260), j)
    checks = pf.run(j, src, pr.BUILTIN_PRESETS[0], risk=None, gamut_fraction=0.2)
    keys = {c.key: c for c in checks}
    assert keys["ppi"].level == "warn" and keys["ppi"].fix == "upscale"
    assert keys["approval"].level == "warn" and keys["gamut"].level == "warn"
    assert checks[0].level in ("error", "warn")
    j.set_status("Approved")
    risk = np.zeros(int(j.art_width / 0.01) + 1)
    for s in wl.current_seams(j):
        risk[int(s / 0.01)] = 5.0
    keys = {c.key: c for c in pf.run(j, src, pr.BUILTIN_PRESETS[0], risk=risk)}
    assert keys["seams"].level == "error" and keys["approval"].level == "ok"
    assert pf.counts(pf.run(j, None))[0] >= 1
    assert "PREFLIGHT" in pf.report_text(checks, j)


def test_cloud_flow_with_fake_server():
    from app.core import cloud
    out_png = io.BytesIO()
    Image.new("RGB", (80, 60), (1, 2, 3)).save(out_png, "PNG")
    calls = []

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=0):
        url = req.full_url
        calls.append((req.get_method(), url))
        if url.endswith("/models/nightmareai/real-esrgan"):
            return R(json.dumps({"latest_version": {"id": "v123"}}).encode())
        if url.endswith("/files"):
            assert b"Content-Disposition" in req.data
            return R(json.dumps({"urls": {"get": "https://api.replicate.com/v1/files/f1"}}).encode())
        if url.endswith("/predictions"):
            body = json.loads(req.data)
            assert body["version"] == "v123" and body["input"]["scale"] == 4
            return R(json.dumps({"status": "processing", "urls": {"get": "https://api.replicate.com/v1/predictions/p1"}}).encode())
        if url.endswith("/predictions/p1"):
            return R(json.dumps({"status": "succeeded", "output": "https://replicate.delivery/out.png"}).encode())
        if url.endswith("out.png"):
            return R(out_png.getvalue())
        raise AssertionError(url)

    img = cloud.upscale(Image.new("RGB", (20, 15)), "tok", "Real-ESRGAN (faithful, fast)", 4, opener=opener, poll=0)
    assert img.size == (80, 60) and len(calls) == 5
    with pytest.raises(cloud.CloudError):
        cloud.upscale(Image.new("RGB", (20, 15)), "", "Real-ESRGAN (faithful, fast)")


class _FakeAI:
    """Stands in for the offline AI engine: records calls, enlarges with Lanczos."""
    def __init__(self):
        self.calls = []

    def available(self):
        return True

    def upscale_to(self, img, size, art=False, progress=None, cancel=None):
        self.calls.append((img.size, size, art))
        return img.resize(size, Image.Resampling.LANCZOS)


def test_ai_enhanced_print_package(tmp_path):
    j = job((2.2,), 2.4)
    small = photo(160, 120)                                   # a small design on a big wall: enlarged a lot
    src = pr.ImageSource(small, j)
    ai = _FakeAI()
    ai_src = pr.with_ai(src, ai, art=True)
    assert src.ai_engine is None and pr.uses_ai(ai_src) and not pr.uses_ai(src)   # studio's copy untouched
    pre = pr.OutputPreset("t", "TIFF", dpi=30)
    plain = pr.make_package(j, tmp_path / "a", src, pre)
    res = pr.make_package(j, tmp_path / "b", ai_src, pre)
    panels = wl.compute_panels(j)
    assert len(ai.calls) >= len(panels) and all(c[2] for c in ai.calls)     # AI used, art model
    for a, b in zip(sorted((plain.folder / "panels").iterdir()), sorted((res.folder / "panels").iterdir())):
        assert Image.open(a).size == Image.open(b).size
    # neighbouring panels overlap: the shared strip must match (no visible join)
    ppm = 30 / 0.0254
    imgs = [np.asarray(Image.open(p).convert("RGB")).astype(int) for p in sorted((res.folder / "panels").iterdir())]
    slug = (imgs[0].shape[0] - round((panels[0].y1 - panels[0].y0) * ppm)) // 2
    for k in range(len(panels) - 1):
        p, q = panels[k], panels[k + 1]
        ov = p.x1 - q.x0
        n = int(ov * ppm) - 2
        if n < 2:
            continue
        right = imgs[k][slug + 20:-slug - 20, -n - 1:-1]
        left = imgs[k + 1][slug + 20:-slug - 20, 1:n + 1]
        h = min(right.shape[0], left.shape[0])
        assert np.abs(right[:h] - left[:h]).mean() < 6


def test_with_ai_leaves_patterns_and_missing_engines_alone():
    j = job((2.2,), 2.4)
    src = pr.ImageSource(photo(), j)
    assert pr.with_ai(src, None) is src

    class Off(_FakeAI):
        def available(self):
            return False
    assert pr.with_ai(src, Off()) is src
    tile_src = pt.PatternSource(photo(200, 150), pt.PatternSpec(repeat_w=0.5))
    assert pr.with_ai(tile_src, _FakeAI()) is tile_src


def test_panels_too_big_for_one_file_are_refused_clearly(tmp_path):
    from app.core import preflight as pf
    j = job((3.0,), 30.0)                                   # the tallest wall the app allows
    big = pr.OutputPreset("big", "TIFF", dpi=300)
    msg = pr.panel_too_big_text(j, big)
    assert msg and "too big" in msg
    with pytest.raises(ValueError):
        pr.make_package(j, tmp_path / "job", pr.ImageSource(photo(), j), big)
    assert any(c.key == "panel_px" and c.level == "error" for c in pf.run(j, pr.ImageSource(photo(), j), big))
    ok = pr.OutputPreset("ok", "TIFF", dpi=100, scale=0.25)
    assert pr.panel_too_big_text(j, ok) is None
