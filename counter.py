#!/usr/bin/env python3
"""Vehicle traffic counter for the NYC DOT feeds.

SOLID-RECOGNITION build (2026-07):
  - VEHICLES ONLY (car/truck/bus/moto). Pedestrians/bikes are not counted: the
    same weak detector can't resolve ~10px people reliably, so we don't pretend.
  - NO colour, NO appearance fingerprint, NO cross-camera re-identification.
    Nothing here follows or re-identifies an individual vehicle between cameras.
  - STALE-FRAME GUARD: the DOT webcam endpoint sometimes serves a frozen/cached
    frame for minutes. Every fetched frame is content-hashed; a frame identical
    to the camera's previous one is a duplicate and is DROPPED (not re-counted),
    and a reading tallies how many samples were fresh vs stale so a frozen camera
    is visible instead of silently logged as live.
  - each reading carries an honest reliability signal: frame BRIGHTNESS + a
    day/night `lit` flag (night badly undercounts) and the fresh/stale sample
    counts.
  - the annotated preview frame is OVERWRITTEN every pass; no per-vehicle crops
    are ever saved.
"""
import json, time, csv, os, sys, io, hashlib, urllib3, datetime as dt
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageDraw
from ultralytics import YOLO
import stats as statsmod
from track import link_tracks, VEH_FIELDS
import turso_sync

urllib3.disable_warnings()
HERE = os.path.dirname(os.path.abspath(__file__))

# --- sharding: split the camera list across N parallel runners (SHARD_COUNT) ---
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

SAMPLE_INTERVAL = float(os.environ.get("PEDCOUNT_INTERVAL", "2"))   # seconds between frames
MINUTE_SECONDS = int(os.environ.get("PEDCOUNT_MINUTE_SECONDS", "50"))  # sample this long, then write one row/cam
SAVE_PREVIEW = os.environ.get("PEDCOUNT_PREVIEW", "1") == "1"
MODEL_PATH = os.environ.get("PEDCOUNT_MODEL", "yolo11n.pt")   # committed weight; override for a stronger one
CONF = float(os.environ.get("PEDCOUNT_CONF", "0.25"))
UPSCALE = 2
# minute mean-luma below this => night; reading still logged but flagged lit=0.
DARK_THRESH = float(os.environ.get("PEDCOUNT_DARK_THRESH", "55"))
# COCO ids we keep -> friendly label. VEHICLES ONLY.
CLASSES = {2: "car", 3: "moto", 5: "bus", 7: "truck"}
VEH_KEYS = ["car", "moto", "bus", "truck"]
# reading schema (must match turso_sync.READINGS_COLS and stats.py)
COUNT_HEADER = (["ts", "cam_id", "name"] + VEH_KEYS +
                ["veh_total", "brightness", "lit", "samples", "stale"])

http = urllib3.PoolManager(cert_reqs="CERT_NONE", maxsize=FETCH_WORKERS * 2)
model = YOLO(MODEL_PATH)

_LAST_DIGEST = {}   # cam_id -> content hash of its last DISTINCT frame (persists across minutes)


def grab(url):
    r = http.request("GET", url + "?t=" + str(time.time()), timeout=8.0)
    digest = hashlib.md5(r.data).hexdigest()          # content hash -> stale-frame detection
    return Image.open(io.BytesIO(r.data)).convert("RGB"), digest


def grab_all(cams):
    """Fetch every cam image in parallel. Returns cam_id -> (image, digest) | None."""
    def one(c):
        try:
            return c["id"], grab(c["img"])
        except Exception:
            return c["id"], None
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        return dict(ex.map(one, cams))


def brightness(img):
    """Mean perceived luma (0-255) of the frame -- the low-light reliability signal."""
    a = np.asarray(img, dtype=np.float32)
    return float(a[..., 0].mean() * 0.299 + a[..., 1].mean() * 0.587 +
                 a[..., 2].mean() * 0.114)


def analyze(img):
    """Return (counts, annotated, dets). `dets` is the per-detection list the
    tracker links across frames: one dict per box (geometry only -- no colour,
    no crop, nothing that could re-identify a vehicle)."""
    big = img.resize((img.width * UPSCALE, img.height * UPSCALE)) if UPSCALE != 1 else img
    res = model.predict(np.array(big), classes=list(CLASSES), conf=CONF, verbose=False)[0]
    counts, dets = Counter(), []
    draw = ImageDraw.Draw(big)
    for b in res.boxes:
        label = CLASSES.get(int(b.cls))
        if not label:
            continue
        counts[label] += 1
        x1, y1, x2, y2 = map(int, b.xyxy[0])
        draw.rectangle([x1, y1, x2, y2], outline=(78, 161, 255), width=2)
        dets.append({"box": (x1, y1, x2, y2), "cls": label})
    return counts, big, dets


VEH_HEADER = ["ts", "epoch", "cam_id", "name"] + VEH_FIELDS


