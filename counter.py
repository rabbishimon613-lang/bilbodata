#!/usr/bin/env python3
"""Multi-class aggregate traffic counter for the Crown Heights DOT feeds.

AGGREGATE ONLY BY DESIGN:
  - counts objects by TYPE per frame (car/truck/bus/bike/moto/person)
  - color mix is a bucket tally, not tied to any individual vehicle
  - the annotated preview frame is OVERWRITTEN every pass; no per-vehicle
    crops are ever saved. Nothing here re-identifies or follows an individual.
"""
import json, time, csv, os, sys, io, urllib3, datetime as dt
from collections import Counter
import numpy as np
from PIL import Image, ImageDraw
from ultralytics import YOLO
import stats as statsmod

urllib3.disable_warnings()
HERE = os.path.dirname(os.path.abspath(__file__))
CAMS = json.load(open(os.path.join(HERE, "cams.json")))
CSV_PATH = os.path.join(HERE, "counts.csv")
JSON_PATH = os.path.join(HERE, "counts.json")
PREVIEW_DIR = os.path.join(HERE, "preview")   # one annotated frame per cam, overwritten
os.makedirs(PREVIEW_DIR, exist_ok=True)

SAMPLE_INTERVAL = float(os.environ.get("PEDCOUNT_INTERVAL", "2"))   # seconds between frames (DOT refreshes ~1-2s)
MINUTE_SECONDS = int(os.environ.get("PEDCOUNT_MINUTE_SECONDS", "50"))  # sample this long, then write one row/cam
CONF = 0.25
UPSCALE = 2
# COCO ids we care about -> friendly label
CLASSES = {0: "person", 1: "bike", 2: "car", 3: "moto", 5: "bus", 7: "truck"}
# coarse color buckets in RGB space (for aggregate color mix only)
COLOR_REF = {
    "red": (200, 40, 40), "blue": (40, 60, 200), "green": (40, 160, 60),
    "yellow": (220, 200, 40), "white": (235, 235, 235), "black": (25, 25, 25),
    "silver": (160, 160, 165),
}
http = urllib3.PoolManager(cert_reqs="CERT_NONE")
model = YOLO("yolo11n.pt")


def grab(url):
    r = http.request("GET", url + "?t=" + str(time.time()), timeout=8.0)
    return Image.open(io.BytesIO(r.data)).convert("RGB")


def bucket_color(crop):
    a = np.asarray(crop).reshape(-1, 3).mean(axis=0)
    best = min(COLOR_REF, key=lambda k: np.linalg.norm(a - np.array(COLOR_REF[k])))
    return best


def analyze(img):
    big = img.resize((img.width * UPSCALE, img.height * UPSCALE)) if UPSCALE != 1 else img
    res = model.predict(np.array(big), classes=list(CLASSES), conf=CONF, verbose=False)[0]
    counts, colors = Counter(), Counter()
    draw = ImageDraw.Draw(big)
    for b in res.boxes:
        cid = int(b.cls)
        label = CLASSES.get(cid)
        if not label:
            continue
        counts[label] += 1
        x1, y1, x2, y2 = map(int, b.xyxy[0])
        draw.rectangle([x1, y1, x2, y2], outline=(78, 161, 255), width=2)
        if cid in (2, 5, 7):  # vehicles -> aggregate color tally only
            colors[bucket_color(big.crop((x1, y1, x2, y2)))] += 1
    return counts, colors, big


def minute_pass(writer):
    """Sample every cam repeatedly for ~MINUTE_SECONDS, then write ONE averaged
    row per cam (avg objects in view during the minute). 1 minute = finest grain."""
    acc = {c["id"]: Counter() for c in CAMS}        # summed class counts over the minute
    col = {c["id"]: Counter() for c in CAMS}        # summed color tallies
    nsamp = {c["id"]: 0 for c in CAMS}              # frames captured this minute
    shots = 0
    t_end = time.time() + MINUTE_SECONDS
    while time.time() < t_end:
        for c in CAMS:
            try:
                counts, colors, annotated = analyze(grab(c["img"]))
                annotated.save(os.path.join(PREVIEW_DIR, c["id"] + ".jpg"), quality=70)
                acc[c["id"]].update(counts); col[c["id"]].update(colors)
                nsamp[c["id"]] += 1
            except Exception as e:
                print("  !", c["name"], e)
        shots += 1
        time.sleep(SAMPLE_INTERVAL)

    ts = dt.datetime.now().replace(second=0, microsecond=0).isoformat(timespec="minutes")
    snap = {}
    for c in CAMS:
        n = max(nsamp[c["id"]], 1)
        avg = {k: round(acc[c["id"]][k] / n) for k in CLASSES.values()}
        avgcol = {k: round(col[c["id"]][k] / n) for k in COLOR_REF}
        veh = avg["car"] + avg["truck"] + avg["bus"]
        writer.writerow([ts, c["id"], c["name"]] + [avg[k] for k in CLASSES.values()] +
                        [veh] + [avgcol[k] for k in COLOR_REF])
        snap[c["id"]] = {"classes": avg, "veh": veh, "ped": avg["person"], "samples": nsamp[c["id"]]}
        print("%-30s cars=%-2d ped=%-2d  (%d frames)" %
              (c["name"][:30], avg["car"], avg["person"], nsamp[c["id"]]))
    json.dump({"ts": ts, "cams": snap}, open(JSON_PATH, "w"))
    try:
        statsmod.compute()
    except Exception as e:
        print("  ! stats:", e)
    print("minute %s written across ~%d rounds" % (ts, shots))


def main():
    minute = "--minute" in sys.argv   # CI: one averaged minute then exit
    new = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "cam_id", "name"] + list(CLASSES.values()) +
                       ["veh_total"] + list(COLOR_REF))
        while True:
            minute_pass(w)
            f.flush()
            if minute:
                break
            print("-" * 46)


if __name__ == "__main__":
    main()
