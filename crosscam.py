#!/usr/bin/env python3
"""Cross-camera vehicle matching -> speed + routes.

Every camera has a real lat/lon, so we know exactly how far apart any two are.
Cameras closer than MAX_LINK_MI are "down the road" neighbours. When a vehicle
with the same signature (body type + color) leaves camera A and shows up at a
neighbour B a plausible moment later, we have a match:

        speed = distance_between_cams / (arrival_time - departure_time)

Do that everywhere and you get live corridor speeds and a picture of where
traffic actually flows — through-routes and delivery runs across the ring.

Timing comes from the ~2s wall-clock stamp track.py now records, so short hops
between adjacent cameras resolve to real mph, not minute-bucket mush. Matching
on type+color is deliberately conservative (a signature can repeat), so we
report the MEDIAN implied speed per corridor with a sample count — an estimate
that sharpens as coverage grows, never a fake per-car GPS trace.

Writes speed.json: per-corridor median speed + busiest routes.
"""
import os, csv, glob, json, math
from collections import defaultdict

import calibrate as cal
import embed

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "speed.json")

MAX_LINK_MI = 0.60          # cameras farther apart than this aren't "down the road"
MIN_MPH, MAX_MPH = 3, 75    # implausible speeds => bad match, drop it
MATCH_WINDOW_S = 240        # a vehicle should reach a neighbour within this many seconds
EMB_THRESH = 0.85           # min appearance-fingerprint cosine to call it the same car


def _cams():
    for name in ("cams_all.json", "cams.json"):
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            cams = {c["id"]: c for c in json.load(open(p))}
            if cams:
                return cams
    return {}


def haversine_mi(a, b):
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(math.radians, [a["lat"], a["lon"], b["lat"], b["lon"]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def adjacency(cams):
    """Neighbour pairs within MAX_LINK_MI, with their distance."""
    ids = list(cams)
    pairs = {}
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = cams[ids[i]], cams[ids[j]]
            if "lat" not in a or "lat" not in b:
                continue
            d = haversine_mi(a, b)
            if d <= MAX_LINK_MI:
                pairs[(ids[i], ids[j])] = round(d, 3)
    return pairs


def _load_moving_vehicles():
    """Per-vehicle sightings that are actually moving, with a wall-clock epoch."""
    import datetime as _dt
    seen = defaultdict(list)   # cam_id -> [(epoch, signature, name)]
    scales = cal.learn_scales(cal.load_vehicles())            # scale from ALL history
    now = _dt.datetime.now().timestamp()
    rows = cal.load_vehicles(since_epoch=now - 6 * 3600)      # match within recent 6h
    for r in rows:
        if str(r.get("moving")).lower() not in ("true", "1"):
            continue
        try:
            e = float(r["epoch"])
        except Exception:
            continue
        v = embed.from_hex(r.get("emb", ""))
        if v is None:                       # no fingerprint -> can't safely re-identify
            continue
        seen[r["cam_id"]].append((e, v, r.get("cls"), r.get("name", r["cam_id"])))
    return seen


def compute():
    cams = _cams()
    pairs = adjacency(cams)
    seen = _load_moving_vehicles()

    corridors = []
    for (a, b), dist in pairs.items():
        speeds = []
        # A vehicle only counts as "the same car" at both cameras if its
        # appearance FINGERPRINT matches (cosine >= EMB_THRESH), it's the same
        # coarse class, and the travel time is physically possible. Fingerprint
        # gating is what stops every silver blob matching every other one.
        for src, dst in ((a, b), (b, a)):
            for e0, v0, cls0, _ in seen.get(src, []):
                best = None
                for e1, v1, cls1, _ in seen.get(dst, []):
                    dt = e1 - e0
                    if dt <= 0 or dt > MATCH_WINDOW_S or cls1 != cls0:
                        continue
                    if embed.cosine(v0, v1) < EMB_THRESH:
                        continue
                    if best is None or dt < best:
                        best = dt
                if best:
                    mph = dist / (best / 3600.0)
                    if MIN_MPH <= mph <= MAX_MPH:
                        speeds.append(mph)
        if speeds:
            speeds.sort()
            corridors.append({
                "a": cams[a].get("name", a), "b": cams[b].get("name", b),
                "dist_mi": dist, "matches": len(speeds),
                "median_mph": round(speeds[len(speeds) // 2], 1),
            })
    corridors.sort(key=lambda x: -x["matches"])

    all_speeds = [c["median_mph"] for c in corridors if c["matches"] >= 2]
    data = {
        "neighbor_pairs": len(pairs),
        "corridors": corridors[:40],
        "corridors_measured": len(corridors),
        "city_median_mph": round(sorted(all_speeds)[len(all_speeds) // 2], 1) if all_speeds else None,
        "total_matches": sum(c["matches"] for c in corridors),
    }
    json.dump(data, open(OUT, "w"))
    return data


if __name__ == "__main__":
    d = compute()
    print("neighbor pairs:", d["neighbor_pairs"], "| corridors measured:",
          d["corridors_measured"], "| city median mph:", d["city_median_mph"])
