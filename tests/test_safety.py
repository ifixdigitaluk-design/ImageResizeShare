"""Saving must never leave half-written files or lose the old one; backups never include backups."""
import zipfile

import pytest

from app.core import backup as bk
from app.ui.errors import write_bytes_safely


def test_write_bytes_safely(tmp_path):
    p = tmp_path / "out.jpg"
    write_bytes_safely(p, b"first")
    assert p.read_bytes() == b"first"
    write_bytes_safely(p, b"second")
    assert p.read_bytes() == b"second"
    assert not list(tmp_path.glob("*.part"))


def test_failed_save_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / "out.jpg"
    p.write_bytes(b"good")

    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        write_bytes_safely(p, b"new")
    assert p.read_bytes() == b"good"
    assert not list(tmp_path.glob("*.part"))


def test_backup_skips_old_backups(tmp_path):
    src = tmp_path / "data"
    (src / "Jobs" / "JOB-1").mkdir(parents=True)
    (src / "Jobs" / "JOB-1" / "job.json").write_text("{}", encoding="utf-8")
    (src / "Jobs" / (bk.PREFIX + "20260101-000000.zip")).write_bytes(b"x" * 100)
    (src / "Jobs" / "JOB-1" / "job.json.tmp").write_text("{}", encoding="utf-8")
    r = bk.backup(tmp_path / "out", src=src)
    names = zipfile.ZipFile(r.path).namelist()
    assert any(n.endswith("job.json") for n in names)
    assert not any(bk.PREFIX in n or n.endswith(".tmp") for n in names)


def test_whatsapp_numbers():
    from app.ui.share import clean_phone
    assert clean_phone("07700 900123", "44") == "447700900123"
    assert clean_phone("+44 (0)7700-900123", "92") == "447700900123"
    assert clean_phone("0044 7700 900123", "") == "447700900123"
    assert clean_phone("0300 1234567", "92") == "923001234567"
    assert clean_phone("+92 300 1234567", "44") == "923001234567"
    assert clean_phone("", "44") == ""


def test_lengths_with_decimal_comma():
    from app.core import units as un
    assert un.parse_length("4,2") == pytest.approx(4.2)
    assert un.parse_length("3,25 m") == pytest.approx(3.25)
    assert un.parse_length("420cm") == pytest.approx(4.2)
    with pytest.raises(ValueError):
        un.parse_length("1,200")              # thousands separator: not guessed
    with pytest.raises(ValueError):
        un.parse_length("abc")


def test_test_strip_is_held_to_a_safe_size():
    from PIL import Image
    from app.core import documents as docs
    from app.core import wall as wl

    class Flat:
        def render(self, x0, y0, x1, y1, W, H):
            return Image.new("RGB", (W, H), (90, 90, 90))

    j = wl.Job(job_no="T")
    big = docs.test_strip(Flat(), j, (1.5, 1.2), (6.0, 0.30), 600)         # 6 m roll at 600 dpi
    assert big.width * big.height < docs.TEST_STRIP_MAX_PX * 1.3
    a4 = docs.test_strip(Flat(), j, (1.5, 1.2), (0.297, 0.21), 300)
    assert a4.width == round(0.297 * 300 / 0.0254)                        # normal strips unchanged


@pytest.mark.parametrize("mode,size", [("RGB", (2501, 1999)), ("RGBA", (2100, 2050))])
def test_big_picture_to_screen_is_exact(mode, size):
    import numpy as np
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.ui.qtutil import pil_to_qimage, qimage_to_pil
    arr = np.random.default_rng(1).integers(0, 255, (size[1], size[0], len(mode)), dtype=np.uint8)
    img = Image.fromarray(arr, mode)
    back = qimage_to_pil(pil_to_qimage(img)).convert(mode)    # 2501 × 3 bytes: rows are padded
    assert np.array_equal(np.asarray(back), arr)


def test_update_check_reads_release_tags(monkeypatch):
    from app.ui import support
    rels = [{"tag_name": "windows-v1.0.57"},                       # old tag style: ignored
            {"tag_name": "android-v1.0.9"},
            {"tag_name": "windows-v3.1.1.60", "html_url": "u60"},
            {"tag_name": "windows-v3.2.0.61", "html_url": "u61", "body": "New"},
            {"tag_name": "windows-v3.3.0.62", "draft": True}]
    best = support.newest_windows_release(rels)
    assert best["label"] == "3.2.0" and best["build"] == 61 and best["url"] == "u61"
    monkeypatch.setattr(support, "fetch_releases", lambda *a, **k: rels)
    monkeypatch.setattr(support, "current_version", lambda: (3, 2, 0, 61))
    assert support.check_for_update() is None                      # already the newest
    monkeypatch.setattr(support, "current_version", lambda: (3, 1, 1, 0))
    assert support.check_for_update()["label"] == "3.2.0"


def test_error_report_zip(tmp_path, monkeypatch):
    import zipfile
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.ui import errors, share, support
    log = tmp_path / "errors.log"
    log.write_text("\n===== 2026-10-23 10:00:00 =====\nTraceback: boom\n", encoding="utf-8")
    monkeypatch.setattr(errors, "log_path", lambda: log)
    monkeypatch.setattr(share, "temp_folder", lambda: tmp_path)
    z = zipfile.ZipFile(support.make_report())
    assert set(z.namelist()) == {"about-this-pc.txt", "errors.log"}
    assert "boom" in z.read("errors.log").decode()
    assert "Image Resize & Share" in z.read("about-this-pc.txt").decode()
    assert support.error_count_in_log() == 1


def test_update_check_from_a_latest_json(monkeypatch):
    import app as app_pkg
    from app.ui import support
    monkeypatch.setattr(app_pkg, "UPDATE_JSON_URL", "https://example.invalid/latest.json")
    monkeypatch.setattr(support, "_get_json", lambda url, t: {"version": "3.4.0", "build": 70, "url": "u"})
    monkeypatch.setattr(support, "current_version", lambda: (3, 1, 1, 60))
    rel = support.check_for_update()
    assert rel["label"] == "3.4.0" and rel["build"] == 70 and rel["url"] == "u"
