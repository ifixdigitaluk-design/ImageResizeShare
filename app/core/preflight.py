"""Print-readiness checks run before a job is sent to print."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from app.core import production as pr
from app.core import units as u
from app.core import wall as wl

LEVEL_ORDER = {"error": 0, "warn": 1, "info": 2, "ok": 3}
APPROVED_STATES = {"Approved", "Printing", "Printed", "Installed", "Completed"}


@dataclass
class Check:
    key: str
    level: str          # ok / info / warn / error
    title: str
    detail: str = ""
    fix: str = ""       # upscale / fit_cover / auto_seams / proof / measure / design / gamut / bleed / scale


def run(job: wl.Job, source=None, preset: Optional[pr.OutputPreset] = None, risk: Optional[np.ndarray] = None,
        gamut_fraction: Optional[float] = None, job_dir: Optional[Path] = None) -> List[Check]:
    out: List[Check] = []
    preset = preset or pr.find_preset(job.output_preset)
    # 1. walls
    if job.run_width < 0.2 or job.run_height < 0.2:
        out.append(Check("walls", "error", "Wall size missing", "Enter the wall width and height, or measure "
                                                                "the wall from a photo.", "measure"))
    else:
        out.append(Check("walls", "ok", "Wall measured",
                         " + ".join(u.fmt_size(w.width, w.height) for w in job.walls)
                         + f" · area {u.fmt_area_both(job.wall_area())}"))
    # 2. design
    if source is None:
        out.append(Check("design", "error", "No design yet", "Choose a picture or a pattern for the wall.", "design"))
    else:
        # coverage
        rp = getattr(source, "rp", None)
        if rp is not None and not rp.covers(job.art_width, job.art_height):
            out.append(Check("cover", "warn", "Design does not cover the whole print area",
                             f"The background colour {job.placement.background} will show at the edges.", "fit_cover"))
        else:
            out.append(Check("cover", "ok", "Design covers the wall and bleed"))
        size = getattr(source, "size_px", None)
        if job.design_kind != "pattern" and size and job.placement.mode == "fill":
            from app.core.expand import crop_fraction
            cf = crop_fraction(size, job.art_width / job.art_height)
            if cf > 0.15:
                out.append(Check("crop", "warn", f"Filling the wall cuts off {cf * 100:.0f}% of the design",
                                 "The design is a different shape from the wall. Expand it to add picture at the "
                                 "edges instead of cutting it.", "expand"))
        # resolution
        ppi = float(getattr(source, "ppi", 0.0))
        lvl, txt = wl.ppi_quality(ppi, job.view_distance)
        out.append(Check("ppi", {"excellent": "ok", "good": "ok", "low": "warn"}[lvl], "Print resolution", txt,
                         "upscale" if lvl == "low" else ""))
    # 3. panels
    panels = wl.compute_panels(job)
    issues = wl.panel_issues(job, panels)
    errs = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level == "warn"]
    if errs:
        out.append(Check("panels", "error", "Panels don't fit the media", " ".join(i.text for i in errs), "auto_seams"))
    else:
        widths = sorted({round(p.width * 100, 1) for p in panels})
        out.append(Check("panels", "ok", f"{len(panels)} panel{'s' if len(panels) != 1 else ''}",
                         f"{', '.join(str(w) for w in widths)} cm wide · {job.art_height * 100:.1f} cm long · "
                         f"media {job.panels.media_width * 100:.0f} cm"))
    for i in warns:
        out.append(Check("panel_warn", "warn", "Panel layout", i.text, "auto_seams"))
    # panel file size: each panel is made in memory
    too_big = pr.panel_too_big_text(job, preset)
    if too_big:
        out.append(Check("panel_px", "error", "Panels too big for this preset", too_big))
    else:
        pw, ph = pr.biggest_panel(job, preset)
        if pw * ph > pr.WARN_PANEL_PX:
            out.append(Check("panel_px", "warn", "Very big panel files",
                             f"The biggest panel is {pw:,} × {ph:,} px ({pw * ph / 1e6:,.0f} MP). It needs "
                             "several GB of memory and takes a while; a lower DPI or 50 % scale preset is lighter."))
    if job.uneven and job.panels.trim_to_shape:
        shaped = [w.name for w in job.walls if w.shaped]
        out.append(Check("shape", "info", "Panels cut to the wall shape",
                         ("Shaped wall: " + ", ".join(shaped) + ". " if shaped else "") +
                         "Each panel is only as long as the wall needs plus bleed. Trim along slopes, stair lines "
                         "and arches on site."))
    # 4. seams vs detail / faces
    seams = wl.current_seams(job)
    if risk is not None and len(risk) and seams:
        step = job.art_width / max(1, len(risk) - 1)
        worst_face, worst_detail = [], []
        for s in seams:
            a = max(0, int((s - job.panels.overlap / 2) / step))
            b = min(len(risk) - 1, int((s + job.panels.overlap / 2) / step) + 1)
            r = float(np.max(risk[a:b + 1])) if b >= a else 0.0
            if r >= 3.0:
                worst_face.append(s)
            elif r >= 1.1:
                worst_detail.append(s)
        if worst_face:
            out.append(Check("seams", "error", "A seam cuts through a face",
                             f"{len(worst_face)} seam(s). Use 'Place seams safely' to move them.", "auto_seams"))
        elif worst_detail:
            out.append(Check("seams", "warn", "A seam crosses fine detail",
                             f"{len(worst_detail)} seam(s) cross busy areas (text, patterns). Moving them makes the "
                             "joins invisible.", "auto_seams"))
        else:
            out.append(Check("seams", "ok", "Seams avoid faces and fine detail"))
    # 5. bleed
    b = min(job.panels.bleed_top, job.panels.bleed_bottom, job.panels.bleed_left, job.panels.bleed_right)
    if b < 0.02:
        out.append(Check("bleed", "warn", "Very little bleed",
                         f"Smallest bleed is {b * 100:.1f} cm. Walls are rarely square – 3 to 5 cm is safer.", "bleed"))
    else:
        out.append(Check("bleed", "ok", f"Bleed {b * 100:.0f} cm or more on every side"))
    # 6. colour
    if gamut_fraction is not None:
        if gamut_fraction > 0.05:
            out.append(Check("gamut", "warn", "Some colours can't be printed exactly",
                             f"{gamut_fraction * 100:.0f}% of the design is outside the printer's colours "
                             "(shown in magenta in Colour → Print check).", "gamut"))
        else:
            out.append(Check("gamut", "ok", "Colours are printable",
                             f"{gamut_fraction * 100:.1f}% outside the printer's range"))
    # 7. approval
    if job.status in APPROVED_STATES or job.approved_by:
        who = f" by {job.approved_by}" if job.approved_by else ""
        out.append(Check("approval", "ok", f"Proof approved{who}", job.approved_on or ""))
    else:
        out.append(Check("approval", "warn", "Customer hasn't approved a proof",
                         "Send a proof and record the approval before printing.", "proof"))
    # 8. output size / disk
    est = pr.estimate_bytes(job, preset)
    ppm = preset.dpi * preset.scale / u.M_PER_IN
    biggest = max((p.width * ppm * p.height * ppm for p in panels), default=0)
    if biggest > 400e6:
        out.append(Check("mp", "warn", "Very large panel files",
                         f"Biggest panel is {biggest / 1e6:.0f} MP. Use a 50 % scale preset if your RIP allows it.",
                         "scale"))
    if job_dir is not None:
        try:
            free = shutil.disk_usage(job_dir).free
            if est > free * 0.9:
                out.append(Check("disk", "error", "Not enough disk space",
                                 f"About {est / 1e9:.1f} GB needed, {free / 1e9:.1f} GB free."))
        except Exception:
            pass
    out.append(Check("output", "info", f"Output: {preset.name}",
                     f"{preset.fmt} · {preset.colour} · {preset.dpi} dpi"
                     f"{' · ' + str(int(preset.scale * 100)) + ' % scale' if preset.scale != 1 else ''}"
                     f" · about {max(1, est // 1_000_000)} MB"))
    out.sort(key=lambda c: LEVEL_ORDER[c.level])
    return out


def counts(checks: List[Check]):
    return (sum(c.level == "error" for c in checks), sum(c.level == "warn" for c in checks))


def report_text(checks: List[Check], job: wl.Job) -> str:
    sym = {"ok": "✓", "info": "i", "warn": "!", "error": "✗"}
    lines = [f"PREFLIGHT  {job.job_no}  {job.customer}", "-" * 60]
    for c in checks:
        lines.append(f"[{sym[c.level]}] {c.title}" + (f" – {c.detail}" if c.detail else ""))
    e, w = counts(checks)
    lines.append("-" * 60)
    lines.append(f"{e} problem(s), {w} warning(s)")
    return "\n".join(lines) + "\n"
