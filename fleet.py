#!/usr/bin/env python3
"""Fleet fingerprint — the headline product.

Run body-typing (calibrate.py) across every camera and each intersection gets a
personality: this corner is trucks, that one is delivery vans, this one is
taxis at rush hour. Aggregated over 900+ cameras it's a citywide map of what
kind of traffic each street actually carries — and how it breathes by hour.

The "prior" isn't hand-coded per neighborhood; it's DISCOVERED here, per camera,
straight from the data. That makes it both an analysis product and a feedback
signal (an uncertain vehicle can lean on its camera's learned mix).

Writes fleet.json: per-camera body mix + a by-hour citywide breakdown.
"""
import os, json, datetime as dt
from collections import defaultdict

import calibrate as cal

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fleet.json")


def _hour(ts):
    try:
        return dt.datetime.fromisoformat(ts).hour
    except Exception:
        return None


def compute():
    vehicles = cal.load_vehicles()
    scales = cal.learn_scales(vehicles)

    per_cam = defaultdict(lambda: {b: 0 for b in cal.BODY_TYPES})
    per_cam_name = {}
    by_hour = defaultdict(lambda: {b: 0 for b in cal.BODY_TYPES})
    citywide = {b: 0 for b in cal.BODY_TYPES}

    for v in vehicles:
        bt = cal.body_type(v, scales)
        cam = v["cam_id"]
        per_cam[cam][bt] += 1
        per_cam_name[cam] = v.get("name", cam)
        citywide[bt] += 1
        h = _hour(v.get("ts", ""))
        if h is not None:
            by_hour[h][bt] += 1

    # rank each camera by its most distinctive type (share vs citywide baseline)
    total = sum(citywide.values()) or 1
    base = {b: citywide[b] / total for b in cal.BODY_TYPES}
    fingerprints = []
    for cam, mix in per_cam.items():
        n = sum(mix.values())
        if n < 5:
            continue
        share = {b: mix[b] / n for b in cal.BODY_TYPES}
        # signature type = biggest positive lift over the citywide baseline
        lift = {b: share[b] - base[b] for b in cal.BODY_TYPES}
        sig = max(lift, key=lift.get)
        fingerprints.append({
            "cam_id": cam, "name": per_cam_name.get(cam, cam),
            "n": n, "signature": sig,
            "mix": {b: round(share[b], 3) for b in cal.BODY_TYPES},
        })
    fingerprints.sort(key=lambda x: -x["n"])

    data = {
        "citywide": citywide,
        "by_hour": {str(h): by_hour[h] for h in sorted(by_hour)},
        "fingerprints": fingerprints,
        "cameras": len(fingerprints),
    }
    json.dump(data, open(OUT, "w"))
    return data


if __name__ == "__main__":
    d = compute()
    print("cameras fingerprinted:", d["cameras"], "citywide:", d["citywide"])
