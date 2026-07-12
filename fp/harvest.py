#!/usr/bin/env python3
"""Tier-weighted, all-city harvester — the one perpetual thing.

Sweeps the FULL census (917 cams), weighted by tier: blues every sweep,
oranges every 2nd, purples on a rotating 6th. Dusk/night/rain sweeps widen
the net (those frames are the rare ones). Saves vehicle close-up crops gated
per tier, plus a crops_meta.jsonl manifest and a heartbeat status file.

Designed to run anywhere: the Mac, or a bounded GitHub Actions job
(--run-seconds). CPU only. Frames/crops go under --out (NEVER commit them to
main — the Actions workflow ships them to a Release and commits only the
manifest + telemetry).

  python3 fp/harvest.py --out fp_out --run-seconds 19000
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tiers import CROP_MIN_H, load_census, due_this_sweep  # noqa: E402

CLS = {2: "car", 3: "moto", 5: "bus", 7: "truck"}
CONF = 0.40
PAD = 0.12
PARKED_IOU = 0.60
MAX_PER_CAM = 6
MIN_SHARP = {"blue": 45.0, "orange": 30.0, "purple": 22.0}
NIGHT_BRIGHTNESS = 60  # mean pixel value below this = night ("lit" flag off)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48]


def fetch(cam_id):
    # curl, not urllib: python SSL is broken on the Mac and curl is everywhere
    url = f"https://webcams.nyctmc.org/api/cameras/{cam_id}/image?t={int(time.time())}"
    p = subprocess.run(["curl", "-sk", "--max-time", "15", url], capture_output=True)
    return p.stdout if p.returncode == 0 else b""


def raining_now():
    """Open-Meteo current precipitation for NYC — free, keyless, best-effort."""
    try:
        p = subprocess.run(
            ["curl", "-sk", "--max-time", "10",
             "https://api.open-meteo.com/v1/forecast?latitude=40.71&longitude=-74.0&current=precipitation"],
            capture_output=True, timeout=15)
        return json.loads(p.stdout)["current"]["precipitation"] > 0.1
    except Exception:
        return False


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix = max(0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.environ.get("FP_OUT", "fp_out"),
                    help="output root for crops/ + crops_meta.jsonl + status")
    ap.add_argument("--run-seconds", type=int, default=0,
                    help="exit cleanly after this long (0 = forever)")
    ap.add_argument("--sleep", type=int, default=45, help="pause between sweeps")
    ap.add_argument("--model", default="yolo11s.pt")
    ap.add_argument("--tiers", default="blue,orange,purple",
                    help="comma list; e.g. 'blue' to watch only the readers")
    args = ap.parse_args()

    import cv2
    import numpy as np
    from ultralytics import YOLO

    want = set(args.tiers.split(","))
    cams = [c for c in load_census() if c["tier"] in want]
    for c in cams:
        c["slug"] = slug(c["name"])
    model = YOLO(args.model)
    os.makedirs(args.out, exist_ok=True)
    meta_path = os.path.join(args.out, "crops_meta.jsonl")
    status_path = os.path.join(args.out, "harvest_status.json")

    t0 = time.time()
    last_hash, last_boxes = {}, {}
    sweep = saved_total = 0
    by_tier = {"blue": 0, "orange": 0, "purple": 0}
    print(f"[fp.harvest] {len(cams)} cams in scope "
          f"({sum(1 for c in cams if c['tier']=='blue')} blue / "
          f"{sum(1 for c in cams if c['tier']=='orange')} orange / "
          f"{sum(1 for c in cams if c['tier']=='purple')} purple)", flush=True)

    while True:
        sweep += 1
        hour = time.localtime().tm_hour
        boost = hour >= 18 or hour <= 7 or (sweep % 20 == 1 and raining_now())
        todo = due_this_sweep(cams, sweep, night_boost=boost)
        live = saved_sweep = 0
        for cam in todo:
            raw = fetch(cam["id"])
            if len(raw) < 10000:  # offline placeholder / error
                continue
            h = hashlib.md5(raw).hexdigest()
            if last_hash.get(cam["id"]) == h:  # stale-frame guard
                continue
            last_hash[cam["id"]] = h
            img = cv2.imdecode(np.frombuffer(raw, "uint8"), cv2.IMREAD_COLOR)
            if img is None:
                continue
            live += 1
            lit = float(img.mean()) >= NIGHT_BRIGHTNESS
            try:
                r = model.predict(img, imgsz=1280 if img.shape[1] >= 1280 else 640,
                                  conf=CONF, device="cpu", verbose=False)[0]
            except Exception:
                continue
            H, W = img.shape[:2]
            min_h = CROP_MIN_H[cam["tier"]]
            cands = []
            for b in r.boxes:
                c = int(b.cls)
                if c not in CLS:
                    continue
                x1, y1, x2, y2 = (int(v) for v in b.xyxy[0].tolist())
                if (y2 - y1) < min_h or (x2 - x1) < int(min_h * 0.8):
                    continue
                cands.append((y2 - y1, (x1, y1, x2, y2), c, float(b.conf)))
            cands.sort(reverse=True)
            prev = last_boxes.get(cam["id"], [])
            kept, n = [], 0
            for bh, box, c, conf in cands:
                kept.append(box)
                if n >= MAX_PER_CAM:
                    continue
                if any(iou(box, pb) > PARKED_IOU for pb in prev):  # parked
                    continue
                x1, y1, x2, y2 = box
                px, py = int((x2 - x1) * PAD), int((y2 - y1) * PAD)
                crop = img[max(0, y1 - py):min(H, y2 + py),
                           max(0, x1 - px):min(W, x2 + px)]
                sharp = cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY),
                                      cv2.CV_64F).var()
                if sharp < MIN_SHARP[cam["tier"]]:
                    continue
                day = time.strftime("%Y-%m-%d")
                d = os.path.join(args.out, "crops", cam["slug"], day)
                os.makedirs(d, exist_ok=True)
                fn = os.path.join(d, f"{time.strftime('%H%M%S')}_{CLS[c]}_{bh}px_s{int(sharp)}_{n}.jpg")
                cv2.imwrite(fn, crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
                with open(meta_path, "a") as f:
                    f.write(json.dumps({
                        "file": os.path.relpath(fn, args.out), "cam": cam["slug"],
                        "cam_id": cam["id"], "tier": cam["tier"], "cls": CLS[c],
                        "h": bh, "sharp": round(sharp, 1), "conf": round(conf, 3),
                        "cam_w": W, "lit": lit, "ts": int(time.time())}) + "\n")
                n += 1
                saved_sweep += 1
                saved_total += 1
                by_tier[cam["tier"]] += 1
            last_boxes[cam["id"]] = kept
        json.dump({"sweep": sweep, "cams_in_scope": len(cams), "cams_due": len(todo),
                   "cams_live": live, "crops_this_sweep": saved_sweep,
                   "crops_total": saved_total, "by_tier": by_tier,
                   "night_boost": boost, "ts": int(time.time())},
                  open(status_path, "w"))
        print(f"[fp.harvest] sweep {sweep}: {len(todo)} due, {live} live, "
              f"+{saved_sweep} crops ({saved_total} total)", flush=True)
        if args.run_seconds and time.time() - t0 > args.run_seconds:
            print("[fp.harvest] bounded run complete", flush=True)
            return
        time.sleep(args.sleep)


if __name__ == "__main__":
    main()
