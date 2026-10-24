"""
Optional online upscaling through Replicate (https://replicate.com), using
the customer's own API token. Images are uploaded to Replicate for
processing, which costs a few cents per image.

* "Real-ESRGAN (faithful)"     – nightmareai/real-esrgan
* "Clarity (creative detail)"  – philz1337x/clarity-upscaler – invents extra
                                  texture like Lupa / Magnific "creative" modes.
"""
from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
import uuid
from typing import Callable, Dict, Optional, Tuple

from PIL import Image

API = "https://api.replicate.com/v1"

MODELS: Dict[str, Tuple[str, str]] = {   # label: (owner/name, kind)
    "Real-ESRGAN (faithful, fast)": ("nightmareai/real-esrgan", "esrgan"),
    "Clarity (creative detail, slower)": ("philz1337x/clarity-upscaler", "clarity"),
}


class CloudError(Exception):
    pass


Opener = Callable[..., object]


def _req(method: str, url: str, token: str, data: Optional[bytes] = None, headers: Optional[dict] = None,
         opener: Opener = urllib.request.urlopen, timeout: float = 120.0) -> dict:
    h = {"Authorization": f"Bearer {token}", "User-Agent": "ImageResizeShare/3"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with opener(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("detail", str(e))
        except Exception:
            msg = str(e)
        if e.code == 401:
            msg = "The Replicate token was not accepted. Check it in Settings → Online upscaling."
        elif e.code == 402:
            msg = "Your Replicate account needs billing set up (Replicate → Account → Billing)."
        raise CloudError(msg) from None
    except urllib.error.URLError as e:
        raise CloudError(f"Could not reach Replicate ({e.reason}). Check the internet connection.") from None
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except ValueError:
        raise CloudError("Unexpected answer from Replicate.") from None


def _download(url: str, opener: Opener = urllib.request.urlopen, timeout: float = 300.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ImageResizeShare/3"})
    try:
        with opener(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        raise CloudError(f"Could not download the result: {e}") from None


def check_token(token: str, opener: Opener = urllib.request.urlopen) -> str:
    d = _req("GET", f"{API}/account", token, opener=opener, timeout=20)
    return d.get("username") or d.get("name") or "OK"


def _upload(img: Image.Image, token: str, opener: Opener) -> str:
    buf = io.BytesIO()
    img.convert("L" if img.mode == "L" else "RGB").save(buf, "PNG", compress_level=3)
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"content\"; filename=\"image.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + buf.getvalue() + f"\r\n--{boundary}--\r\n".encode()
    d = _req("POST", f"{API}/files", token, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"},
             opener=opener, timeout=300)
    url = (d.get("urls") or {}).get("get")
    if not url:
        raise CloudError("Upload to Replicate failed.")
    return url


def build_input(kind: str, image_url: str, factor: float, creativity: float, resemblance: float) -> dict:
    if kind == "clarity":
        return {"image": image_url, "scale_factor": max(1.0, min(4.0, factor)), "creativity": creativity,
                "resemblance": resemblance, "dynamic": 6, "num_inference_steps": 18,
                "prompt": "masterpiece, best quality, highres, sharp focus, detailed texture",
                "negative_prompt": "(worst quality, low quality, normal quality:2) JuggernautNegative-neg",
                "output_format": "png"}
    return {"image": image_url, "scale": int(max(2, min(10, round(factor)))), "face_enhance": False}


def upscale(img: Image.Image, token: str, model: str, factor: float = 2.0, creativity: float = 0.35,
            resemblance: float = 0.6, progress: Optional[Callable[[str], None]] = None,
            opener: Opener = urllib.request.urlopen, poll: float = 2.0, max_wait: float = 900.0) -> Image.Image:
    if not token:
        raise CloudError("Add your Replicate API token in Settings → Online upscaling first.")
    slug, kind = MODELS[model]
    say = progress or (lambda m: None)
    say("Contacting Replicate…")
    info = _req("GET", f"{API}/models/{slug}", token, opener=opener, timeout=30)
    version = (info.get("latest_version") or {}).get("id")
    if not version:
        raise CloudError(f"Model {slug} is not available.")
    say("Uploading the image…")
    url = _upload(img, token, opener)
    say("Upscaling online…")
    pred = _req("POST", f"{API}/predictions", token,
                json.dumps({"version": version, "input": build_input(kind, url, factor, creativity, resemblance)}).encode(),
                {"Content-Type": "application/json", "Prefer": "wait=55"}, opener=opener, timeout=90)
    t0 = time.time()
    while pred.get("status") not in ("succeeded", "failed", "canceled"):
        if time.time() - t0 > max_wait:
            raise CloudError("Online upscaling took too long.")
        time.sleep(poll)
        get = (pred.get("urls") or {}).get("get")
        if not get:
            raise CloudError("Lost track of the job on Replicate.")
        pred = _req("GET", get, token, opener=opener, timeout=60)
        say(f"Upscaling online… {pred.get('status', '')}")
    if pred.get("status") != "succeeded":
        raise CloudError(f"Replicate: {pred.get('error') or pred.get('status')}")
    out = pred.get("output")
    if isinstance(out, list):
        out = out[-1] if out else None
    if not out:
        raise CloudError("Replicate returned no image.")
    say("Downloading the result…")
    data = _download(out, opener)
    res = Image.open(io.BytesIO(data))
    res.load()
    return res.convert("RGB")


# ======================================================================
# Generic prediction (official models have no version id)
# ======================================================================
def run_model(slug: str, inp: dict, token: str, progress: Optional[Callable[[str], None]] = None,
              opener: Opener = urllib.request.urlopen, poll: float = 2.0, max_wait: float = 900.0,
              label: str = "Working online") -> Image.Image:
    say = progress or (lambda m: None)
    hdr = {"Content-Type": "application/json", "Prefer": "wait=55"}
    info = _req("GET", f"{API}/models/{slug}", token, opener=opener, timeout=30)
    version = (info.get("latest_version") or {}).get("id")
    if version and not info.get("is_official"):
        pred = _req("POST", f"{API}/predictions", token, json.dumps({"version": version, "input": inp}).encode(),
                    hdr, opener=opener, timeout=90)
    else:
        pred = _req("POST", f"{API}/models/{slug}/predictions", token, json.dumps({"input": inp}).encode(),
                    hdr, opener=opener, timeout=90)
    t0 = time.time()
    while pred.get("status") not in ("succeeded", "failed", "canceled"):
        if time.time() - t0 > max_wait:
            raise CloudError("The online job took too long.")
        time.sleep(poll)
        get = (pred.get("urls") or {}).get("get")
        if not get:
            raise CloudError("Lost track of the job on Replicate.")
        pred = _req("GET", get, token, opener=opener, timeout=60)
        say(f"{label}… {pred.get('status', '')}")
    if pred.get("status") != "succeeded":
        raise CloudError(f"Replicate: {pred.get('error') or pred.get('status')}")
    out = pred.get("output")
    if isinstance(out, list):
        out = out[-1] if out else None
    if not out:
        raise CloudError("Replicate returned no image.")
    say("Downloading the result…")
    data = _download(out, opener)
    res = Image.open(io.BytesIO(data))
    res.load()
    return res.convert("RGB")


OUTPAINT_MODEL = "black-forest-labs/flux-fill-pro"


def outpaint(img: Image.Image, mask: Image.Image, token: str, prompt: str = "",
             progress: Optional[Callable[[str], None]] = None, opener: Opener = urllib.request.urlopen,
             **kw) -> Image.Image:
    """Fill the white parts of `mask` (same size as `img`) with new, matching picture content."""
    if not token:
        raise CloudError("Add your Replicate API token in Jobs → Online Upscaling first.")
    say = progress or (lambda m: None)
    say("Uploading the picture…")
    img_url = _upload(img, token, opener)
    mask_url = _upload(mask.convert("L"), token, opener)
    say("Extending the design online…")
    inp = {"image": img_url, "mask": mask_url, "output_format": "png", "safety_tolerance": 2,
           "prompt_upsampling": False,
           "prompt": prompt or "seamless natural continuation of the same picture, same style, same lighting, "
                               "same colours, high detail"}
    return run_model(OUTPAINT_MODEL, inp, token, progress, opener, label="Extending the design online", **kw)