def rotate_if_stale_schema(path, header):
    """If an existing file's header doesn't match the current schema (e.g. the old
    person/colour/emb columns), archive it aside as *.legacy and start fresh — so
    new rows never misalign under an old header. Originals are preserved (the
    .legacy file + full git history)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        first = f.readline().strip()
    if first and first.split(",") != header:
        legacy = path + ".legacy"
        if not os.path.exists(legacy):
            os.rename(path, legacy)
            print("schema changed -> archived old %s to %s" %
                  (os.path.basename(path), os.path.basename(legacy)))
        else:
            os.remove(path)   # a legacy archive already exists; drop the stale file


def write_vehicles(rows):
    """Append per-vehicle records to vehicles.csv (header written once)."""
    new = not os.path.exists(VEH_PATH)
    with open(VEH_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(VEH_HEADER)
        w.writerows(rows)


def minute_pass(writer):
    """Sample every cam repeatedly for ~MINUTE_SECONDS, then write ONE averaged
    row per cam. Duplicate (stale) frames are dropped so a frozen camera can't
    inflate its sample count or be mistaken for live."""
    acc = {c["id"]: Counter() for c in CAMS}        # summed class counts over FRESH frames
    lum = {c["id"]: 0.0 for c in CAMS}              # summed brightness over FRESH frames
    nfresh = {c["id"]: 0 for c in CAMS}             # distinct (fresh) frames this minute
    nstale = {c["id"]: 0 for c in CAMS}             # duplicate frames dropped this minute
    fbuf = {c["id"]: [] for c in CAMS}              # per-cam per-frame detections (for tracking)
    shots = 0
    t_start = time.time()
    t_end = t_start + MINUTE_SECONDS
    while time.time() < t_end:
        imgs = grab_all(CAMS)
        for c in CAMS:
            got = imgs.get(c["id"])
            if got is None:
                continue
            img, digest = got
            if _LAST_DIGEST.get(c["id"]) == digest:   # frozen/cached -> drop, don't re-count
                nstale[c["id"]] += 1
                continue
            _LAST_DIGEST[c["id"]] = digest
            try:
                counts, annotated, dets = analyze(img)
                if SAVE_PREVIEW:
                    annotated.save(os.path.join(PREVIEW_DIR, c["id"] + ".jpg"), quality=70)
                acc[c["id"]].update(counts)
                lum[c["id"]] += brightness(img)
                fbuf[c["id"]].append(dets)
                nfresh[c["id"]] += 1
            except Exception as e:
                print("  !", c["name"], e)
        shots += 1
        time.sleep(SAMPLE_INTERVAL)

    ts = dt.datetime.now().replace(second=0, microsecond=0).isoformat(timespec="minutes")
    snap = {}
    count_rows = []
    vehicles = []
    for c in CAMS:
        nf = nfresh[c["id"]]
        n = max(nf, 1)
        avg = {k: round(acc[c["id"]][k] / n) for k in VEH_KEYS}
        veh = sum(avg[k] for k in VEH_KEYS)
        bright = round(lum[c["id"]] / n, 1) if nf else 0.0
        lit = 1 if (nf and bright >= DARK_THRESH) else 0
        row = ([ts, c["id"], c["name"]] + [avg[k] for k in VEH_KEYS] +
               [veh, bright, lit, nf, nstale[c["id"]]])
        writer.writerow(row)
        count_rows.append(row)
        snap[c["id"]] = {"classes": avg, "veh": veh, "bright": bright, "lit": lit,
                         "samples": nf, "stale": nstale[c["id"]],
                         "frozen": 1 if nf == 0 else 0}
        # link this cam's fresh frames into individual vehicles for the size layer
        try:
            for t in link_tracks(fbuf[c["id"]]):
                epoch = round(t_start + t["f0"] * SAMPLE_INTERVAL, 1)
                vehicles.append([ts, epoch, c["id"], c["name"]] +
                                [t[f] for f in VEH_FIELDS])
        except Exception as e:
            print("  ! track:", c["name"], e)
        flag = " FROZEN" if nf == 0 else ("" if not nstale[c["id"]] else " (%d stale)" % nstale[c["id"]])
        print("%-30s veh=%-3d lit=%d (%d fresh%s)" % (c["name"][:30], veh, lit, nf, flag))
    json.dump({"ts": ts, "cams": snap}, open(JSON_PATH, "w"))
    write_vehicles(vehicles)
    # Best-effort live mirror to Turso (no-op unless the DB env vars are set).
    turso_sync.sync_readings(count_rows)
    turso_sync.sync_vehicles(vehicles)
    if SHARD_COUNT == 1:
        try:
            statsmod.compute()
        except Exception as e:
            print("  ! stats:", e)
    print("minute %s (%d cams, shard %d/%d) across ~%d rounds" %
          (ts, len(CAMS), SHARD_INDEX, SHARD_COUNT, shots))


def main():
    minute = "--minute" in sys.argv   # CI: one averaged minute then exit
    rotate_if_stale_schema(CSV_PATH, COUNT_HEADER)     # migrate old-schema data files
    rotate_if_stale_schema(VEH_PATH, VEH_HEADER)
    new = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(COUNT_HEADER)
        while True:
            minute_pass(w)
            f.flush()
            if minute:
                break
            print("-" * 46)


if __name__ == "__main__":
    main()
