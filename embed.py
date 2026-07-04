#!/usr/bin/env python3
"""Per-vehicle appearance FINGERPRINT + honest colour — the fix for
"everything is a grey sedan, so cross-camera speeds are noise."

At 352x240 a car is ~23px wide, so make/model is physically unreadable. What IS
recoverable is a compact appearance signature. Two pieces:

1. embed(crop) -> 64 numbers. A small pretrained CNN (MobileNetV3) turns the car
   crop into a 576-d feature, projected to 64-d by a FIXED random projection
   (Johnson-Lindenstrauss: preserves distances, needs no training) and L2-
   normalised. The SAME car seen at two cameras produces near-parallel vectors
   (cosine ~1); two different cars do not. This is what makes re-identification —
   and therefore speed — trustworthy, instead of matching by one colour word.

2. dominant_colour(crop) -> label. Proper HSV decision on the masked car body:
   dark->black, bright+washed->white, low-saturation->gray/silver by brightness,
   otherwise a real hue (red/orange/yellow/green/blue). Kills the silver blob.

Embeddings are for RECENT matching only (minutes/hours), so they live in the hot
log and are dropped from the forever-archive to keep it lean.
"""
import ssl
import numpy as np

ssl._create_default_https_context = ssl._create_unverified_context  # traffic-cam host certs

DIM = 64
_MODEL = None
_PROJ = None
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _load():
    global _MODEL, _PROJ
    if _MODEL is None:
        import torch
        from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
        m = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
        m.eval()
        _MODEL = m
        rng = np.random.RandomState(42)
        _PROJ = (rng.randn(576, DIM).astype(np.float32) / np.sqrt(576.0))
    return _MODEL, _PROJ


def _prep(crop):
    """crop: HxWx3 uint8 RGB -> 1x3x64x64 float tensor (ImageNet-normalised)."""
    import torch
    from PIL import Image
    if not isinstance(crop, np.ndarray):
        crop = np.asarray(crop)
    if crop.ndim != 3 or crop.shape[2] != 3 or crop.size == 0:
        return None
    img = Image.fromarray(crop.astype(np.uint8)).resize((64, 64))
    a = (np.asarray(img).astype(np.float32) / 255.0 - _MEAN) / _STD
    t = torch.from_numpy(a.transpose(2, 0, 1)[None]).float()
    return t


def embed(crop):
    """Return a 64-d float16 unit vector for the crop, or None if unusable."""
    import torch
    t = _prep(crop)
    if t is None:
        return None
    m, proj = _load()
    with torch.no_grad():
        f = m.avgpool(m.features(t)).flatten(1).numpy()[0]   # 576
    v = f @ proj                                             # 64
    n = np.linalg.norm(v)
    if n < 1e-6:
        return None
    return (v / n).astype(np.float16)


def to_hex(vec):
    return "" if vec is None else vec.astype(np.float16).tobytes().hex()


def from_hex(s):
    if not s:
        return None
    try:
        return np.frombuffer(bytes.fromhex(s), dtype=np.float16).astype(np.float32)
    except Exception:
        return None


def cosine(a, b):
    if a is None or b is None or a.shape != b.shape:
        return 0.0
    return float(np.dot(a, b))     # both already unit-norm


# ---------------------------------------------------------------- colour ----
def dominant_colour(crop):
    """Honest HSV colour of the car body (central region only)."""
    import colorsys
    a = np.asarray(crop).astype(np.float32)
    if a.ndim != 3 or a.size == 0:
        return None
    h, w = a.shape[:2]
    if h > 6 and w > 6:                         # central 50% = body, not road/sky
        a = a[h // 4:h - h // 4, w // 4:w - w // 4]
    r, g, b = (a[..., 0] / 255.0).mean(), (a[..., 1] / 255.0).mean(), (a[..., 2] / 255.0).mean()
    hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
    V, S = val * 255, sat
    if V < 55:
        return "black"
    if S < 0.18:                                # desaturated -> brightness decides
        if V > 200:
            return "white"
        if V > 120:
            return "silver"
        return "gray"
    H = hue * 360                               # real hue present
    if H < 20 or H >= 330:
        return "red"
    if H < 45:
        return "orange"
    if H < 70:
        return "yellow"
    if H < 170:
        return "green"
    if H < 255:
        return "blue"
    return "red"


if __name__ == "__main__":
    import numpy as np
    x = (np.random.rand(30, 24, 3) * 255).astype(np.uint8)
    v = embed(x)
    print("embed dim:", None if v is None else v.shape, "| colour:", dominant_colour(x))
