"""
AI super-resolution using Real-ESRGAN (ncnn / Vulkan build).

Real-ESRGAN rebuilds detail when enlarging, so a small photo can be made
2x-4x bigger and still look sharp. It runs on any Vulkan-capable GPU
(NVIDIA, AMD and Intel integrated graphics on most PCs from ~2016 onwards).

The executable + models live in a "realesrgan" folder next to the app
(build.bat downloads them automatically). If they are missing, or the PC
has no usable GPU, the app falls back to "Enhanced" upscaling.
"""
from __future__ import annotations

import hashlib
import math
import os
import subprocess
import sys
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

EXE_NAMES = ("realesrgan-ncnn-vulkan.exe", "realesrgan-ncnn-vulkan")
MODEL_PHOTO = "realesrgan-x4plus"
MODEL_ART = "realesrgan-x4plus-anime"


def _candidate_dirs() -> list[Path]:
    dirs = []
    env = os.environ.get("REALESRGAN_DIR")
    if env:
        dirs.append(Path(env))
    if getattr(sys, "frozen", False):
        dirs.append(Path(getattr(sys, "_MEIPASS", "")) / "realesrgan")
        dirs.append(Path(sys.executable).parent / "realesrgan")
    root = Path(__file__).resolve().parents[2]
    dirs += [root / "vendor" / "realesrgan", root / "realesrgan"]
    return dirs


