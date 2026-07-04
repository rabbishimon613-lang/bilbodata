#!/usr/bin/env python3
"""Auto-calibration + metric body-typing — no per-intersection setup, works the
same on all 900+ cameras.

We can't read a badge on a 40px car, so we don't try. Instead we MEASURE.
Each fixed camera self-calibrates from its own fleet: the *median car* it sees
is the yardstick (a passenger car is ~6 ft wide / ~15 ft long everywhere in the
world). Once a camera knows how big a normal car looks in its frame, every other
vehicle can be sized relative to that — reliably telling apart:

    moto · sedan · SUV/minivan · pickup/large · box truck · bus

That is the honest, resolution-proof version of "make & model": vehicle *type*
by real footprint, not by reading chrome. It scales to the whole city because
the yardstick is discovered per-camera from the data, never hand-placed.

Reads the per-vehicle log(s) produced by track.py via the counter.
Writes calibration.json: per-camera scale + a citywide body-type histogram.
"""
import os, csv, glob, json, statistics as st
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "calibration.json")

CAR_WIDTH_FT = 6.0          # real-world width of a typical passenger car
MIN_CARS_TO_TRUST = 8       # a camera needs this many car sightings to self-calibrate

BODY_TYPES = ["moto", "sedan", "suv_van", "pickup_large", "truck", "bus"]


def _f(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def load_vehicles(since_epoch=None):
    """Every tagged vehicle across ALL history — the forever-archive (Parquet)
    plus today's hot log — so calibration and fleet mix keep accumulating instead
    of resetting daily. Falls back to raw CSVs if the storage layer is unavailable."""
    try:
        import storage
        rows = storage.vehicle_rows(since_epoch=since_epoch)
        if rows:
            return rows
    except Exception:
        pass
    rows = []
    for path in glob.glob(os.path.join(HERE, "vehicles*.csv")):
        try:
            with open(path) as f:
                rows.extend(list(csv.DictReader(f)))
        except Exception:
            continue
    return rows


def learn_scales(vehicles):
    """Per-camera yardstick: median car box. Returns {cam_id: {...}}."""
    car_area = defaultdict(list)
    car_w = defaultdict(list)
    for r in vehicles:
        if r.get("cls") == "car":
            car_area[r["cam_id"]].append(_f(r.get("area_px")))
            car_w[r["cam_id"]].append(_f(r.get("box_w")))
    scales = {}
    for cam, areas in car_area.items():
        if len(areas) < MIN_CARS_TO_TRUST:
            continue
        med_area = st.median(areas)
        med_w = st.median(car_w[cam]) or 1.0
        scales[cam] = {
            "med_car_area": round(med_area, 1),
            "med_car_w": round(med_w, 1),
            "ft_per_px": round(CAR_WIDTH_FT / med_w, 4),   # rough metric anchor
            "cars_seen": len(areas),
        }
    return scales


def body_type(v, scales):
    """Classify one vehicle into a body type using its camera's yardstick.

    YOLO already separates bus/truck/moto with high confidence, so trust those.
    For 'car'-class boxes we size against the camera's median car to split
    sedan / SUV-van / pickup-large."""
    cls = v.get("cls")
    if cls == "moto":
        return "moto"
    if cls == "bus":
        return "bus"
    if cls == "truck":
        return "truck"
    sc = scales.get(v["cam_id"])
    area = _f(v.get("area_px"))
    aspect = _f(v.get("aspect"), 1.0)
    if not sc or not sc["med_car_area"]:
        return "sedan"                      # uncalibrated camera -> safe default
    ratio = area / sc["med_car_area"]
    # A car near the camera just LOOKS big, so size alone over-calls pickups.
    # Require elongation too: pickups/vans stay long even head-on; sedans don't.
    if ratio >= 2.0 and aspect >= 1.7:
        return "pickup_large"
    if ratio >= 1.5:
        return "suv_van"                    # bigger footprint, not elongated
    return "sedan"


def coverage(vehicles, scales):
    """How much of the fleet sits on a calibrated camera (honest reporting)."""
    total = len(vehicles)
    calib = sum(1 for v in vehicles if v.get("cam_id") in scales)
    return {"vehicles": total, "on_calibrated_cam": calib,
            "pct": round(100 * calib / total, 1) if total else 0.0}


def compute():
    vehicles = load_vehicles()
    scales = learn_scales(vehicles)
    hist = {b: 0 for b in BODY_TYPES}
    for v in vehicles:
        hist[body_type(v, scales)] += 1
    data = {
        "cameras_calibrated": len(scales),
        "body_hist": hist,
        "coverage": coverage(vehicles, scales),
        "scales": scales,
    }
    json.dump(data, open(OUT, "w"))
    return data


if __name__ == "__main__":
    print(json.dumps(compute(), indent=2)[:1500])
