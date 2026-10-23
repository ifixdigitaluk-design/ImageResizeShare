import io, sys
from pathlib import Path
import numpy as np
import pytest
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import imaging as im


def make_photo(w=400, h=300, alpha=False):
    rng = np.random.default_rng(1)
    x = np.linspace(0, 1, w)[None, :, None]; y = np.linspace(0, 1, h)[:, None, None]
    arr = np.concatenate([x * 255 * np.ones((h, 1, 1)), y * 255 * np.ones((1, w, 1)),
                          ((x + y) / 2) * 255], axis=2)
    arr += rng.normal(0, 4, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB")
    d = ImageDraw.Draw(img)
    for i in range(0, w, 20):
        d.line([(i, 0), (i, h)], fill=(0, 0, 0), width=1)
    d.text((10, 10), "Sharp text 123", fill=(255, 255, 255))
    if alpha:
        img = img.convert("RGBA"); a = Image.new("L", img.size, 0)
        ImageDraw.Draw(a).ellipse([20, 20, w - 20, h - 20], fill=255); img.putalpha(a)
    return img


def loaded(img):
    return im.from_pil(img)


def edge_energy(img):
    g = np.asarray(img.convert("L"), dtype=float)
    return np.abs(np.diff(g, axis=1)).mean() + np.abs(np.diff(g, axis=0)).mean()


@pytest.mark.parametrize("mode,exp", [
    (im.MODE_FIT_PAD, (1080, 1080)), (im.MODE_FILL, (1080, 1080)),
    (im.MODE_STRETCH, (1080, 1080)), (im.MODE_FIT_INSIDE, (1080, 810))])
def test_modes_sizes(mode, exp):
    rs = im.ResizeSettings(width=1080, height=1080, mode=mode)
    out = im.resize_image(make_photo(), rs)
    assert out.size == exp


def test_fit_pad_keeps_whole_image():
    src = Image.new("RGB", (400, 200), (255, 0, 0))
    out = im.resize_image(src, im.ResizeSettings(width=400, height=400, mode=im.MODE_FIT_PAD,
                                                 background=im.BG_BLACK))
    a = np.asarray(out)
    assert a[0, 200].tolist() == [0, 0, 0]          # padding top
    assert a[200, 200, 0] > 240                      # image in the middle, red


def test_enhanced_sharper_than_standard_on_upscale():
    small = make_photo(200, 150)
    std = im.resample(small, (800, 600), im.UPSCALE_STANDARD)
    enh = im.resample(small, (800, 600), im.UPSCALE_ENHANCED)
    assert enh.size == std.size == (800, 600)
    assert edge_energy(enh) > edge_energy(std) * 1.05


def test_upscale_fidelity_close_to_original():
    """Downscale an original then enlarge back: result must stay close."""
    orig = make_photo(800, 600)
    small = orig.resize((400, 300), Image.Resampling.LANCZOS)
    std = im.resample(small, (800, 600), im.UPSCALE_STANDARD)
    back = im.resample(small, (800, 600), im.UPSCALE_ENHANCED)
    mae = lambda a: np.abs(np.asarray(a, float) - np.asarray(orig, float)).mean()
    assert mae(back) < mae(std) * 1.15, (mae(back), mae(std))
    # sharpness (edge energy) is restored closer to the original
    assert abs(edge_energy(back) - edge_energy(orig)) < abs(edge_energy(std) - edge_energy(orig))


def test_ai_fallback_note():
    class Broken:
        def available(self): return True
        def upscale_to(self, *a, **k): raise RuntimeError("invalid gpu device")
    notes = []
    out = im.resample(make_photo(100, 100), (300, 300), im.UPSCALE_AI_PHOTO, ai_engine=Broken(), notes=notes)
    assert out.size == (300, 300) and notes and "Enhanced" in notes[0]


def test_rotation_and_crop():
    src = make_photo(400, 300)
    st = im.EditState(rotation=90, crop=(10, 20, 100, 50))
    assert im.oriented_size(src.size, st) == (300, 400)
    out = im.apply_edits(src, st)
    assert out.size == (100, 50)
    assert im.edited_size(src.size, st) == (100, 50)


def test_crop_clamp():
    assert im.clamp_crop((-5, -5, 1000, 1000), (100, 100)) is None
    assert im.clamp_crop((90, 90, 50, 50), (100, 100)) == (90, 90, 10, 10)


def test_units():
    assert im.to_pixels(35, "mm", 300, 0) == 413
    assert im.to_pixels(2, "in", 300, 0) == 600
    assert im.to_pixels(50, "%", 300, 1000) == 500
    assert abs(im.from_pixels(600, "in", 300, 0) - 2) < 1e-9


@pytest.mark.parametrize("fmt", ["JPG", "PNG", "WEBP", "PDF"])
def test_encode_formats(fmt):
    data = im.encode(make_photo(), im.OutputSettings(fmt=fmt, dpi=300))
    assert len(data) > 100
    if fmt != "PDF":
        r = Image.open(io.BytesIO(data)); assert r.size == (400, 300)
    if fmt == "JPG":
        assert round(Image.open(io.BytesIO(data)).info["dpi"][0]) == 300


def test_transparency_kept_png_webp_flattened_jpg():
    img = make_photo(alpha=True)
    png = Image.open(io.BytesIO(im.encode(img, im.OutputSettings(fmt="PNG"))))
    assert png.mode == "RGBA"
    webp = Image.open(io.BytesIO(im.encode(img, im.OutputSettings(fmt="WEBP"))))
    assert webp.mode == "RGBA"
    jpg = Image.open(io.BytesIO(im.encode(img, im.OutputSettings(fmt="JPG"))))
    assert jpg.mode == "RGB" and jpg.getpixel((0, 0)) == (255, 255, 255) or sum(jpg.getpixel((0, 0))) > 740


def test_target_size():
    img = make_photo(1600, 1200)
    os_ = im.OutputSettings(fmt="JPG", quality=95, target_kb=120)
    data, q, _ = im.encode_to_target(img, os_)
    assert len(data) <= 120 * 1024 and q is not None


def test_target_size_shrinks_when_needed():
    img = Image.fromarray(np.random.default_rng(0).integers(0, 255, (2000, 2000, 3), dtype="uint8"))
    notes = []
    data, q, final = im.encode_to_target(img, im.OutputSettings(fmt="JPG", target_kb=60), notes=notes)
    assert len(data) <= 60 * 1024 and final.width < 2000 and notes


def test_exif_orientation_and_icc(tmp_path):
    img = make_photo(400, 300)
    ex = Image.Exif(); ex[0x0112] = 6  # rotate 90 CW on display
    p = tmp_path / "o.jpg"
    from PIL import ImageCms
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    img.save(p, exif=ex.tobytes(), icc_profile=icc)
    li = im.load_image(p)
    assert li.image.size == (300, 400) and li.icc_profile
    res = im.process(li, im.EditState(), im.ResizeSettings(width=150, height=200), im.OutputSettings())
    out = Image.open(io.BytesIO(res.data))
    assert out.size == (150, 200) and out.info.get("icc_profile")
    assert out.getexif().get(0x0112, 1) == 1


def test_strip_metadata(tmp_path):
    img = make_photo(); ex = Image.Exif(); ex[0x010F] = "CameraMaker"
    p = tmp_path / "m.jpg"; img.save(p, exif=ex.tobytes())
    li = im.load_image(p)
    keep = im.process(li, im.EditState(), im.ResizeSettings(enabled=False), im.OutputSettings())
    strip = im.process(li, im.EditState(), im.ResizeSettings(enabled=False), im.OutputSettings(strip_metadata=True))
    assert Image.open(io.BytesIO(keep.data)).getexif().get(0x010F) == "CameraMaker"
    assert Image.open(io.BytesIO(strip.data)).getexif().get(0x010F) is None


def test_modes_loading(tmp_path):
    for mode in ["P", "L", "LA", "CMYK", "1", "I;16"]:
        img = Image.new(mode, (50, 40))
        p = tmp_path / f"t_{mode.replace(';','')}.{'tif' if mode in ('CMYK','I;16') else 'png'}"
        img.save(p)
        li = im.load_image(p)
        assert li.image.mode in ("RGB", "RGBA")


def test_no_upscale_option():
    rs = im.ResizeSettings(width=2000, height=2000, mode=im.MODE_FIT_INSIDE, allow_upscale=False)
    assert im.resize_image(make_photo(400, 300), rs).size == (400, 300)


def test_too_big_guard():
    with pytest.raises(ValueError):
        im.resize_image(make_photo(), im.ResizeSettings(width=40000, height=100))


def _seen(img, st):
    return np.asarray(im.apply_edits(img, st))


def test_rotate_flip_compose_like_user_sees():
    img = make_photo(120, 80)
    T = Image.Transpose
    st = im.EditState()
    seen = img
    ops = [("cw", None), ("fh", None), ("cw", None), ("fv", None), ("ccw", None), ("fh", None), ("cw", None)]
    for op, _ in ops:
        if op == "cw":
            st = im.rotate_state(st, img.size, True); seen = seen.transpose(T.ROTATE_270)
        elif op == "ccw":
            st = im.rotate_state(st, img.size, False); seen = seen.transpose(T.ROTATE_90)
        elif op == "fh":
            st = im.flip_state(st, img.size, True); seen = seen.transpose(T.FLIP_LEFT_RIGHT)
        else:
            st = im.flip_state(st, img.size, False); seen = seen.transpose(T.FLIP_TOP_BOTTOM)
        assert np.array_equal(_seen(img, st), np.asarray(seen)), op


def test_crop_follows_rotation_and_flip():
    img = make_photo(120, 80)
    T = Image.Transpose
    st = im.EditState(crop=(10, 5, 40, 30))
    seen = img.crop((10, 5, 50, 35))
    for op in ["cw", "fh", "ccw", "fv", "cw"]:
        if op == "cw":
            st = im.rotate_state(st, img.size, True); seen = seen.transpose(T.ROTATE_270)
        elif op == "ccw":
            st = im.rotate_state(st, img.size, False); seen = seen.transpose(T.ROTATE_90)
        elif op == "fh":
            st = im.flip_state(st, img.size, True); seen = seen.transpose(T.FLIP_LEFT_RIGHT)
        else:
            st = im.flip_state(st, img.size, False); seen = seen.transpose(T.FLIP_TOP_BOTTOM)
        assert np.array_equal(_seen(img, st), np.asarray(seen)), op


def test_enhanced_has_no_halos():
    """Sharpening must not create bright/dark outlines around edges."""
    img = Image.new("RGB", (60, 60), (60, 60, 60))
    ImageDraw.Draw(img).rectangle([20, 20, 40, 40], fill=(200, 200, 200))
    out = np.asarray(im.resample(img, (240, 240), im.UPSCALE_ENHANCED).convert("L"))
    lan = np.asarray(img.resize((240, 240), Image.Resampling.LANCZOS).convert("L"))
    # never brighter/darker than plain Lanczos already rings
    assert out.max() <= lan.max() and out.min() >= lan.min()


@pytest.mark.parametrize("mode", [im.MODE_FIT_PAD, im.MODE_FILL, im.MODE_STRETCH, im.MODE_FIT_INSIDE])
def test_point_mapping_roundtrip(mode):
    src = im.from_pil(make_photo(400, 300))
    st = im.EditState(crop=(50, 40, 200, 100))
    rs = im.ResizeSettings(width=600, height=600, mode=mode)
    out = im.resize_image(im.apply_edits(src.image, st), rs)
    for p in [(10, 20), (300, 300), (590, 100)]:
        x, y, k = im.result_to_source(p, src, st, rs, out.size)
        back = im.source_to_result((x, y), src, st, rs, out.size)
        assert abs(back[0] - p[0]) < 1e-6 and abs(back[1] - p[1]) < 1e-6
    # the centre of the crop maps to the centre of the result (all modes are centred)
    x, y, k = im.result_to_source((out.width / 2, out.height / 2), src, st, rs, out.size)
    assert abs(x - 150) < 1 and abs(y - 90) < 1 and k > 1


def test_proof_sheet():
    from app.core import proof
    ps = proof.ProofSettings(width_in=125, height_in=104, width_px=955)
    img = proof.render_proof(make_photo(895, 740), ps)
    assert img.width == 955 and img.height > 800
    assert proof.area_label(125, 104) == "90.28 Sq.Ft"
    assert proof.size_label(125, 104) == "125”x 104”"
    assert proof.size_label(125, 104, "ft") == "10'5” x 8'8”"
    ps2 = proof.ProofSettings(width_in=100, height_in=50, closeup=True, watermark="SAMPLE",
                              footer="Shop", fill=False, width_px=800)
    img2 = proof.render_proof(make_photo(400, 300), ps2)
    ox, oy, dw, dh = img2.info["design_box"]
    assert abs(dw / dh - 2.0) < 0.02


# ----------------------------------------------------------------------
# Print size labels and customer preview sheets
# ----------------------------------------------------------------------
def test_print_labels():
    from app.core import sheets as sh
    assert sh.size_text(4, 3) == "4.00 in × 3.00 in"
    assert sh.size_alt_text(4, 3) == "(10.16 cm × 7.62 cm / 102 mm × 76 mm)"
    assert sh.size_alt_text(4, 3, first_only=True) == "(10.16 cm × 7.62 cm)"
    assert sh.size_words(4, 3) == "4 inches × 3 inches"
    assert sh.length_label(4) == "4 inches (10.16 cm / 102 mm)"
    assert sh.length_label(1) == "1 inch (2.54 cm / 25 mm)"
    assert sh.area_text(4, 3) == "0.083 sq ft"
    assert sh.area_text(125, 104) == "90.28 sq ft"
    assert sh.area_text(120, 96, "sqm") == "7.43 sq m"
    assert abs(sh.from_unit(sh.to_unit(37.5, "ft"), "ft") - 37.5) < 1e-9
    assert sh.size_text(120, 96, "ft") == "10.00 ft × 8.00 ft"
    spec = sh.PrintSpec.from_pixels(1200, 900, 300)
    assert (spec.width_in, spec.height_in) == (4.0, 3.0)
    assert sh.print_quality(1200, 900, 4, 3)[1] == "good"
    assert sh.print_quality(1200, 900, 120, 90)[1] == "low"


def test_download_and_closeup_sheets():
    from app.core import sheets as sh
    spec = sh.PrintSpec(4, 3)
    a = sh.render_download_preview(make_photo(400, 300), spec, sh.SheetOptions(width_px=900, footer="Shop"))
    assert a.width == 900 and a.height > 700
    b = sh.render_closeup_preview(make_photo(400, 300), spec, (0.2, 0.8), 3.0, sh.SheetOptions(width_px=900))
    assert b.width == 900
    # tall banner + white bars + watermark still renders
    c = sh.render_download_preview(make_photo(400, 300), sh.PrintSpec(24, 72, "in"),
                                   sh.SheetOptions(width_px=600, fill=False, watermark="SAMPLE"))
    assert c.height > c.width
    assert sh.sheet_filename("wall.jpg", sh.PrintSpec(120, 96, "ft"), "preview", ".jpg") == \
        "wall_preview_10x8ft.jpg"


@pytest.mark.parametrize("center", [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)])
def test_closeup_layout_inside_picture(center):
    from app.core import sheets as sh
    lay = sh.closeup_layout(800, 600, center, 2.0)
    for x0, y0, x1, y1 in (lay.box, lay.inset):
        assert 0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 600
    # inset shows the marked spot magnified by the zoom factor
    assert abs((lay.inset[2] - lay.inset[0]) / (lay.box[2] - lay.box[0]) - 2.0) < 0.01
    if center in ((0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)):
        assert not sh._overlap(lay.box, lay.inset)


