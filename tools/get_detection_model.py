"""
Download the furniture-detection model (YOLOX-S, Apache-2.0, OpenCV Zoo) and store its weights at
half size, as the app expects:  assets/models/object_detection_yolox_2022nov_fp16w.onnx

    pip install onnx
    python tools/get_detection_model.py

Only needed when the project was shared without the model file (to keep the upload small).
Without it the app still works; Measure just doesn't suggest furniture.

Or, if you have the three pieces model_part1.bin … model_part3.bin, put them in the project folder and run
    python tools/get_detection_model.py --join
"""
import sys
import urllib.request
from pathlib import Path

URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/object_detection_yolox/"
       "object_detection_yolox_2022nov.onnx")
ROOT = Path(__file__).resolve().parents[1]
SHA_START = "7f028a4bf76b2d4a"
DST = ROOT / "assets" / "models" / "object_detection_yolox_2022nov_fp16w.onnx"


def join() -> int:
    parts = sorted(ROOT.glob("model_part*.bin")) or sorted(Path.cwd().glob("model_part*.bin"))
    if not parts:
        print("No model_part*.bin files found next to the project.")
        return 1
    DST.parent.mkdir(parents=True, exist_ok=True)
    with open(DST, "wb") as out:
        for p in parts:
            out.write(p.read_bytes())
    import hashlib
    h = hashlib.sha256(DST.read_bytes()).hexdigest()
    print("Saved", DST, "sha256", h[:16], "OK" if h.startswith(SHA_START) else "(does not match – pieces missing?)")
    return 0


def main() -> int:
    if "--join" in sys.argv:
        return join()
    if DST.is_file():
        print("Already there:", DST)
        return 0
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper
    tmp = DST.with_name("yolox_original.onnx")
    if not tmp.is_file():
        print("Downloading", URL)
        urllib.request.urlretrieve(URL, tmp)
    m = onnx.load(str(tmp))
    g = m.graph
    inits, casts = [], []
    for t in g.initializer:
        a = numpy_helper.to_array(t)
        if a.dtype == np.float32 and a.size >= 16:
            inits.append(numpy_helper.from_array(a.astype(np.float16), t.name + "_fp16"))
            casts.append(helper.make_node("Cast", [t.name + "_fp16"], [t.name], to=TensorProto.FLOAT,
                                          name=t.name + "_cast"))
        else:
            inits.append(t)
    del g.initializer[:]
    g.initializer.extend(inits)
    nodes = list(g.node)
    del g.node[:]
    g.node.extend(casts + nodes)
    onnx.checker.check_model(m)
    onnx.save(m, str(DST))
    tmp.unlink()
    print("Saved", DST, f"({DST.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
