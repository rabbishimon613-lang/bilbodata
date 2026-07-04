#!/usr/bin/env python3
"""Where has this vehicle been? — 24-hour cross-camera trail reconstruction.

The dossier layer. For a vehicle seen right now we want everything we know —
color, measured body type, real size — and MOST importantly its recent path:
"5 minutes ago this one was at Grand Army Plaza, before that Eastern Pkwy."

How, honestly, at 352x240 with no plates:
  Each sighting carries a SIGNATURE = (body type, color, calibrated width in ft).
  Calibrated width makes size comparable ACROSS cameras (a camera's own yardstick
  turns pixels into feet), so the signature is far more distinctive than colour
  alone. We then CHAIN sightings into a journey when consecutive ones are:
      - the same signature,
      - at geographically reachable cameras (we know every lat/lon),
      - separated by a feasible travel time (implied speed 3-75 mph),
  greedily, over the last 24h. A chain spanning >=2 cameras is a trail.

This is a BEST-MATCH reconstruction, not a plate read — a shared signature can
belong to two different cars, so every trail carries a confidence from how rare
its signature is in the window. Trails sharpen as camera coverage and sampling
cadence grow. No individual is identified; there is no PII in a colour + size.

Writes trajectories.json: reconstructed trails + a per-camera "seen here now"
index so the UI can answer "click this vehicle -> where has it been."
"""
import os, csv, glob, json, math, datetime as dt
from collections import defaultdict

import calibrate as cal

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "trajectories.json")

WINDOW_S = 24 * 3600        # look back 24h
HOP_MAX_S = 1200            # max gap between two stops on one trail (20 min)
HOP_MIN_S = 4              # below this it's the same pass, not travel
MIN_MPH, MAX_MPH = 3, 75
MAX_TRAILS = 60


def _cams():
    for name in ("cams_all.json", "cams.json"):
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            return {c["id"]: c for c in json.load(open(p))}
    return {}


def haversine_mi(a, b):
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(math.radians, [a["lat"], a["lon"], b["lat"], b["lon"]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _load(scales):
    rows = []
    for path in glob.glob(os.path.join(HERE, "vehicles*.csv")):
        try:
            rows.extend(list(csv.DictReader(open(path))))
        except Exception:
            continue
    now = dt.datetime.now().timestamp()
    out = []
    for r in rows:
        try:
            e = float(r["epoch"])
        except Exception:
            continue
        if now - e > WINDOW_S:
            continue
        sc = scales.get(r["cam_id"])
        try:
            w_ft = round(float(r["box_w"]) * sc["ft_per_px"], 1) if sc else None
        except Exception:
            w_ft = None
        out.append({
            "epoch": e, "cam": r["cam_id"], "name": r.get("name", r["cam_id"]),
            "type": cal.body_type(r, scales), "color": r.get("color"),
            "w_ft": w_ft, "moving": str(r.get("moving")).lower() in ("true", "1"),
        })
    out.sort(key=lambda x: x["epoch"])
    return out


def _sig(s):
    wb = "?" if s["w_ft"] is None else str(int(round(s["w_ft"])))
    return "%s|%s|%s" % (s["type"], s["color"], wb)


def build():
    cams = _cams()
    scales = cal.learn_scales(
        [r for p in glob.glob(os.path.join(HERE, "vehicles*.csv"))
         for r in csv.DictReader(open(p))])
    sights = _load(scales)

    # group by signature; how common each signature is drives confidence
    by_sig = defaultdict(list)
    for s in sights:
        by_sig[_sig(s)].append(s)

    trails = []
    for sig, group in by_sig.items():
        group.sort(key=lambda x: x["epoch"])
        used = [False] * len(group)
        for i in range(len(group)):
            if used[i]:
                continue
            chain = [group[i]]
            used[i] = True
            last = group[i]
            for j in range(i + 1, len(group)):
                if used[j]:
                    continue
                nxt = group[j]
                gap = nxt["epoch"] - last["epoch"]
                if gap < HOP_MIN_S:
                    continue
                if gap > HOP_MAX_S:
                    break
                if nxt["cam"] == last["cam"]:
                    continue
                a, b = cams.get(last["cam"]), cams.get(nxt["cam"])
                if not a or not b or "lat" not in a or "lat" not in b:
                    continue
                dist = haversine_mi(a, b)
                mph = dist / (gap / 3600.0)
                if not (MIN_MPH <= mph <= MAX_MPH):
                    continue
                chain.append(nxt)
                used[j] = True
                last = nxt
            if len(chain) >= 2 and len({c["cam"] for c in chain}) >= 2:
                trails.append((sig, chain, len(by_sig[sig])))

    # rank: more stops first, then rarer signature (higher confidence)
    trails.sort(key=lambda t: (-len(t[1]), t[2]))

    def stop(s):
        c = cams.get(s["cam"], {})
        return {"t": int(s["epoch"] * 1000), "cam": s["cam"], "name": s["name"],
                "lat": c.get("lat"), "lon": c.get("lon")}

    out_trails = []
    for sig, chain, pop in trails[:MAX_TRAILS]:
        typ, color, wb = sig.split("|")
        span = chain[-1]["epoch"] - chain[0]["epoch"]
        # confidence: rarer signature + more stops => more trustworthy
        conf = min(1.0, (len(chain) / 4.0) * (1.0 / max(1, pop / 25.0)))
        out_trails.append({
            "type": typ, "color": color, "width_ft": None if wb == "?" else int(wb),
            "stops": [stop(s) for s in chain],
            "n_stops": len(chain), "cams": len({c["cam"] for c in chain}),
            "span_min": round(span / 60.0, 1),
            "confidence": round(conf, 2),
            "conf_label": "high" if conf >= .6 else "medium" if conf >= .3 else "low",
        })

    # "seen here now": latest pass vehicles per camera (for click-through dossiers)
    latest = {}
    if sights:
        last_min = max(s["epoch"] for s in sights)
        for s in sights:
            if last_min - s["epoch"] <= 60:
                latest.setdefault(s["cam"], []).append({
                    "type": s["type"], "color": s["color"], "w_ft": s["w_ft"],
                    "moving": s["moving"], "t": int(s["epoch"] * 1000),
                })

    data = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "trails": out_trails,
        "trails_found": len(trails),
        "sightings_24h": len(sights),
        "seen_now": latest,
    }
    json.dump(data, open(OUT, "w"))
    return data


if __name__ == "__main__":
    d = build()
    print("sightings 24h:", d["sightings_24h"], "| trails:", d["trails_found"],
          "| shown:", len(d["trails"]))