def test_shape_to_print():
    from app.core import sheets as sh
    img = make_photo(400, 300)
    assert sh.shape_to_print(img, 10, 10, fill=True).size == (300, 300)
    assert sh.shape_to_print(img, 10, 10, fill=False).size == (400, 400)


# ----------------------------------------------------------------------
# AI Upscale studio engine
# ----------------------------------------------------------------------
def test_upscale_factors_and_fallback():
    from app.core import upscale as up
    notes = []
    out = up.upscale(make_photo(100, 75), up.UpscaleSettings(factor=3.0), ai_engine=None, notes=notes)
    assert out.size == (300, 225) and notes and "Enhanced" in notes[0]


@pytest.mark.parametrize("name", [n for n, _ in __import__("app.core.upscale", fromlist=["PRESETS"]).PRESETS])
def test_upscale_presets_run(name):
    from app.core import upscale as up
    us = up.apply_preset(up.UpscaleSettings(factor=2.0), name)
    out = up.upscale(make_photo(80, 60, alpha=(name == "Text & Logo")), us)
    assert out.size == (160, 120)
    if name == "Text & Logo":
        assert out.mode == "RGBA"   # transparency kept


def test_upscale_fit_print_size_and_limits():
    from app.core import upscale as up
    assert up.size_for_print((400, 300), 120, 90, 100) == (12000, 9000)
    us = up.UpscaleSettings(target=up.size_for_print((400, 300), 20, 15, 100))
    assert up.target_size((400, 300), us) == (2000, 1500)
    assert up.check_target((40000, 100)) is not None
    with pytest.raises(ValueError):
        up.upscale(make_photo(100, 100), up.UpscaleSettings(factor=16.0, target=(40000, 40000)))


