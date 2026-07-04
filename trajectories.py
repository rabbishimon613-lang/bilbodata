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
import os, csv, glob, json, math, hashlib, datetime as dt
from collections import defaultdict

import calibrate as cal
import embed

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "trajectories.json")
TRIPS_CSV = os.path.join(HERE, "trips.csv")   # forever log of completed journeys
TRIP_FIELDS = ["trip_id", "first_ts", "last_ts", "type", "color", "width_ft",
               "n_stops", "cams", "span_min", "match", "confidence", "path"]


def _persist_trips(out_trails, now):
    """Save every COMPLETED trip into the forever DB (trips.csv). A trip is
    complete once its last stop is older than one hop window — no new camera can
    extend it — so we record it exactly once. Dedup by a stable id hashed from its
    (camera, ~5s time) stop sequence, since the 24h window recomputes overlaps
    every run. This is the only durable record of a journey: the fingerprints that
    built it are ephemeral, so if we don't store the trip here it's gone."""
    finalized = [t for t in out_trails
                 if t["stops"] and t["stops"][-1]["t"] / 1000.0 < now - HOP_MAX_S]
    if not finalized:
        return 0
    existing = set()
    if os.path.exists(TRIPS_CSV):
        try:
            existing = {r["trip_id"] for r in csv.DictReader(open(TRIPS_CSV))}
        except Exception:
            pass

    def iso(ms):
        return dt.datetime.fromtimestamp(ms / 1000.0).isoformat(timespec="seconds")

    new = []
    for t in finalized:
        key = "|".join("%s@%d" % (s["cam"], round(s["t"] / 5000)) for s in t["stops"])
        tid = hashlib.sha1(key.encode()).hexdigest()[:16]
        if tid in existing:
            continue
        existing.add(tid)
        path = json.dumps([{"cam": s["cam"], "name": s["name"], "t": s["t"],
                            "lat": s.get("lat"), "lon": s.get("lon")} for s in t["stops"]])
        new.append([tid, iso(t["stops"][0]["t"]), iso(t["stops"][-1]["t"]),
                    t["type"], t["color"], t.get("width_ft"), t["n_stops"], t["cams"],
                    t["span_min"], t.get("match"), t["confidence"], path])
    if new:
        first = not os.path.exists(TRIPS_CSV)
        with open(TRIPS_CSV, "a", newline="") as f:
            w = csv.writer(f)
            if first:
                w.writerow(TRIP_FIELDS)
            w.writerows(new)
    return len(new)

WINDOW_S = 24 * 3600        # look back 24h
HOP_MAX_S = 1200            # max gap between two stops on one trail (20 min)
HOP_MIN_S = 4              # below this it's the same pass, not travel
MIN_MPH, MAX_MPH = 3, 75
MAX_TRAILS = 60
EMB_THRESH = 0.85           # min appearance-fingerprint cosine to link two sightings


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
    now = dt.datetime.now().timestamp()
    rows = cal.load_vehicles(since_epoch=now - WINDOW_S)   # last 24h, archive + hot
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
            "cls": r.get("cls"), "emb": embed.from_hex(r.get("emb", "")),
            "w_ft": w_ft, "moving": str(r.get("moving")).lower() in ("true", "1"),
        })
    out.sort(key=lambda x: x["epoch"])
    return out


def _sig(s):
    wb = "?" if s["w_ft"] is None else str(int(round(s["w_ft"])))
    return "%s|%s|%s" % (s["type"], s["color"], wb)


def build():
    cams = _cams()
    scales = cal.learn_scales(cal.load_vehicles())   # calibrate on ALL history
    sights = _load(scales)

    # Only vehicles that carry an appearance fingerprint can be trailed — that's
    # what makes "the same car" mean the same car. Pre-group by coarse class just
    # to limit comparisons; the real link test is fingerprint cosine + geo + time.
    sights = [s for s in sights if s.get("emb") is not None]
    by_cls = defaultdict(list)
    for s in sights:
        by_cls[s.get("cls") or "car"].append(s)

    trails = []
    for group in by_cls.values():
        group.sort(key=lambda x: x["epoch"])
        used = [False] * len(group)
        for i in range(len(group)):
            if used[i]:
                continue
            chain = [group[i]]
            links = []                       # per-hop fingerprint cosine
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
                cos = embed.cosine(last["emb"], nxt["emb"])
                if cos < EMB_THRESH:          # not the same-looking car -> not a hop
                    continue
                a, b = cams.get(last["cam"]), cams.get(nxt["cam"])
                if not a or not b or "lat" not in a or "lat" not in b:
                    continue
                dist = haversine_mi(a, b)
                mph = dist / (gap / 3600.0)
                if not (MIN_MPH <= mph <= MAX_MPH):
                    continue
                chain.append(nxt)
                links.append(cos)
                used[j] = True
                last = nxt
            if len(chain) >= 2 and len({c["cam"] for c in chain}) >= 2:
                trails.append((chain, links))

    # rank: more stops first, then stronger fingerprint agreement
    trails.sort(key=lambda t: (-len(t[0]), -(sum(t[1]) / len(t[1]) if t[1] else 0)))

    def stop(s):
        c = cams.get(s["cam"], {})
        return {"t": int(s["epoch"] * 1000), "cam": s["cam"], "name": s["name"],
                "lat": c.get("lat"), "lon": c.get("lon")}

    out_trails = []
    for chain, links in trails[:MAX_TRAILS]:
        span = chain[-1]["epoch"] - chain[0]["epoch"]
        avg_cos = sum(links) / len(links) if links else 0.0
        # confidence: how strongly the fingerprints agree, plus a small bonus for
        # more corroborating stops. A tight match across many cameras is trustworthy.
        conf = min(1.0, max(0.0, (avg_cos - EMB_THRESH) / (1.0 - EMB_THRESH))
                   * 0.7 + min(len(chain) / 6.0, 1.0) * 0.3)
        rep = chain[0]
        out_trails.append({
            "type": rep["type"], "color": rep["color"],
            "width_ft": None if rep.get("w_ft") is None else int(round(rep["w_ft"])),
            "match": round(avg_cos, 2),
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

    # persist completed journeys into the forever DB, then report the running total
    now = dt.datetime.now().timestamp()
    added = _persist_trips(out_trails, now)
    total_trips = 0
    if os.path.exists(TRIPS_CSV):
        try:
            total_trips = sum(1 for _ in open(TRIPS_CSV)) - 1
        except Exception:
            pass

    data = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "trails": out_trails,
        "trails_found": len(trails),
        "sightings_24h": len(sights),
        "trips_logged": total_trips,
        "trips_added_now": added,
        "seen_now": latest,
    }
    json.dump(data, open(OUT, "w"))
    return data


if __name__ == "__main__":
    d = build()
    print("sightings 24h:", d["sightings_24h"], "| trails:", d["trails_found"],
          "| shown:", len(d["trails"]))
