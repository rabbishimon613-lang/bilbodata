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
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageDraw
from ultralytics import YOLO
import stats as statsmod
from track import link_tracks, VEH_FIELDS

urllib3.disable_warnings()
HERE = os.path.dirname(os.path.abspath(__file__))

# --- sharding: split the camera list across N parallel runners (SHARD_COUNT) ---
# Each runner handles CAMS[SHARD_INDEX::SHARD_COUNT] and writes to its own files,
# so 20 machines never collide on the same CSV. SHARD_COUNT=1 == the classic path.
SHARD_INDEX = int(os.environ.get("PEDCOUNT_SHARD_INDEX", "0"))
SHARD_COUNT = int(os.environ.get("PEDCOUNT_SHARD_COUNT", "1"))
CAMS_FILE = os.environ.get("PEDCOUNT_CAMS", "cams.json")
FETCH_WORKERS = int(os.environ.get("PEDCOUNT_FETCH_WORKERS", "16"))

_ALL = json.load(open(os.path.join(HERE, CAMS_FILE)))
CAMS = _ALL[SHARD_INDEX::SHARD_COUNT] if SHARD_COUNT > 1 else _ALL
_sfx = "" if SHARD_COUNT == 1 else "_shard%d" % SHARD_INDEX
CSV_PATH = os.path.join(HERE, "counts%s.csv" % _sfx)
JSON_PATH = os.path.join(HERE, "counts%s.json" % _sfx)
VEH_PATH = os.path.join(HERE, "vehicles%s.csv" % _sfx)   # per-vehicle log (tracked)
PREVIEW_DIR = os.path.join(HERE, "preview")   # one annotated frame per cam, overwritten
os.makedirs(PREVIEW_DIR, exist_ok=True)

SAMPLE_INTERVAL = float(os.environ.get("PEDCOUNT_INTERVAL", "2"))   # seconds between frames (DOT refreshes ~1-2s)
MINUTE_SECONDS = int(os.environ.get("PEDCOUNT_MINUTE_SECONDS", "50"))  # sample this long, then write one row/cam
SAVE_PREVIEW = os.environ.get("PEDCOUNT_PREVIEW", "1") == "1"   # off at scale to save storage
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
http = urllib3.PoolManager(cert_reqs="CERT_NONE", maxsize=FETCH_WORKERS * 2)
model = YOLO("yolo11n.pt")


def grab(url):
    r = http.request("GET", url + "?t=" + str(time.time()), timeout=8.0)
    return Image.open(io.BytesIO(r.data)).convert("RGB")


def grab_all(cams):
    """Fetch every cam image in parallel (network is I/O-bound -> ~4x faster)."""
    def one(c):
        try:
            return c["id"], grab(c["img"])
        except Exception as e:
            return c["id"], None
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        return dict(ex.map(one, cams))


def bucket_color(crop):
    """Nearest coarse color of a vehicle. Sample the CENTER of the box only —
    the outer ring is mostly road / sky / foliage, which is what used to make
    'silver' and 'green' explode with background instead of paint."""
    a = np.asarray(crop)
    h, w = a.shape[:2]
    if h > 6 and w > 6:                      # keep the central 50% (the body)
        a = a[h // 4:h - h // 4, w // 4:w - w // 4]
    a = a.reshape(-1, 3).mean(axis=0)
    best = min(COLOR_REF, key=lambda k: np.linalg.norm(a - np.array(COLOR_REF[k])))
    return best


def analyze(img):
    """Return (counts, colors, annotated, dets). `dets` is the per-detection list
    the tracker links across frames: one dict per box with its pixel geometry."""
    big = img.resize((img.width * UPSCALE, img.height * UPSCALE)) if UPSCALE != 1 else img
    res = model.predict(np.array(big), classes=list(CLASSES), conf=CONF, verbose=False)[0]
    counts, colors, dets = Counter(), Counter(), []
    draw = ImageDraw.Draw(big)
    for b in res.boxes:
        cid = int(b.cls)
        label = CLASSES.get(cid)
        if not label:
            continue
        counts[label] += 1
        x1, y1, x2, y2 = map(int, b.xyxy[0])
        draw.rectangle([x1, y1, x2, y2], outline=(78, 161, 255), width=2)
        col = None
        if cid in (2, 5, 7):  # vehicles -> color tally + per-vehicle geometry
            col = bucket_color(big.crop((x1, y1, x2, y2)))
            colors[col] += 1
        dets.append({"box": (x1, y1, x2, y2), "cls": label, "color": col})
    return counts, colors, big, dets


def write_vehicles(rows):
    """Append per-vehicle records to vehicles.csv (header written once)."""
    new = not os.path.exists(VEH_PATH)
    with open(VEH_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "epoch", "cam_id", "name"] + VEH_FIELDS)
        w.writerows(rows)


