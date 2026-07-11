#!/usr/bin/env python3
"""Live evaluation room for the Academy tab.

Two feeds, refreshed continuously and published (via publish_training's
`git add training`) to bilbodata.vercel.app:

  live[]   — the FRESHEST vehicles the harvester just banked, each run through
             the CURRENT street student RIGHT NOW: make guess with the top-3
             confidence spread, plus the vehicle's colour, type and size. This
             is the "being evaluated right now" window — it moves with traffic.

  graded[] — the same student run on close-ups the TEACHER already named
             (badge-verified). Shows "teacher said X · student thinks Y
             (Z% sure)" and whether it got it right — a live report card.

The guesser is the street student (mmr/make_student.pt): MobileNetV3-small
fine-tuned only on badge-verified NYC crops, six makes so far. We use it, not
the raw VMMRdb textbook model, because it is the one that actually learned OUR
cameras — it is honestly uncertain (~50% on six makes vs 17% chance) instead
of collapsed-confident. Exact model naming is still in the textbook, so we
don't assert it here.

Polite by construction: MobileNetV3-small forward on ~12 small crops every
few seconds, single thread, nice 19. The governor pins it to the E-cores.
Never trains, never touches worker files — read + publish only.
"""
import io, json, os, sys, time
import numpy as np
import torch, torch.nn as nn
from torchvision import models, transforms
from PIL import Image

try: os.nice(19)                     # best-effort; the governor also floors us
except OSError: pass
torch.set_num_threads(1)

ROOT = "/Volumes/EOS_DIGITAL/bilbodata"
MMR, TR = f"{ROOT}/mmr", f"{ROOT}/training"
CROPS_META = f"{MMR}/crops_meta.jsonl"
MAKE_LABELS = f"{MMR}/make_labels.jsonl"
STUDENT = f"{MMR}/make_student.pt"      # the street student (real, uncertain)
OUT = f"{TR}/live_eval.json"
N_LIVE, N_GRADED = 6, 6

TF = transforms.Compose([
    transforms.Resize((224, 224)), transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])


# ---------- model ----------
_model = {"mtime": None, "net": None, "classes": None}

def load_student():
    """(Re)load the student whenever its checkpoint changes on disk, so the
    guesses on screen track the model as it actually studies."""
    try:
        mt = os.path.getmtime(STUDENT)
    except OSError:
        return None, None
    if mt != _model["mtime"]:
        try:
            ck = torch.load(STUDENT, map_location="cpu")
            classes = ck["classes"]
            net = models.mobilenet_v3_small(weights=None)
            net.classifier[3] = nn.Linear(net.classifier[3].in_features, len(classes))
            net.load_state_dict(ck["state"]); net.eval()
            _model.update(mtime=mt, net=net, classes=classes)
        except Exception:
            return _model["net"], _model["classes"]   # mid-write; keep old
    return _model["net"], _model["classes"]


def norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())

@torch.no_grad()
def predict(net, classes, im, k=3):
    """Top-k make guesses with confidence %. classes are display-ready
    ('Toyota', 'Mercedes-Benz', …). k is clamped to the number of classes."""
    p = torch.softmax(net(TF(im).unsqueeze(0))[0], 0)
    vals, idx = torch.topk(p, min(k, len(classes)))
    return [{"label": classes[i], "pct": round(v * 100, 1)}
            for v, i in zip(vals.tolist(), idx.tolist())]


# ---------- colour ----------
COLORS = [  # (name, hex) chromatic anchors, matched by hue+value in HSV
    ("red", "#c0392b"), ("orange", "#d35400"), ("gold", "#c9a227"),
    ("yellow", "#e1c340"), ("green", "#2e7d4f"), ("teal", "#1f8a8a"),
    ("blue", "#2d5fa8"), ("navy", "#1f2f5c"), ("purple", "#6b4b8a"),
    ("maroon", "#6e2b2b"), ("brown", "#6b4a2b"), ("burgundy", "#7b2233"),
]

