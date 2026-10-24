"""The AI engine wrapper, tested with a stand-in for Real-ESRGAN (a small script that prints progress
like the real program and can freeze or fail on purpose). Linux/macOS only: the stand-in is a script."""
import os
import sys
import threading
import time

import pytest
from PIL import Image

pytestmark = pytest.mark.skipif(os.name == "nt", reason="stand-in engine is a shell-run script")

FAKE = r'''#!{py}
import os, sys, time
from PIL import Image
a = sys.argv; mode = os.environ.get("FAKE_AI", "ok")
src, dst = a[a.index("-i") + 1], a[a.index("-o") + 1]
tile = "-t" in a
print("[0 Fake GPU]", file=sys.stderr, flush=True)
if mode == "fail_gpu":
    print("vkCreateInstance failed -9", file=sys.stderr, flush=True); sys.exit(255)
if mode == "oom_unless_tile" and not tile:
    print("vkAllocateMemory failed -2", file=sys.stderr, flush=True); sys.exit(255)
if mode == "hang" or (mode == "hang_unless_tile" and not tile):
    time.sleep(3600)
for i in range(6):
    time.sleep(0.25 if mode == "slow" else 0.02)
    print(f"{{i * 100 / 6:.2f}}%", file=sys.stderr, flush=True)
im = Image.open(src); im.resize((im.width * 4, im.height * 4)).save(dst)
'''


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    d = tmp_path / "realesrgan"
    (d / "models").mkdir(parents=True)
    (d / "models" / "realesrgan-x4plus.param").write_text("")
    exe = d / "realesrgan-ncnn-vulkan"
    exe.write_text(FAKE.format(py=sys.executable))
    exe.chmod(0o755)
    monkeypatch.setenv("REALESRGAN_DIR", str(d))
    from app.core import ai_upscale as A
    monkeypatch.setattr(A.RealEsrgan, "STALL_S", 1.5)

    def make(mode):
        monkeypatch.setenv("FAKE_AI", mode)
        return A.RealEsrgan()
    return make


IMG = Image.new("RGB", (120, 80), (10, 120, 200))


def test_progress_is_reported(engine):
    msgs = []
    out = engine("ok").upscale_to(IMG, (480, 320), progress=msgs.append)
    assert out.size == (480, 320) and any(m.endswith("%") for m in msgs)


@pytest.mark.parametrize("mode", ["hang_unless_tile", "oom_unless_tile"])
def test_retries_with_small_tiles(engine, mode):
    msgs = []
    out = engine(mode).upscale_to(IMG, (480, 320), progress=msgs.append)
    assert out.size == (480, 320) and any("smaller tiles" in m for m in msgs)


def test_a_frozen_engine_is_stopped(engine):
    from app.core import ai_upscale as A
    t0 = time.time()
    with pytest.raises(A.AIStalled):
        engine("hang").upscale_to(IMG, (480, 320))
    assert time.time() - t0 < 15


def test_cancel_stops_the_engine(engine):
    from app.core import ai_upscale as A
    flag = [False]
    threading.Timer(0.5, lambda: flag.__setitem__(0, True)).start()
    t0 = time.time()
    with pytest.raises(A.Cancelled):
        engine("slow").upscale_to(IMG, (480, 320), cancel=lambda: flag[0])
    assert time.time() - t0 < 3


def test_no_gpu_is_remembered(engine):
    e = engine("fail_gpu")
    with pytest.raises(RuntimeError):
        e.upscale_to(IMG, (480, 320))
    assert not e.available() and "Vulkan" in e.status_text()


def test_small_enlargement_of_a_big_picture_is_not_made_huge(engine):
    big = Image.new("RGB", (1200, 800), (90, 90, 90))
    out = engine("ok").upscale_to(big, (1800, 1200))         # 1.5x: the AI pass makes 2x, not 4x
    assert out.size[0] < 1200 * 4 and out.size[0] >= 1800


def test_upscale_falls_back_to_enhanced_when_frozen(engine):
    from app.core import upscale as up
    notes = []
    us = up.UpscaleSettings()
    out = up.upscale(IMG, us, engine("hang"), notes)
    assert out.size == up.target_size(IMG.size, us) and any("stopped responding" in n for n in notes)