def minute_pass(writer):
    """Sample every cam repeatedly for ~MINUTE_SECONDS, then write ONE averaged
    row per cam (avg objects in view during the minute). 1 minute = finest grain."""
    acc = {c["id"]: Counter() for c in CAMS}        # summed class counts over the minute
    col = {c["id"]: Counter() for c in CAMS}        # summed color tallies
    nsamp = {c["id"]: 0 for c in CAMS}              # frames captured this minute
    fbuf = {c["id"]: [] for c in CAMS}              # per-cam per-frame detections (for tracking)
    shots = 0
    t_start = time.time()
    t_end = t_start + MINUTE_SECONDS
    while time.time() < t_end:
        imgs = grab_all(CAMS)               # all cams fetched in parallel (~4x faster)
        for c in CAMS:
            img = imgs.get(c["id"])
            if img is None:
                continue
            try:
                counts, colors, annotated, dets = analyze(img)
                if SAVE_PREVIEW:
                    annotated.save(os.path.join(PREVIEW_DIR, c["id"] + ".jpg"), quality=70)
                acc[c["id"]].update(counts); col[c["id"]].update(colors)
                fbuf[c["id"]].append(dets)
                nsamp[c["id"]] += 1
            except Exception as e:
                print("  !", c["name"], e)
        shots += 1
        time.sleep(SAMPLE_INTERVAL)

    ts = dt.datetime.now().replace(second=0, microsecond=0).isoformat(timespec="minutes")
    snap = {}
    vehicles = []   # per-vehicle records for this pass (tracked, deduped)
    for c in CAMS:
        n = max(nsamp[c["id"]], 1)
        avg = {k: round(acc[c["id"]][k] / n) for k in CLASSES.values()}
        avgcol = {k: round(col[c["id"]][k] / n) for k in COLOR_REF}
        veh = avg["car"] + avg["truck"] + avg["bus"]
        writer.writerow([ts, c["id"], c["name"]] + [avg[k] for k in CLASSES.values()] +
                        [veh] + [avgcol[k] for k in COLOR_REF])
        snap[c["id"]] = {"classes": avg, "veh": veh, "ped": avg["person"], "samples": nsamp[c["id"]]}
        # link this cam's frames into individual vehicles for the metric/fleet/speed layers
        try:
            for t in link_tracks(fbuf[c["id"]]):
                epoch = round(t_start + t["f0"] * SAMPLE_INTERVAL, 1)   # ~2s wall-clock resolution
                vehicles.append([ts, epoch, c["id"], c["name"]] + [t[f] for f in VEH_FIELDS])
        except Exception as e:
            print("  ! track:", c["name"], e)
        print("%-30s cars=%-2d ped=%-2d  (%d frames)" %
              (c["name"][:30], avg["car"], avg["person"], nsamp[c["id"]]))
    json.dump({"ts": ts, "cams": snap}, open(JSON_PATH, "w"))
    write_vehicles(vehicles)
    if SHARD_COUNT == 1:            # single runner rolls up stats inline; sharded runs aggregate separately
        try:
            statsmod.compute()
        except Exception as e:
            print("  ! stats:", e)
    print("minute %s (%d cams, shard %d/%d) across ~%d rounds" %
          (ts, len(CAMS), SHARD_INDEX, SHARD_COUNT, shots))


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