def color_of(im):
    """Read the vehicle's dominant colour from its central body region.

    Returns (name, hex, mono) — mono True on a greyscale / IR feed, where we
    report a tone (white … black) instead of a colour, honestly.
    """
    w, h = im.size
    box = im.crop((int(w * .2), int(h * .18), int(w * .8), int(h * .72)))
    a = np.asarray(box.resize((48, 48))).astype(np.float32) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx = np.maximum(np.maximum(r, g), b); mn = np.minimum(np.minimum(r, g), b)
    v = mx; s = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)
    # weight toward the more saturated, mid-bright body pixels (skip glare/shadow)
    wgt = (s > 0.12) & (v > 0.12) & (v < 0.97)
    med_rgb = np.median(a.reshape(-1, 3), axis=0)
    hexv = "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in med_rgb)
    sat_frac = float(wgt.mean())
    if sat_frac < 0.10:                      # essentially colourless -> a tone
        vv = float(np.median(v))
        name = ("black" if vv < .18 else "dark grey" if vv < .38 else
                "grey" if vv < .60 else "silver" if vv < .82 else "white")
        return name, hexv, True
    # chromatic: median hue over the coloured body pixels
    rr, gg, bb = r[wgt].mean(), g[wgt].mean(), b[wgt].mean()
    import colorsys
    hh, ss, vv = colorsys.rgb_to_hsv(rr, gg, bb)
    deg = hh * 360
    if   deg < 15 or deg >= 345: base = "red"
    elif deg < 40:  base = "orange"
    elif deg < 65:  base = "gold"
    elif deg < 80:  base = "yellow"
    elif deg < 160: base = "green"
    elif deg < 200: base = "teal"
    elif deg < 255: base = "blue"
    elif deg < 290: base = "purple"
    else:           base = "red"
    if vv < .30: base = {"red": "maroon", "orange": "brown", "blue": "navy"}.get(base, "dark " + base)
    hx = dict(COLORS).get(base, hexv)
    return base, hx, False


# ---------- crop sources ----------
def readable_recent(path, n, need_make=False):
    try:
        lines = open(path).readlines()[-400:]
    except OSError:
        return []
    rows = []
    for l in reversed(lines):
        try: r = json.loads(l)
        except Exception: continue
        if not os.path.exists(r.get("file", "")): continue
        if need_make and not (r.get("verdict") == "labeled" and r.get("make")): continue
        if not need_make and r.get("h", 0) < 90: continue
        rows.append(r)
    return rows

def thumb(src, dst, px=300):
    im = Image.open(src).convert("RGB")
    disp = im.copy(); disp.thumbnail((px, px)); disp.save(dst, quality=84)
    return im


def build():
    net, classes = load_student()
    if net is None:
        return None
    cycle = int(time.time())
    # ---- live: freshest wild vehicles, one per camera for variety ----
    live, seen_cam = [], set()
    for r in readable_recent(CROPS_META, 60):
        cam = r.get("cam", "")
        if cam in seen_cam: continue
        seen_cam.add(cam)
        try:
            im = thumb(r["file"], f"{TR}/eval_live_{len(live)}.jpg")
        except Exception:
            continue
        top = predict(net, classes, im)
        cname, chex, mono = color_of(im)
        live.append({
            "i": len(live), "cam": cam, "cls": r.get("cls", "car"),
            "h": r.get("h"), "ts": r.get("ts"),
            "color": cname, "hex": chex, "mono": mono,
            "top": top})
        if len(live) >= N_LIVE: break
    # ---- graded: teacher-named close-ups, student vs teacher ----
    # Prefer teacher makes that are inside the student's current syllabus, so
    # the report card is a fair fight; still note the teacher's model name.
    syllabus = {norm(c) for c in classes}
    rows = readable_recent(MAKE_LABELS, 300, need_make=True)
    rows.sort(key=lambda r: norm(r["make"]) not in syllabus)   # in-syllabus first
    graded, seen_make = [], set()
    for r in rows:
        tmake = r["make"]
        if tmake in seen_make: continue
        seen_make.add(tmake)
        try:
            im = thumb(r["file"], f"{TR}/eval_grade_{len(graded)}.jpg")
        except Exception:
            continue
        top = predict(net, classes, im)
        in_syllabus = norm(tmake) in syllabus
        correct = in_syllabus and norm(top[0]["label"]) == norm(tmake)
        graded.append({
            "i": len(graded),
            "teacher_make": tmake, "teacher_model": r.get("model"),
            "student": top[0], "top": top,
            "in_syllabus": in_syllabus, "correct": correct})
        if len(graded) >= N_GRADED: break

    scored = [g for g in graded if g["in_syllabus"]]
    hit = sum(1 for g in scored if g["correct"])
    return {
        "ts": cycle,
        "classes": classes,
        "student_mtime": int(_model["mtime"] or 0),
        "live": live,
        "graded": graded,
        "graded_score": {"hit": hit, "n": len(scored)},
    }


def main():
    once = "--once" in sys.argv
    os.makedirs(TR, exist_ok=True)
    while True:
        try:
            data = build()
            if data:
                tmp = OUT + ".tmp"
                json.dump(data, open(tmp, "w"))
                os.replace(tmp, OUT)
                print(f"[live_eval] {time.strftime('%H:%M:%S')} "
                      f"live={len(data['live'])} graded={data['graded_score']}", flush=True)
        except Exception as e:
            print(f"[live_eval] error: {e}", flush=True)
        if once:
            break
        time.sleep(9)


if __name__ == "__main__":
    main()