class RealEsrgan:
    def __init__(self) -> None:
        self.exe: Optional[Path] = None
        self.gpu_error: Optional[str] = None
        self._lock = threading.Lock()
        self._cache_key: Optional[tuple] = None
        self._cache_img: Optional[Image.Image] = None
        self._cache2_key: Optional[tuple] = None
        self._cache2_img: Optional[Image.Image] = None
        for d in _candidate_dirs():
            for name in EXE_NAMES:
                p = d / name
                if p.is_file() and (d / "models" / f"{MODEL_PHOTO}.param").is_file():
                    self.exe = p
                    break
            if self.exe:
                break

    # ------------------------------------------------------------------
    def installed(self) -> bool:
        return self.exe is not None

    def available(self) -> bool:
        return self.exe is not None and self.gpu_error is None

    def status_text(self) -> str:
        if not self.exe:
            return "AI engine not installed"
        if self.gpu_error:
            return "AI needs a Vulkan GPU – not available on this PC"
        return "AI engine ready"

    # ------------------------------------------------------------------
    STALL_S = 90           # no word from the AI program for this long: it has stopped (GPU driver hang)
    MAX_S = 1800           # and never more than this for one pass

    def _run_x4(self, img: Image.Image, art: bool, progress=None, cancel=None) -> Image.Image:
        """One 4x pass. If the AI program stalls or runs out of GPU memory, it is tried once more
        with small work tiles (gentler on laptop graphics) before giving up."""
        try:
            return self._run_x4_once(img, art, progress, cancel, tile=0)
        except AIStalled:
            if progress:
                progress("The AI engine stopped responding – trying again with smaller tiles…")
            return self._run_x4_once(img, art, progress, cancel, tile=128)
        except RuntimeError as exc:
            if not _is_memory_error(str(exc)):
                raise
            if progress:
                progress("Not enough graphics memory – trying again with smaller tiles…")
            return self._run_x4_once(img, art, progress, cancel, tile=128)

    def _run_x4_once(self, img: Image.Image, art: bool, progress, cancel, tile: int) -> Image.Image:
        assert self.exe is not None
        model = MODEL_ART if art else MODEL_PHOTO
        alpha = img.getchannel("A") if img.mode == "RGBA" else None
        rgb = img if img.mode == "RGB" else img.convert("RGB")
        with tempfile.TemporaryDirectory(prefix="irs_ai_") as td:
            src = Path(td) / "in.png"
            dst = Path(td) / "out.png"
            rgb.save(src, "PNG", compress_level=1)
            cmd = [str(self.exe), "-i", str(src), "-o", str(dst), "-n", model, "-s", "4", "-f", "png"]
            if tile:
                cmd += ["-t", str(tile)]
            flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
            proc = subprocess.Popen(cmd, cwd=str(self.exe.parent), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=flags)
            lines: list = []
            last = [time.monotonic()]
            pct = [None]

            def reader():                       # the program prints "12.50%" as it works
                buf = b""
                while True:
                    ch = proc.stdout.read(1)
                    if not ch:
                        break
                    if ch in (b"\n", b"\r"):
                        line = buf.decode("utf-8", "replace").strip()
                        buf = b""
                        if line:
                            last[0] = time.monotonic()
                            m = re.match(r"^(\d+(?:[.,]\d+)?)%$", line)
                            if m:
                                pct[0] = float(m.group(1).replace(",", "."))
                            else:
                                lines.append(line)
                    else:
                        buf += ch
            t = threading.Thread(target=reader, daemon=True)
            t.start()
            t0 = time.monotonic()
            shown = None
            try:
                while proc.poll() is None:
                    time.sleep(0.2)
                    if cancel is not None and cancel():
                        raise Cancelled("Cancelled")
                    now = time.monotonic()
                    if now - last[0] > self.STALL_S or now - t0 > self.MAX_S:
                        raise AIStalled("The AI engine stopped responding")
                    if progress and pct[0] is not None and pct[0] != shown:
                        shown = pct[0]
                        progress(f"AI upscaling… {shown:.0f}%")
            except BaseException:
                _kill(proc)
                raise
            t.join(timeout=2)
            if proc.returncode != 0 or not dst.exists():
                text = "\n".join(lines)
                msg = [ln for ln in lines if ln.strip()]
                last_line = msg[-1] if msg else f"exit code {proc.returncode}"
                if "vkCreateInstance" in text or "invalid gpu" in text.lower() or "no vulkan" in text.lower():
                    self.gpu_error = last_line
                raise RuntimeError(last_line if not _is_memory_error(text) else "out of graphics memory: " + last_line)
            with Image.open(dst) as out:
                out.load()
                result = out.convert("RGB")
        if alpha is not None:  # transparency: enlarge the mask with Lanczos
            result.putalpha(alpha.resize(result.size, Image.Resampling.LANCZOS))
        return result

    def _acquire(self, progress, cancel) -> None:
        """One AI job at a time; say so while waiting, and allow cancelling."""
        told = False
        while not self._lock.acquire(timeout=0.3):
            if cancel is not None and cancel():
                raise Cancelled("Cancelled")
            if progress and not told:
                progress("Waiting for the AI engine (it is finishing another picture)…")
                told = True

    def upscale_to(self, img: Image.Image, size: Tuple[int, int], art: bool = False,
                   progress=None, cancel=None) -> Image.Image:
        """Return an AI-enlarged image close to `size` (up to 16x).

        One Real-ESRGAN pass gives 4x. For bigger enlargements (8x, 16x) the
        4x result is resized so that a second 4x pass lands right on the
        target, instead of making a giant 16x image and shrinking it.
        For a small enlargement of a big picture the input is made smaller first, so the AI never
        makes a picture much bigger than needed (that made it very slow, or run out of memory).
        Results are cached, so changing only the target size is fast.
        """
        # the 4x result needn't be more than twice the target size (and never smaller than it)
        k = min(1.0, max(size[0] / (2.0 * img.width), size[1] / (2.0 * img.height)))
        work = img if k >= 1.0 else img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))),
                                               Image.Resampling.LANCZOS, reducing_gap=3.0)
        key = (_fingerprint(work), work.size, work.mode, art)
        self._acquire(progress, cancel)
        try:
            if self._cache_key == key and self._cache_img is not None:
                cur = self._cache_img
            else:
                cur = self._run_x4(work, art, progress, cancel)
                self._cache_key, self._cache_img = key, cur
                self._cache2_key, self._cache2_img = None, None
            need = max(size[0] / cur.width, size[1] / cur.height)
            if need <= 1.0:
                return cur
            k2 = (key, tuple(size))
            if getattr(self, "_cache2_key", None) == k2 and self._cache2_img is not None:
                return self._cache2_img
            mid = (min(cur.width, max(1, math.ceil(size[0] / 4))),
                   min(cur.height, max(1, math.ceil(size[1] / 4))))
            inter = cur if mid == cur.size else cur.resize(mid, Image.Resampling.LANCZOS)
            if progress:
                progress("AI upscaling, second pass…")
            out = self._run_x4(inter, art, progress, cancel)
            self._cache2_key, self._cache2_img = k2, out
            return out
        finally:
            self._lock.release()


class Cancelled(Exception):
    """The user pressed Cancel."""


class AIStalled(RuntimeError):
    """The AI program stopped responding (usually a graphics driver problem)."""


def _is_memory_error(text: str) -> bool:
    t = text.lower()
    return "vkallocatememory" in t or "out of memory" in t or "vk_error_out_of_device_memory" in t \
        or "failed to allocate" in t


def _kill(proc) -> None:
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


def _fingerprint(img: Image.Image) -> str:
    """Identifies a picture for the cache without copying it all (tobytes of a big image is a full copy)."""
    h = hashlib.md5()
    step = max(1, 4_000_000 // max(1, img.width))
    for y in range(0, img.height, step):
        h.update(img.crop((0, y, img.width, min(img.height, y + step))).tobytes())
    return h.hexdigest()


_engine: Optional[RealEsrgan] = None


def get_engine() -> RealEsrgan:
    global _engine
    if _engine is None:
        _engine = RealEsrgan()
    return _engine
