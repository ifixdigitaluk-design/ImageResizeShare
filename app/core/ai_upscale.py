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
import os
import subprocess
import sys
import tempfile
import threading
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
    def _run_x4(self, img: Image.Image, art: bool) -> Image.Image:
        assert self.exe is not None
        model = MODEL_ART if art else MODEL_PHOTO
        alpha = img.getchannel("A") if img.mode == "RGBA" else None
        rgb = img.convert("RGB")
        with tempfile.TemporaryDirectory(prefix="irs_ai_") as td:
            src = Path(td) / "in.png"
            dst = Path(td) / "out.png"
            rgb.save(src, "PNG", compress_level=1)
            cmd = [str(self.exe), "-i", str(src), "-o", str(dst), "-n", model,
                   "-s", "4", "-f", "png"]
            flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
            proc = subprocess.run(cmd, cwd=str(self.exe.parent), capture_output=True,
                                  text=True, timeout=900, creationflags=flags)
            if proc.returncode != 0 or not dst.exists():
                msg = (proc.stderr or proc.stdout or "").strip().splitlines()
                last = msg[-1] if msg else f"exit code {proc.returncode}"
                if "gpu" in last.lower() or "vkCreateInstance" in (proc.stderr or ""):
                    self.gpu_error = last
                raise RuntimeError(last)
            with Image.open(dst) as out:
                out.load()
                result = out.convert("RGB")
        if alpha is not None:  # transparency: enlarge the mask with Lanczos
            result.putalpha(alpha.resize(result.size, Image.Resampling.LANCZOS))
        return result

    def upscale_to(self, img: Image.Image, size: Tuple[int, int], art: bool = False) -> Image.Image:
        """Return an AI-enlarged image at least as large as `size` (or 16x max)."""
        # Cache by source content, so changing only the target size re-uses
        # the slow AI result and just re-samples it.
        key = (hashlib.md5(img.tobytes()).hexdigest(), img.size, img.mode, art)
        with self._lock:
            if self._cache_key == key and self._cache_img is not None:
                cur = self._cache_img
            else:
                cur = self._run_x4(img, art)
            need = max(size[0] / cur.width, size[1] / cur.height)
            if need > 1.0 and cur.width <= img.width * 4:
                # Second AI pass for very large enlargements (> 4x).
                cur = self._run_x4(cur, art)
            self._cache_key, self._cache_img = key, cur
            return cur


_engine: Optional[RealEsrgan] = None


def get_engine() -> RealEsrgan:
    global _engine
    if _engine is None:
        _engine = RealEsrgan()
    return _engine
