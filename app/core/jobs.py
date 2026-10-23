"""
Jobs, design library and business details – stored as plain files under
~/Documents/Image Resize & Share so they are easy to back up.

  Jobs/JOB-2026-0001 Sarah Khan/
      job.json            everything about the job (see wall.Job)
      design/             design versions (v1_…, v2_… upscaled, recoloured …)
      survey/             wall photos
      proofs/  mockups/   customer documents
      print/              print packages
  Library/                designs for the showroom (with library.json)
  business.json           your business details for proofs and sheets
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageOps

from app.core import wall as wl
from app.core.paths import base_dir, sub_dir

THUMB = 360


def jobs_dir() -> Path:
    return sub_dir("Jobs")


def library_dir() -> Path:
    return sub_dir("Library")


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", s or "").strip()
    return s[:40]


# ======================================================================
# Business details
# ======================================================================
BUSINESS_FIELDS = ("name", "phone", "email", "website", "address", "logo", "terms", "country_code")


def load_business() -> Dict[str, str]:
    try:
        d = json.loads((base_dir() / "business.json").read_text(encoding="utf-8"))
        return {k: str(d.get(k, "")) for k in BUSINESS_FIELDS}
    except Exception:
        return {k: "" for k in BUSINESS_FIELDS}


def save_business(d: Dict[str, str]) -> None:
    data = {k: d.get(k, "") for k in BUSINESS_FIELDS}
    logo = data.get("logo")
    if logo and Path(logo).is_file() and Path(logo).parent != base_dir():
        dst = base_dir() / ("logo" + Path(logo).suffix.lower())
        shutil.copyfile(logo, dst)
        data["logo"] = str(dst)
    (base_dir() / "business.json").write_text(json.dumps(data, indent=1), encoding="utf-8")


# ======================================================================
# Jobs
# ======================================================================
def next_job_no(year: Optional[int] = None) -> str:
    year = year or datetime.now().year
    best = 0
    for d in jobs_dir().iterdir():
        m = re.match(rf"JOB-{year}-(\d+)", d.name)
        if m:
            best = max(best, int(m.group(1)))
    return f"JOB-{year}-{best + 1:04d}"


def folder_for(job: wl.Job) -> Path:
    for d in jobs_dir().iterdir():
        if d.is_dir() and d.name.split(" ")[0] == job.job_no:
            return d
    name = job.job_no + (f" {_slug(job.customer)[:28].strip()}" if job.customer else "")
    d = jobs_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_job(customer: str = "", phone: str = "", room: str = "") -> wl.Job:
    j = wl.Job(job_no=next_job_no(), customer=customer, phone=phone, room=room)
    j.log("Job created")
    save_job(j)
    return j


def _replace(src: Path, dst: Path, tries: int = 8) -> None:
    """os.replace with a few retries: on Windows an antivirus or OneDrive can hold the file
    open for a moment."""
    import time
    for i in range(tries):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.15)


def save_job(job: wl.Job) -> Path:
    job.updated = datetime.now().isoformat(timespec="seconds")
    d = folder_for(job)
    tmp = d / "job.json.tmp"
    tmp.write_text(json.dumps(job.to_dict(), indent=1), encoding="utf-8")
    cur = d / "job.json"
    if cur.is_file():
        try:
            shutil.copyfile(cur, d / "job.json.bak")     # the last good copy
        except OSError:
            pass
    _replace(tmp, cur)
    return d


def load_job(folder: Path) -> wl.Job:
    """Load a job; if job.json is damaged (e.g. the PC lost power while saving) the last
    good copy is used."""
    folder = Path(folder)
    try:
        return wl.Job.from_dict(json.loads((folder / "job.json").read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        bak = folder / "job.json.bak"
        if bak.is_file():
            try:
                return wl.Job.from_dict(json.loads(bak.read_text(encoding="utf-8")))
            except Exception:
                pass
        raise ValueError(f"The job file in '{folder.name}' is damaged and could not be read.") from exc


@dataclass
class JobSummary:
    folder: Path
    job_no: str
    customer: str
    room: str
    status: str
    updated: str
    walls: str
    thumb: Optional[Path]
    phone: str = ""
    install_date: str = ""
    install_time: str = ""
    installer: str = ""


def list_jobs() -> List[JobSummary]:
    out = []
    for d in jobs_dir().iterdir():
        f = d / "job.json"
        if not f.is_file():
            continue
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(j, dict):
                raise ValueError
        except Exception:
            try:
                j = json.loads((d / "job.json.bak").read_text(encoding="utf-8"))
                if not isinstance(j, dict):
                    continue
            except Exception:
                continue
        walls = " + ".join(f"{w.get('width', 0):.2f}×{w.get('height', 0):.2f}" for w in j.get("walls", []))
        th = d / "thumb.jpg"
        out.append(JobSummary(d, j.get("job_no", d.name), j.get("customer", ""), j.get("room", ""),
                              j.get("status", ""), j.get("updated", ""), walls, th if th.is_file() else None,
                              j.get("phone", ""), j.get("install_date", ""), j.get("install_time", ""),
                              j.get("installer", "")))
    out.sort(key=lambda s: s.updated, reverse=True)
    return out


def add_design(job: wl.Job, image_or_path, note: str = "") -> str:
    """Store a design version in the job folder; returns the relative path."""
    d = folder_for(job) / "design"
    d.mkdir(exist_ok=True)
    n = len(list(d.glob("v*_*"))) + 1
    if isinstance(image_or_path, (str, Path)):
        src = Path(image_or_path)
        name = f"v{n}_{_slug(src.stem) or 'design'}{src.suffix.lower()}"
        shutil.copyfile(src, d / name)
        job.design_name = src.name
    else:
        img: Image.Image = image_or_path
        name = f"v{n}_{_slug(note) or 'design'}.png"
        img.save(d / name, "PNG", compress_level=4)
        job.design_name = note or name
    rel = f"design/{name}"
    job.design = rel
    job.design_kind = "image"
    job.log(f"Design v{n}: {note or job.design_name}")
    return rel


def add_file(job: wl.Job, sub: str, image: Image.Image, name: str, fmt: str = "JPEG") -> str:
    d = folder_for(job) / sub
    d.mkdir(exist_ok=True)
    p = d / name
    if fmt == "JPEG":
        image.convert("RGB").save(p, "JPEG", quality=92, subsampling=0)
    elif fmt == "PDF":
        image.convert("RGB").save(p, "PDF", resolution=150.0)
    else:
        image.save(p, fmt)
    return f"{sub}/{name}"


def save_thumb(job: wl.Job, img: Image.Image) -> None:
    t = img.convert("RGB").copy()
    t.thumbnail((THUMB, THUMB))
    t.save(folder_for(job) / "thumb.jpg", "JPEG", quality=85)


def duplicate_job(job: wl.Job, reason: str = "Reprint") -> wl.Job:
    """A new job with the same walls and design (reprints, other rooms)."""
    src = folder_for(job)
    k = job.copy()
    k.job_no = next_job_no()
    k.status = "Enquiry"
    k.history = []
    k.proof_version = 0
    k.proof_file = k.mockup_file = ""
    k.approved_by = k.approved_on = ""
    k.log(f"{reason} of {job.job_no}")
    dst = folder_for(k)
    for sub in ("design", "survey"):
        if (src / sub).is_dir():
            shutil.copytree(src / sub, dst / sub, dirs_exist_ok=True)
    if (src / "thumb.jpg").is_file():
        shutil.copyfile(src / "thumb.jpg", dst / "thumb.jpg")
    save_job(k)
    return k


def delete_job(folder: Path) -> Path:
    """Moves the job to Jobs/_deleted (never removes files)."""
    bin_ = jobs_dir() / "_deleted"
    bin_.mkdir(exist_ok=True)
    dst = bin_ / folder.name
    i = 1
    while dst.exists():
        dst = bin_ / f"{folder.name} ({i})"
        i += 1
    # a plain rename: all or nothing (shutil.move would fall back to copy + delete and could
    # leave half a job in each place when Windows has a file open)
    Path(folder).rename(dst)
    return dst


# ======================================================================
# Design library (showroom)
# ======================================================================
@dataclass
class LibraryItem:
    file: str                 # file name inside Library/
    name: str
    tags: List[str] = field(default_factory=list)
    added: str = ""
    kind: str = "mural"       # mural / pattern
    repeat_cm: float = 0.0
    notes: str = ""


def _lib_index() -> Path:
    return library_dir() / "library.json"


def load_library() -> List[LibraryItem]:
    try:
        data = json.loads(_lib_index().read_text(encoding="utf-8"))
        items = [LibraryItem(**{k: v for k, v in d.items() if k in LibraryItem.__dataclass_fields__}) for d in data]
        return [i for i in items if (library_dir() / i.file).is_file()]
    except Exception:
        return []


def save_library(items: List[LibraryItem]) -> None:
    _lib_index().write_text(json.dumps([asdict(i) for i in items], indent=1), encoding="utf-8")


def library_add(path: str | Path, name: str = "", tags: Optional[List[str]] = None, kind: str = "mural",
                repeat_cm: float = 0.0) -> LibraryItem:
    src = Path(path)
    items = load_library()
    dst = library_dir() / src.name
    i = 1
    while dst.exists():
        dst = library_dir() / f"{src.stem}_{i}{src.suffix}"
        i += 1
    shutil.copyfile(src, dst)
    item = LibraryItem(dst.name, name or src.stem.replace("_", " ").title(), [t.strip().lower() for t in tags or [] if t.strip()],
                       datetime.now().isoformat(timespec="seconds"), kind, repeat_cm)
    items.append(item)
    save_library(items)
    library_thumb(item)
    return item


def library_remove(item: LibraryItem) -> None:
    items = [i for i in load_library() if i.file != item.file]
    save_library(items)
    p = library_dir() / item.file
    bin_ = library_dir() / "_removed"
    bin_.mkdir(exist_ok=True)
    if p.is_file():
        shutil.move(str(p), str(bin_ / p.name))


def library_update(item: LibraryItem) -> None:
    items = [item if i.file == item.file else i for i in load_library()]
    save_library(items)


def library_thumb(item: LibraryItem, size: int = THUMB) -> Optional[Path]:
    tdir = library_dir() / ".thumbs"
    tdir.mkdir(exist_ok=True)
    t = tdir / (Path(item.file).stem + f"_{size}.jpg")
    src = library_dir() / item.file
    if t.is_file() and t.stat().st_mtime >= src.stat().st_mtime:
        return t
    try:
        with Image.open(src) as im:
            im.draft("RGB", (size * 2, size * 2))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((size, size))
            im.save(t, "JPEG", quality=85)
        return t
    except Exception:
        return None


def library_search(query: str = "", tag: str = "") -> List[LibraryItem]:
    q = query.strip().lower()
    out = []
    for i in load_library():
        if tag and tag.lower() not in i.tags:
            continue
        if q and q not in i.name.lower() and not any(q in t for t in i.tags):
            continue
        out.append(i)
    return out


def library_tags() -> List[str]:
    tags = set()
    for i in load_library():
        tags.update(i.tags)
    return sorted(tags)
