"""
Back up and restore everything the app keeps: jobs (designs, survey photos, proofs,
mockups), the design library, colour profiles and palettes, business details and
output presets.

Print packages (the big panel files) can be left out – they can always be made
again from the job.
"""
from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from app.core.paths import base_dir

Progress = Callable[[float, str], None]
TOP_FILES = ("business.json", "output_presets.json")
TOP_DIRS = ("Jobs", "Library", "Palettes", "Profiles")
PREFIX = "ImageResizeShare-backup-"


@dataclass
class BackupResult:
    path: Path
    files: int
    bytes: int


def _walk(root: Path, include_print: bool):
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        if not include_print:
            dirnames[:] = [n for n in dirnames if n != "print"]
        dirnames[:] = [n for n in dirnames if n != "_deleted"]
        for n in filenames:
            if n.startswith(PREFIX) or n.endswith((".tmp", ".part")):   # never back up backups
                continue
            yield d / n


def backup(dest_dir: Path, include_print: bool = False, progress: Optional[Progress] = None,
           cancel: Optional[Callable[[], bool]] = None, src: Optional[Path] = None) -> BackupResult:
    src = Path(src or base_dir())
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    files: List[Path] = [src / f for f in TOP_FILES if (src / f).is_file()]
    files += [p for p in src.glob("logo.*") if p.is_file()]
    for d in TOP_DIRS:
        if (src / d).is_dir():
            files += list(_walk(src / d, include_print))
    total = sum(f.stat().st_size for f in files) or 1
    out = dest_dir / f"{PREFIX}{datetime.now():%Y%m%d-%H%M%S}.zip"
    for old in Path(dest_dir).glob(f"{PREFIX}*.part"):          # left over when the PC was switched off
        try:
            if datetime.now().timestamp() - old.stat().st_mtime > 6 * 3600:
                old.unlink()
        except OSError:
            pass
    tmp = out.with_suffix(".part")
    done = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr("backup.json", json.dumps({"app": "Image Resize & Share", "made": datetime.now().isoformat(
            timespec="seconds"), "from": str(src), "files": len(files), "include_print": include_print}, indent=1))
        for f in files:
            if cancel and cancel():
                z.close()
                tmp.unlink(missing_ok=True)
                raise InterruptedError("Backup stopped")
            rel = f.relative_to(src).as_posix()
            # pictures are already compressed: store them
            stored = f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".zip", ".pdf", ".heic")
            z.write(f, rel, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
            done += f.stat().st_size
            if progress:
                progress(done / total, rel)
    tmp.replace(out)
    return BackupResult(out, len(files), out.stat().st_size)


def prune(dest_dir: Path, keep: int = 5) -> int:
    """Delete the oldest automatic backups, keeping `keep`."""
    old = sorted(Path(dest_dir).glob(f"{PREFIX}*.zip"))
    n = 0
    for f in old[:-keep] if keep > 0 else old:
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    return n


def last_backup(dest_dir: Path) -> Optional[datetime]:
    files = sorted(Path(dest_dir).glob(f"{PREFIX}*.zip")) if dest_dir and Path(dest_dir).is_dir() else []
    if not files:
        return None
    return datetime.fromtimestamp(files[-1].stat().st_mtime)


@dataclass
class RestoreResult:
    jobs_added: int
    jobs_updated: int
    jobs_kept: int
    other_files: int


def _job_updated(data: bytes) -> str:
    try:
        return json.loads(data.decode("utf-8")).get("updated", "")
    except Exception:
        return ""


def restore(zip_path: Path, progress: Optional[Progress] = None, dest: Optional[Path] = None) -> RestoreResult:
    """Merge a backup into the data folder. A job already here is replaced only if the backup's copy is newer."""
    dest = Path(dest or base_dir())
    added = updated = kept = other = 0
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith("/") and n != "backup.json"]
        if not any(n.startswith("Jobs/") or n in TOP_FILES for n in names):
            raise ValueError("This is not a backup made by Image Resize & Share.")
        # decide per job folder
        jobs = {}
        for n in names:
            parts = n.split("/")
            if parts[0] == "Jobs" and len(parts) > 2:
                jobs.setdefault(parts[1], []).append(n)
        decision = {}
        for folder, members in jobs.items():
            here = dest / "Jobs" / folder / "job.json"
            if not here.is_file():
                decision[folder] = True
                added += 1
                continue
            theirs = f"Jobs/{folder}/job.json"
            new = _job_updated(z.read(theirs)) if theirs in members else ""
            old = _job_updated(here.read_bytes())
            if new and new > old:
                decision[folder] = True
                updated += 1
            else:
                decision[folder] = False
                kept += 1
        for k, n in enumerate(names):
            parts = n.split("/")
            target = dest / Path(*parts)
            if ".." in parts:
                continue
            if parts[0] == "Jobs" and len(parts) > 2:
                if not decision.get(parts[1]):
                    continue
            elif target.exists():
                continue                      # library files, presets …: never overwrite what is here
            else:
                other += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as srcf, open(target, "wb") as dstf:
                while True:
                    chunk = srcf.read(1 << 20)
                    if not chunk:
                        break
                    dstf.write(chunk)
            if progress:
                progress((k + 1) / len(names), n)
    return RestoreResult(added, updated, kept, other)


def copy_data(src: Path, dst: Path, progress: Optional[Progress] = None) -> int:
    """Copy the whole data folder to a new place (when moving it to OneDrive / a shared folder)."""
    import shutil
    src, dst = Path(src), Path(dst)
    files = [p for p in src.rglob("*") if p.is_file()]
    for k, f in enumerate(files):
        t = dst / f.relative_to(src)
        if t.exists():
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, t)
        if progress:
            progress((k + 1) / max(1, len(files)), f.name)
    return len(files)
