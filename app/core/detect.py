"""
Offline AI detectors (OpenCV DNN, run on the CPU):

* YOLOX-S (Apache-2.0, OpenCV Zoo)  – furniture in front of a wall: sofa, bed,
  TV, chair, table, plant …
* YuNet (MIT, OpenCV Zoo)           – faces, so panel seams never cut through one.

Both models ship in assets/models. If OpenCV or a model is missing the
functions return empty results instead of failing.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

from pathlib import Path

import numpy as np
from PIL import Image

from app.core.paths import resource_path

try:
    import cv2  # type: ignore
    CV_OK = True
except Exception:  # pragma: no cover
    cv2 = None
    CV_OK = False

# YOLOX-S with its weights stored at half size (18 MB instead of 36 MB); all maths still runs in
# full precision, results match the original model within 0.4 px.
YOLOX_FILE = "assets/models/object_detection_yolox_2022nov_fp16w.onnx"
YUNET_FILE = "assets/models/face_detection_yunet_2023mar.onnx"

COCO = ('person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat',
        'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog',
        'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella',
        'handbag', 'tie', 'suitcase', 'frisbee', 'skis', 'snowboard', 'sports ball', 'kite',
        'baseball bat', 'baseball glove', 'skateboard', 'surfboard', 'tennis racket', 'bottle',
        'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich', 'orange',
        'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch', 'potted plant', 'bed',
        'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard', 'cell phone',
        'microwave', 'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase', 'scissors',
        'teddy bear', 'hair drier', 'toothbrush')

# COCO class -> wall-plan item kind
FURNITURE = {"couch": "sofa", "bench": "sofa", "bed": "bed", "tv": "tv", "chair": "chair",
             "dining table": "table", "potted plant": "plant", "refrigerator": "cabinet",
             "clock": "other", "oven": "cabinet", "sink": "cabinet", "toilet": "other"}


@dataclass
class Detection:
    kind: str           # wall-plan kind (sofa, bed, …) or 'face'
    label: str          # model label
    score: float
    box: Tuple[float, float, float, float]   # x, y, w, h in image pixels


_lock = threading.Lock()
_yolox = None
_yunet = None


def available() -> bool:
    return CV_OK and resource_path(YOLOX_FILE).is_file()


def faces_available() -> bool:
    return CV_OK and resource_path(YUNET_FILE).is_file()


def _to_bgr(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGB"))
    return a[:, :, ::-1].copy()


# ----------------------------------------------------------------------
# YOLOX
# ----------------------------------------------------------------------
class _YoloX:
    def __init__(self, path: str):
        # read the file in Python: OpenCV can't open paths with non-English letters on Windows
        self.net = cv2.dnn.readNetFromONNX(np.frombuffer(Path(path).read_bytes(), np.uint8))
        self.size = 640
        strides = [8, 16, 32]
        grids, exp = [], []
        for s in strides:
            n = self.size // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            g = np.stack((xv, yv), 2).reshape(1, -1, 2)
            grids.append(g)
            exp.append(np.full((*g.shape[:2], 1), s))
        self.grids = np.concatenate(grids, 1)
        self.strides = np.concatenate(exp, 1)

    def __call__(self, rgb: np.ndarray, conf: float = 0.35, nms: float = 0.5):
        h, w = rgb.shape[:2]
        r = min(self.size / h, self.size / w)
        nw, nh = int(w * r), int(h * r)
        pad = np.full((self.size, self.size, 3), 114.0, dtype=np.float32)
        pad[:nh, :nw] = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR).astype(np.float32)
        blob = np.transpose(pad, (2, 0, 1))[None]
        self.net.setInput(blob)
        outs = self.net.forward(self.net.getUnconnectedOutLayersNames())
        dets = outs[0][0].copy()
        dets[:, :2] = (dets[:, :2] + self.grids[0]) * self.strides[0]
        dets[:, 2:4] = np.exp(dets[:, 2:4]) * self.strides[0]
        boxes = np.empty_like(dets[:, :4])
        boxes[:, 0] = dets[:, 0] - dets[:, 2] / 2
        boxes[:, 1] = dets[:, 1] - dets[:, 3] / 2
        boxes[:, 2:4] = dets[:, 2:4]
        scores = dets[:, 4:5] * dets[:, 5:]
        best = scores.max(axis=1)
        cls = scores.argmax(axis=1)
        keep = cv2.dnn.NMSBoxesBatched(boxes.tolist(), best.tolist(), cls.tolist(), conf, nms)
        out = []
        for i in np.array(keep).reshape(-1):
            x, y, bw, bh = boxes[i] / r
            out.append((COCO[int(cls[i])], float(best[i]), (float(x), float(y), float(bw), float(bh))))
        return out


def detect_furniture(img: Image.Image, conf: float = 0.35, max_side: int = 1280) -> List[Detection]:
    """Furniture and other items standing in front of a wall."""
    global _yolox
    if not available():
        return []
    small = img.convert("RGB")
    k = 1.0
    if max(small.size) > max_side:
        k = max(small.size) / max_side
        small = small.resize((round(small.width / k), round(small.height / k)), Image.Resampling.BILINEAR)
    with _lock:
        if _yolox is None:
            _yolox = _YoloX(str(resource_path(YOLOX_FILE)))
        raw = _yolox(np.asarray(small), conf=conf)
    out = []
    for label, score, (x, y, w, h) in raw:
        kind = FURNITURE.get(label)
        if kind:
            out.append(Detection(kind, label, score, (x * k, y * k, w * k, h * k)))
    return out


# ----------------------------------------------------------------------
# YuNet faces
# ----------------------------------------------------------------------
def detect_faces(img: Image.Image, score: float = 0.7, max_side: int = 2000) -> List[Detection]:
    global _yunet
    if not faces_available():
        return []
    small = img.convert("RGB")
    k = 1.0
    if max(small.size) > max_side:
        k = max(small.size) / max_side
        small = small.resize((round(small.width / k), round(small.height / k)), Image.Resampling.BILINEAR)
    bgr = _to_bgr(small)
    h, w = bgr.shape[:2]
    with _lock:
        if _yunet is None:
            buf = np.frombuffer(resource_path(YUNET_FILE).read_bytes(), np.uint8)
            _yunet = cv2.FaceDetectorYN.create("onnx", buf, np.array([], np.uint8), (w, h), score, 0.3, 5000)
        _yunet.setInputSize((w, h))
        _yunet.setScoreThreshold(score)
        _n, faces = _yunet.detect(bgr)
    out = []
    if faces is not None:
        for f in faces:
            x, y, fw, fh = (float(v) * k for v in f[:4])
            out.append(Detection("face", "face", float(f[-1]), (x, y, fw, fh)))
    return out


# ----------------------------------------------------------------------
# Seam risk across the artwork
# ----------------------------------------------------------------------
def seam_risk(render: Image.Image, art_width_m: float, step: float = 0.01,
              faces: Optional[List[Detection]] = None) -> Tuple[np.ndarray, List[Detection]]:
    """Risk of a visible seam for every `step` metres across the artwork.

    `render` is the whole artwork drawn at any resolution. Fine detail (text,
    patterns, eyes …) and faces score high; plain areas (sky, walls) low.
    """
    g = np.asarray(render.convert("L"), dtype=np.float32)
    gx = np.abs(np.diff(g, axis=1, prepend=g[:, :1]))
    gy = np.abs(np.diff(g, axis=0, prepend=g[:1, :]))
    energy = (gx + gy)
    col = energy.mean(axis=0)
    # columns crossing many strong vertical edges hide a seam fairly well, so
    # weight horizontal detail (gy) a bit more than vertical edges (gx)
    col = 0.4 * gx.mean(axis=0) + 0.6 * gy.mean(axis=0)
    ref = np.percentile(col, 95) if col.size else 1.0
    detail = np.clip(col / max(ref, 1e-6), 0, 1.5)
    # smooth over ~2 cm
    px_per_m = render.width / max(art_width_m, 1e-6)
    k = max(1, int(round(0.02 * px_per_m)))
    if k > 1:
        detail = np.convolve(detail, np.ones(k) / k, mode="same")
    if faces is None:
        faces = detect_faces(render)
    face_risk = np.zeros_like(detail)
    for f in faces:
        x, _y, w, _h = f.box
        a = max(0, int(x - 0.15 * w))
        b = min(len(face_risk), int(x + 1.15 * w) + 1)
        face_risk[a:b] = np.maximum(face_risk[a:b], 4.0)
    risk_px = detail + face_risk
    n = int(round(art_width_m / step)) + 1
    xs = np.linspace(0, len(risk_px) - 1, n)
    return np.interp(xs, np.arange(len(risk_px)), risk_px), faces
