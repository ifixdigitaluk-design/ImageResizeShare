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
