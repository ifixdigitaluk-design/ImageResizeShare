"""Image Resize & Share – entry point.

    python main.py                 start the app
    python main.py photo.jpg       start and open a photo
    python main.py --selftest      automated check (used by the build)
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _windows_setup() -> None:
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ImageResizeShare.App")
        except Exception:
            pass


def run_selftest(app, MainWindow) -> int:
    import tempfile

    from PIL import Image, ImageDraw
    from PySide6.QtCore import QEventLoop, QTimer

    from app.core import imaging as im
    from app.ui.batch import BatchThread

    tmp = Path(tempfile.mkdtemp(prefix="irs_selftest_"))
    os.environ["IRS_HOME"] = str(tmp / "home")            # never touch the real jobs and library
    from PySide6.QtCore import QSettings
    _qs = QSettings("ImageResizeShare", "ImageResizeShare")
    _last_job = _qs.value("studio_last_job")
    _qs.remove("studio_last_job")
    img = Image.new("RGB", (640, 480), (30, 120, 200))
    d = ImageDraw.Draw(img)
    for i in range(0, 640, 16):
        d.line([(i, 0), (i, 480)], fill=(255, 255, 255))
    d.text((20, 20), "Self test", fill=(0, 0, 0))
    src = tmp / "test.jpg"
    img.save(src, quality=95)
    img.save(tmp / "test2.png")

    w = MainWindow()
    w.show()
    w.sp_dpi.setValue(300)

    def wait(label):
        loop = QEventLoop()
        w.processed.connect(loop.quit)
        QTimer.singleShot(60000, loop.quit)
        loop.exec()
        w.processed.disconnect(loop.quit)
        r = w.result
        print(f"  {label}: {r.image.size if r else None}  {im.human_size(r.size_bytes) if r else ''}")
        return r

    def check(cond, msg):
        if not cond:
            raise AssertionError(msg)

    print("Self-test:")
    check(w.load_path(src), "load")
    r = wait("loaded")
    check(r.image.size == (640, 480), "original size")

    w.apply_preset(1080, 1080, "px", 0, "1080 x 1080")
    r = wait("preset 1080x1080 fit")
    check(r.image.size == (1080, 1080), "preset size")

    w.mode_group.button(1).click()
    w.canvas.set_rect((10, 20, 300, 200), emit=True)
    r = wait("crop 300x200 -> box")
    check(w.state.crop == (10, 20, 300, 200), "crop state")

    w.rotate(True)
    r = wait("rotated")
    w.flip(True)
    r = wait("flipped")
    w.undo()
    w.undo()
    r = wait("undo x2")
    check(w.state.rotation == 0 and not w.state.flip_h, "undo")

    w.reset_all()
    r = wait("reset")
    check(r.image.size == (640, 480), "reset size")

    # enlarge 3x with Enhanced
    w.mode_group.button(0).click()
    w.chk_ratio.setChecked(True)
    w.sp_w.setValue(1920)
    r = wait("enlarge to 1920 wide")
    check(r.image.size == (1920, 1440), "enlarge size")

    w.fmt_buttons["WEBP"].setChecked(True)
    r = wait("webp")
    check(r.fmt == "WEBP", "webp")
    w.fmt_buttons["JPG"].setChecked(True)
    w.chk_target.setChecked(True)
    w.sp_target.setValue(150)
    r = wait("jpg <=150KB")
    check(r.size_bytes <= 150 * 1024, "target size")
    w.chk_target.setChecked(False)

    w.cb_unit.setCurrentText("mm")
    w.apply_preset(35, 45, "mm", 300, "passport")
    r = wait("passport 35x45mm@300")
    check(r.image.size == (413, 531), "passport px")

    out = tmp / "saved.jpg"
    out.write_bytes(w._fresh_result().data)
    check(Image.open(out).size == (413, 531), "saved file")
    w.copy_result()

    bt = BatchThread([str(src), str(tmp / "test2.png")], tmp / "batch", 2, 800, 800, 50,
                     im.ResizeSettings(), im.OutputSettings(fmt="PNG"), w.ai, "{name}_{w}x{h}")
    bt.run()
    files = sorted(p.name for p in (tmp / "batch").iterdir())
    print("  batch:", files)
    check(len(files) == 2, "batch")

    # quick upscale + close-up loupe
    w.reset_all()
    wait("reset again")
    w.quick_upscale(2)
    r = wait("upscale 2x")
    check(r.image.size == (1280, 960), "upscale 2x")
    w._on_out_hover(640.0, 480.0)
    sx, sy, k = im.result_to_source((640, 480), w.src, w.state, w.current_settings()[0], r.image.size)
    check(abs(sx - 320) < 1 and abs(sy - 240) < 1 and abs(k - 2) < 0.01, "close-up mapping")
    w._on_out_click(100.0, 100.0)
    check(w._cu_pinned and w._cu_pt == (100.0, 100.0), "close-up pin")

    # classic proof sheet (still available from the Preview options)
    from app.ui.proof_dialog import ProofDialog
    dlg = ProofDialog(w, r.image, "test.jpg", 300)
    dlg.cb_px.setCurrentIndex(max(0, dlg.cb_px.findData(1800)))     # not whatever was used last time
    dlg.sp_w.setValue(125)
    dlg.chk_close.setChecked(True)
    dlg.ed_footer.setText("Shop name")
    dlg.render()
    ps = dlg.current_settings()
    check(abs(ps.height_in - 93.75) < 0.01, "proof height locked to ratio")
    check(dlg.rendered is not None and dlg.rendered.width == 1800, "proof render")
    dlg.accept()

    # Download Preview + Closeup Print Preview dialogs
    from app.ui.preview_dialogs import CloseupPrintPreviewDialog, DownloadPreviewDialog
    ctx = w._preview_ctx()
    check(ctx is not None and abs(ctx.spec.width_in - r.image.width / w.sp_dpi.value()) < 1e-6, "print spec")
    dp = DownloadPreviewDialog(w, ctx)
    from app.core import sheets as sh
    dp._spec = sh.PrintSpec(30 / 2.54, 30 / 2.54 * 0.75, "cm")   # 30 cm wide
    dp.refresh()
    spec = dp.spec()
    check(abs(spec.width_in - 30 / 2.54) < 0.01 and abs(spec.height_in / spec.width_in - 0.75) < 0.01,
          "print size in cm, shape kept")
    sheet = dp.render_sheet()
    check(sheet.width == 1800 and "cm" in dp.v_size.text(), "download preview sheet")
    (tmp / "preview.jpg").write_bytes(dp._encode(sheet, "JPG"))
    print("  download preview:", dp.v_size.text(), "|", dp.v_area.text())
    w._remember_print(ctx, dp)
    dp.accept()
    cp = CloseupPrintPreviewDialog(w, w._preview_ctx())
    check(abs(cp.spec().width_in - 30 / 2.54) < 0.01, "print size remembered between previews")
    cp.canvas.set_center(0.3, 0.3)
    cs = cp.render_sheet()
    check(cs.width == 1800, "closeup sheet")
    print("  closeup preview:", cs.size, cp.zoom())
    cp.accept()

    # zoom controls
    w.view_out.fit()
    w._on_zoom_text("200%")
    check(abs(w.view_out.zoom() - 2.0) < 1e-6, "zoom box")
    w._zoom_step(1.25)
    check(abs(w.view_out.zoom() - 2.5) < 1e-6, "zoom step")
    w._on_zoom_slider(w._z_to_slider(0.5))
    check(abs(w.view_out.zoom() - 0.5) < 0.01, "zoom slider")

    # AI Upscale studio (falls back to Enhanced when the AI engine is missing)
    from app.core import upscale as up
    from app.ui.upscale_dialog import UpscaleDialog
    w.reset_all()
    wait("reset for upscale")
    ud = UpscaleDialog(w, im.apply_edits(w.src.image, w.state), "test.jpg", w.ai, 300)
    ud._preset("Wallpaper")
    ud._set_factor(2.0)
    ud.run_upscale()
    ud.wait_done()
    check(ud.result is not None and ud.result.size == (1280, 960), "upscale studio 2x")
    ud.b_fit.setChecked(True)
    ud.cb_pu.setCurrentIndex(ud.cb_pu.findData("in"))
    ud.sp_pw.setValue(20.0)
    ud.sp_dpi.setValue(100)
    check(up.target_size(ud.image.size, ud.us) == (2000, 1500), "fit print size 20in @100dpi")
    ud.run_upscale()
    ud.wait_done()
    check(ud.result.size == (2000, 1500), "upscale to print size")
    applied = []
    ud.applied.connect(lambda *a: applied.append(a))
    ud.applied.connect(w._apply_upscaled)
    ud.use_result()
    r = wait("use upscaled in editor")
    check(applied and w.src.image.size == (2000, 1500) and w.sp_dpi.value() == 100, "use in editor")
    check(w.up_badge.isVisibleTo(w) and "upscaled" in w.up_badge.text().lower(), "upscale badge")
    check(r.image.size == (2000, 1500), "result after upscale")
    w.undo_upscale()
    r = wait("undo upscale")
    check(w.src.image.size == (640, 480), "undo upscale")

    # remove image (X)
    w.clear_image()
    check(w.src is None and not w.file_card.isVisibleTo(w) and not w.tile_print.isEnabled(), "remove image")
    check(w.load_path(src), "reload")
    wait("reloaded")

    # sizes past what a PC can handle are held to the limits (area and each side)
    for tw, th in ((999999, 999999), (353553, 707)):
        w.tw, w.th = tw, th
        w._size_edited()
        check(w.tw * w.th <= im.MAX_OUTPUT_PIXELS and max(w.tw, w.th) <= im.MAX_OUTPUT_SIDE,
              f"size {tw}×{th} held to the limits")
    # a big print is previewed at screen size; Download makes (and keeps) the real full size
    w.tw, w.th = 4800, 3600
    w._size_edited()
    r = wait("big print preview")
    check(r.is_preview and r.out_size == (4800, 3600) and r.image.width < 4800, "big print shown as a fast preview")
    check(w.result_size == (4800, 3600) and "≈" in w.out_info.text(), "preview shows the real size")
    full = w._fresh_result()
    check(full is not None and not full.is_preview and full.image.size == (4800, 3600), "download makes full size")
    check(w._fresh_result() is full, "full size reused for the next export")
    w.tw, w.th = 640, 480
    w._size_edited()
    wait("back to normal size")
    check(not w.result.is_preview and w._full is None, "small size made for real")

    # Help: error report and update notice (offline)
    from app.ui import support
    rd = support.ErrorReportDialog(w)
    rd.copy()
    check(rd.report is not None and rd.report.is_file() and rd.report.suffix == ".zip", "error report zip")
    rd.close()
    rel = support.newest_windows_release([{"tag_name": "windows-v9.0.0.5", "html_url": "https://example.invalid"}])
    check(rel is not None and rel["version"] > support.current_version(), "update found in release tags")
    w._show_update_button(rel)
    check(w._update_btn.isVisibleTo(w) and "9.0.0" in w._update_btn.text(), "update notice in the status bar")
    w._update_btn.hide()

    print("  AI engine:", w.ai.status_text())
    studio_selftest(app, w, tmp, check)
    from app.ui import errors
    check(errors.COUNT[0] == 0, f"{errors.COUNT[0]} error(s) inside the app during the test (see above)")
    w.close()
    if _last_job:
        _qs.setValue("studio_last_job", _last_job)
    else:
        _qs.remove("studio_last_job")
    print("SELFTEST OK")
    return 0


def studio_selftest(app, w, tmp: Path, check) -> None:
    """Wall Studio: measure from a photo, design, room, colour, pattern, proof, print package, jobs."""
    import time

    import numpy as np
    from PIL import Image, ImageDraw
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QMessageBox

    from app.core import jobs
    from app.core import measure as ms
    from app.core import mockup as mk
    from app.core import preflight as pf
    from app.core import wall as wl
    from app.ui import share

    def pump(sec=0.05):
        t = time.time()
        while True:
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
            app.processEvents()
            if time.time() - t >= sec:
                break

    # no folders / browsers / questions during the test
    share.show_in_folder = lambda *_a, **_k: None
    share.open_whatsapp = lambda *_a, **_k: ""
    QMessageBox.question = staticmethod(lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *_a, **_k: QMessageBox.StandardButton.Ok)

    print("Wall Studio:")
    w.set_page(1)
    pump()
    st = w.studio
    st.new_job()
    st.job.customer, st.job.phone = "Self Test", "+440000000000"
    # a photo of a 4.2 x 2.7 m wall with a door, a window and a sofa, taken at an angle
    W, H = 4.2, 2.7
    room = wl.Wall(width=W, height=H, obstacles=[wl.Obstacle.make("door", x=0.35, w=0.9, h=2.1),
                                                 wl.Obstacle.make("window", x=1.95, y=1.05, w=1.4, h=1.15),
                                                 wl.Obstacle.make("sofa", x=1.7, w=1.95, h=0.8)])
    ppm = 200
    front = mk.render_room([room], None, "empty", ppm=ppm)
    side = max(0.8, W * 0.16)
    A = np.array([[ppm, 0, side * ppm], [0, ppm, 0.45 * ppm], [0, 0, 1.0]])
    Hc = ms.camera_homography(W, H, (1600, 1200), 1350, 20, -5, 4.6, (0.2, -0.15))
    import cv2
    photo = Image.fromarray(cv2.warpPerspective(np.asarray(front), Hc @ np.linalg.inv(A), (1600, 1200),
                                                flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT))
    photo.save(tmp / "wall_photo.jpg", quality=92)
    corners = [tuple(p) for p in ms.apply_h(Hc, [(0, 0), (W, 0), (W, H), (0, H)])]

    from app.ui.measure_dialog import MeasureDialog
    st.ensure_dir()
    md = MeasureDialog(st, st.job, 0, st.job_dir)
    md._set_photo(tmp / "wall_photo.jpg", corners, keep_items=False)
    md.ed_w.setText("4.2 m")
    md.ed_h.setText("8' 10\"")
    md._solve(final=True)
    check(md.res is not None and abs(md.res.width - 4.2) < 0.01, "measure width")
    check(md.res.accuracy_pct is not None and md.res.accuracy_pct < 2, "measure accuracy check")
    md.ed_w.setText("4200 m")                                    # a typo: metres instead of cm
    md.ed_h.setText("")
    md._solve(final=True)
    check(md.res is None and "bigger than any wall" in md.lbl_alt.text(), "measure refuses an impossible size")
    md.ed_w.setText("abc")                                       # not a size, then change the unit
    u0 = md.cb_unit.currentIndex()
    md.cb_unit.setCurrentIndex((u0 + 1) % md.cb_unit.count())
    md.cb_unit.setCurrentIndex(u0)
    md.ed_w.setText("4,2 m")                                     # decimal comma
    md.ed_h.setText("8' 10\"")
    md._solve(final=True)
    check(md.res is not None and abs(md.res.width - 4.2) < 0.01, "measure after a unit change and a decimal comma")
    md._detected(ms.auto_detect(md.work, md.res, md.flat, md.ppm))
    kinds = sorted(o.kind for o in md.wall.obstacles)
    print("  measured:", md.lbl_size.text(), "| found:", kinds)
    check("door" in kinds and "window" in kinds, "doors and windows found")
    door = next(o for o in md.wall.obstacles if o.kind == "door")
    check(abs(door.w - 0.9) < 0.15 and abs(door.h - 2.1) < 0.15, "door size")
    md.apply()
    check(md.applied and (st.job_dir / md.result_wall.photo).is_file(), "survey photo saved in the job")
    r = md.result_wall
    w0 = st.job.walls[0]
    w0.width, w0.height, w0.obstacles, w0.photo, w0.corners, w0.survey = (r.width, r.height, r.obstacles, r.photo,
                                                                          r.corners, r.survey)
    st.refresh_forms()
    st._changed("geometry", undoable=False)

    # design
    art = Image.new("RGB", (3000, 2000), (40, 90, 160))
    dd = ImageDraw.Draw(art)
    for i in range(0, 3000, 60):
        dd.line([(i, 0), (3000 - i, 2000)], fill=(240, 200, 80), width=6)
    art.save(tmp / "mural.png")
    st._set_design(tmp / "mural.png", "mural")
    pump(0.3)
    check(st.source is not None and len(wl.compute_panels(st.job)) == 5, "design + 5 panels on a 4.2 m wall")
    checks = pf.run(st.job, st.source)
    print("  checks:", pf.counts(checks), [c.title for c in checks if c.level in ("warn", "error")])

    # room, colour, pattern
    from app.ui.room_dialog import RoomDialog
    rd = RoomDialog(st)
    for scene in ("living", "photo"):
        prm = rd._params()
        prm["scene"] = scene
        img = rd._make(prm, 900, fast=True)
        check(img is not None and img.width > 500, f"room mockup {scene}")
    rd.close()
    from app.ui.colour_dialog import ColourDialog
    cd = ColourDialog(st)
    cd.way = "Sage green"
    cd._set_picked((40, 90, 160))
    cd._add_repl((200, 60, 60))
    out = cd._ops(cd.src)
    check(out.size == cd.src.size, "colour changes")
    cd.close()
    from app.ui.pattern_dialog import PatternDialog
    pd_ = PatternDialog(st)
    pd_._set_tile(art.crop((0, 0, 600, 600)), "tile")
    pd_.chk_seam.setChecked(True)
    pd_.use()
    tile, spec, _n = pd_.result
    check(spec.seamless and abs(spec.repeat_w - 0.53) < 1e-6, "pattern spec")

    # proof + approval
    from app.ui.job_docs import ProofDialog
    pr_d = ProofDialog(st)
    pr_d.page = pr_d._make(pr_d._params())
    from app.core import documents as docs
    check(pr_d.page.size == docs.A3, "proof sheet A3")
    pr_d.save()
    check(st.job.proof_file and (st.job_dir / st.job.proof_file).is_file() and st.job.status == "Proof sent",
          "proof saved")
    st.job.approved_by, st.job.approved_on = "Self Test", "today"
    st.job.set_status("Approved")
    pr_d.close()

    # print package (small and fast)
    st.job.walls[0].width, st.job.walls[0].height = 1.2, 1.0
    st.job.walls[0].obstacles = []
    st.job.output_preset = "Proof print – JPG 72 dpi"
    st._changed("geometry", undoable=False)
    from app.ui.print_dialog import PrintDialog
    pdlg = PrintDialog(st)
    pdlg.chk_strip.setChecked(False)
    pdlg.create()
    t0 = time.time()
    while pdlg.running is not None and time.time() - t0 < 120:
        pump(0.1)
    res = pdlg.result
    check(res is not None and len(list((res.folder / "panels").iterdir())) == 2, "print package panels")
    check((res.folder / "job_ticket.txt").is_file() and (res.folder / "installation_sheet.pdf").is_file(),
          "job ticket + installation sheet")
    check(st.job.status == "Printing", "status after printing")
    print("  package:", res.folder.name, len(res.files), "files")
    pdlg.close()

    # jobs + library + showroom
    st.save_now()
    w.set_page(2)
    pump(0.2)
    check(len(w.jobs_page.rows) >= 1, "jobs list")
    jobs.library_add(tmp / "mural.png", "Self-test mural", ["test"], "mural", 0)
    w.jobs_page.show_library()
    lib = w.jobs_page.library
    check(len(lib.items) == 1, "design library")
    from app.ui.jobs_page import Showroom
    sr = Showroom(w)
    sr._open(0)
    check(sr.d_img.pixmap() is not None and not sr.d_img.pixmap().isNull(), "showroom")
    sr.close()

    # 3.1: shaped walls, expand, text & logo, installs, posts, backup
    print("Wall Studio 3.1:")
    w.set_page(1)
    pump(0.1)
    st.job.walls[0].width, st.job.walls[0].height = 3.6, 2.6
    st.job.walls[0].shape = "stairs"
    st.job.walls[0].shape_params = wl.default_shape_params("stairs", 3.6, 2.6)
    st.job.output_preset = "Print house – TIFF RGB 100 dpi"
    st._changed("geometry", undoable=False)
    panels = wl.compute_panels(st.job)
    check(max(p.height for p in panels) - min(p.height for p in panels) > 0.5, "panels cut to a staircase wall")
    check(st.job.walls[0].area() < 3.6 * 2.6 - 1.0, "staircase wall area")
    from app.ui.shape_dialog import ShapeDialog
    sd = ShapeDialog(w, st.job.walls[0], "m")
    check(sd.result_wall().shape == "stairs", "shape dialog")
    sd.close()
    from app.core import expand as ex
    narrow = art.crop((0, 0, 1200, 2000))
    pl = ex.plan(narrow.size, st.job.art_width / st.job.art_height)
    big = ex.expand_offline(narrow, pl, "mirror")
    check(abs(big.width / big.height - st.job.art_width / st.job.art_height) < 0.01, "expand to the wall shape")
    from app.ui.expand_dialog import ExpandDialog
    before = (st.job.design, st.design_img.size)
    st._set_design(narrow, "narrow")
    st.undo()                                    # undo brings back the old picture, not just its name
    check((st.job.design, st.design_img.size) == before, "undo a design change")
    st.redo()
    check(st.design_img.size == narrow.size and "narrow" in st.job.design, "redo a design change")
    edlg = ExpandDialog(st)
    edlg.use()
    check(edlg.result_img is not None and edlg.result_img.size == big.size, "expand dialog")
    from app.core import layers as lyr
    st.job.layers = [lyr.new_text_layer(st.job, "SELF TEST")]
    st._changed("design", undoable=False)
    check(isinstance(st.source, lyr.LayeredSource), "text layer on the design")
    from app.ui.layers_dialog import LayersDialog
    ld = LayersDialog(st)
    ld.add_text()
    check(len(ld.result_layers()) == 2, "layers dialog")
    ld.close()
    st.save_now()
    # a job that can't be saved (read-only or offline folder) is never dropped by "New job"
    import app.ui.wall_studio as ws_mod
    from PySide6.QtWidgets import QMessageBox as MB
    keep = (ws_mod.jobs.save_job, MB.question, MB.warning)

    def refuse(*a, **k):
        raise PermissionError(13, "read-only")
    ws_mod.jobs.save_job = refuse
    MB.warning = staticmethod(lambda *a, **k: MB.StandardButton.Ok)
    MB.question = staticmethod(lambda *a, **k: MB.StandardButton.No)
    try:
        no, cust = st.job.job_no, st.job.customer
        st.job.customer = "Unsaved change"
        check(not st.new_job() and st.job.job_no == no and st.job.customer == "Unsaved change",
              "an unsaved job is kept when the user says No")
    finally:
        ws_mod.jobs.save_job = keep[0]
        MB.question, MB.warning = staticmethod(keep[1]), staticmethod(keep[2])
        st.job.customer = cust
    check(st.save_now(), "job saves again")
    from app.core import posts
    post = posts.make_post(art, jobs.load_business(), "story", before=narrow, title="Test")
    check(post.size == (1080, 1920), "before/after post")
    st.job.install_date, st.job.install_time = "2030-01-02", "10:00"
    check("2030" in posts.reminder_text(st.job, {"name": "Shop"}), "reminder text")
    st.save_now()
    w.set_page(2)
    w.jobs_page.show_installs()
    pump(0.2)
    check(len(w.jobs_page.installs.rows) >= 1, "installs list")
    from app.core import backup as bk
    b = bk.backup(tmp / "backups")
    check(b.files > 3 and b.path.is_file(), "backup")
    r = bk.restore(b.path, dest=tmp / "restored")
    check(r.jobs_added >= 1, "restore")
    print("  backup:", b.files, "files;", "restore:", r)
    w.set_page(0)


def main() -> int:
    selftest = "--selftest" in sys.argv
    if selftest:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _windows_setup()

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow
    from app.ui.qtutil import app_icon
    from app.ui.style import QSS

    from app.ui import errors
    errors.install(show_dialogs=not selftest)
    app = QApplication(sys.argv)
    app.setApplicationName("Image Resize & Share")
    app.setOrganizationName("ImageResizeShare")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)
    app.setWindowIcon(app_icon())

    if selftest:
        # Run with default settings (saved ones such as unit = mm change the results, so the
        # second self-test in build.bat / CI would fail), then put the user's settings back.
        from PySide6.QtCore import QSettings
        store = QSettings("ImageResizeShare", "ImageResizeShare")
        saved = {k: store.value(k) for k in store.allKeys()}
        store.clear()
        store.sync()
        try:
            return run_selftest(app, MainWindow)
        except Exception:
            traceback.print_exc()
            print("SELFTEST FAILED")
            return 1
        finally:
            store.clear()
            for k, v in saved.items():
                store.setValue(k, v)
            store.sync()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    files = [a for a in sys.argv[1:] if not a.startswith("-") and Path(a).is_file()]
    server = _single_instance(files)
    if server is None:          # already open: the files were handed over to it
        return 0
    from app.ui.settings_dialogs import startup_data_dir
    missing = startup_data_dir()
    try:
        w = MainWindow()
    except Exception:
        txt = traceback.format_exc()
        errors.write_log(txt)
        QMessageBox.critical(None, "Image Resize & Share",
                             "The app could not start.\n\n" + txt.strip().splitlines()[-1][:300] +
                             f"\n\nDetails were written to:\n{errors.log_path()}")
        return 1
    w.show()
    if missing:
        from app.core import paths
        QTimer.singleShot(300, lambda: QMessageBox.warning(
            w, "Data folder not found",
            f"Your jobs folder could not be found:\n{missing}\n\n"
            "If it is on a USB drive or network drive, connect it and restart the app.\n\n"
            f"For now the app is using:\n{paths.base_dir()}"))
    QTimer.singleShot(20000, w.run_auto_backup)
    QTimer.singleShot(8000, w.auto_update_check)          # at most once a day, quietly
    if server is not False:
        def _incoming():
            while server.hasPendingConnections():
                sock = server.nextPendingConnection()

                def _read(sock=sock):
                    data = bytes(sock.readAll()).decode("utf-8", "replace")
                    paths = [x for x in data.split("\n") if x.strip()]
                    if w.isMinimized():
                        w.showNormal()
                    w.raise_()
                    w.activateWindow()
                    if paths and Path(paths[0]).is_file():
                        w.set_page(0)
                        w.load_path(paths[0])
                    sock.disconnectFromServer()
                sock.readyRead.connect(_read)
                sock.disconnected.connect(sock.deleteLater)
        server.newConnection.connect(_incoming)
    if files:
        w.load_path(files[0])
    return app.exec()


def _single_instance(files):
    """Only one copy of the app may run (two copies saving the same job would overwrite each
    other's changes). A second start hands its picture to the open window and quits.
    Returns the QLocalServer for the first copy, False if that can't be set up, or None when
    another copy is already running."""
    try:
        import getpass
        from PySide6.QtNetwork import QLocalServer, QLocalSocket
        name = "ImageResizeShare-" + "".join(ch for ch in getpass.getuser() if ch.isalnum())[:40]
        sock = QLocalSocket()
        sock.connectToServer(name)
        if sock.waitForConnected(400):
            sock.write("\n".join(str(Path(f).resolve()) for f in files).encode("utf-8") or b"\n")
            sock.waitForBytesWritten(1000)
            sock.disconnectFromServer()
            return None
        server = QLocalServer()
        if not server.listen(name):
            QLocalServer.removeServer(name)        # left over after a crash
            if not server.listen(name):
                return False
        return server
    except Exception:
        return False


def _shutdown(rc: int) -> None:
    """Leave without Python tearing down Qt objects one by one: after many windows have been
    open that can crash in Qt's own clean-up on some PCs ("stopped working" on exit).
    Settings are written and background work finishes first."""
    try:
        from PySide6.QtCore import QSettings, QThreadPool
        QThreadPool.globalInstance().waitForDone(8000)
        QSettings("ImageResizeShare", "ImageResizeShare").sync()
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:          # None in the windowed (no console) exe
                stream.flush()
        except Exception:
            pass
    if sys.platform.startswith("win"):
        # os._exit still unloads the Qt DLLs, which crashed (access violation) on the
        # headless Windows build machine after the self-test had passed.
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            k32.TerminateProcess(k32.GetCurrentProcess(), rc & 0xFFFFFFFF)
        except Exception:
            pass
    os._exit(rc)


if __name__ == "__main__":
    _shutdown(main())
