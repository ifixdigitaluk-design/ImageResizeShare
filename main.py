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

# Qt objects created by the self-test are kept alive until the process exits:
# destroying the main window while a background job is still finishing can
# crash on Windows.
_KEEP_ALIVE: list = []


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
    img = Image.new("RGB", (640, 480), (30, 120, 200))
    d = ImageDraw.Draw(img)
    for i in range(0, 640, 16):
        d.line([(i, 0), (i, 480)], fill=(255, 255, 255))
    d.text((20, 20), "Self test", fill=(0, 0, 0))
    src = tmp / "test.jpg"
    img.save(src, quality=95)
    img.save(tmp / "test2.png")

    w = MainWindow()
    _KEEP_ALIVE.append(w)
    w.show()

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

    # proof sheet
    from app.ui.proof_dialog import ProofDialog
    dlg = ProofDialog(w, r.image, "test.jpg", 300)
    dlg.sp_w.setValue(125)
    dlg.chk_close.setChecked(True)
    dlg.ed_footer.setText("Shop name")
    dlg.render()
    ps = dlg.current_settings()
    check(abs(ps.height_in - 93.75) < 0.01, "proof height locked to ratio")
    check(dlg.rendered is not None and dlg.rendered.width == 1800, "proof render")
    (tmp / "proof.jpg").write_bytes(dlg._encode("JPG"))
    print("  proof:", dlg.rendered.size, dlg.area_big.text())
    dlg.accept()

    print("  AI engine:", w.ai.status_text())
    w.close()
    print("SELFTEST OK")
    return 0


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

    app = QApplication(sys.argv)
    app.setApplicationName("Image Resize & Share")
    app.setOrganizationName("ImageResizeShare")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(QSS)
    app.setWindowIcon(app_icon())

    if selftest:
        from PySide6.QtCore import QSettings
        # Run with default settings (saved settings such as unit = mm would
        # change the results), then put the user's settings back.
        store = QSettings("ImageResizeShare", "ImageResizeShare")
        saved = {k: store.value(k) for k in store.allKeys()}
        store.clear()
        store.sync()
        try:
            code = run_selftest(app, MainWindow)
        except Exception:
            traceback.print_exc()
            print("SELFTEST FAILED")
            code = 1
        store.clear()
        for k, v in saved.items():
            store.setValue(k, v)
        store.sync()
        sys.stdout.flush()
        sys.stderr.flush()
        # Skip Python/Qt teardown: on headless Windows runners it can crash
        # (access violation) after the test has already passed.
        os._exit(code)

    w = MainWindow()
    w.show()
    files = [a for a in sys.argv[1:] if not a.startswith("-") and Path(a).is_file()]
    if files:
        w.load_path(files[0])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