def test_upscale_detail_is_sharper_than_plain():
    from app.core import upscale as up
    small = make_photo(120, 90)
    soft = up.upscale(small, up.UpscaleSettings(factor=4.0, detail=0, denoise=0))
    crisp = up.upscale(small, up.UpscaleSettings(factor=4.0, detail=80, denoise=0))
    creative = up.upscale(small, up.UpscaleSettings(mode=up.MODE_CREATIVE, factor=4.0, detail=80,
                                                   denoise=0, texture=40))
    assert edge_energy(crisp) > edge_energy(soft)
    assert edge_energy(creative) > edge_energy(crisp)


def test_ai_engine_second_pass_targets_size(monkeypatch):
    """8x/16x: the 4x result is resized so the 2nd AI pass lands on the target."""
    from app.core import ai_upscale as ai
    eng = ai.RealEsrgan.__new__(ai.RealEsrgan)
    import threading
    eng.exe, eng.gpu_error, eng._lock = "x", None, threading.Lock()
    eng._cache_key = eng._cache_img = eng._cache2_key = eng._cache2_img = None
    calls = []

    def fake_x4(img, art):
        calls.append(img.size)
        return img.resize((img.width * 4, img.height * 4))
    eng._run_x4 = fake_x4
    out = eng.upscale_to(make_photo(100, 50), (800, 400))
    assert calls == [(100, 50), (200, 100)] and out.size == (800, 400)
    calls.clear()
    eng.upscale_to(make_photo(100, 50), (800, 400))      # cached
    assert calls == []


def test_tiff_output():
    data = im.encode(make_photo(), im.OutputSettings(fmt="TIFF", dpi=150))
    r = Image.open(io.BytesIO(data))
    assert r.format == "TIFF" and r.size == (400, 300) and round(r.info["dpi"][0]) == 150
