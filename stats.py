#!/usr/bin/env python3
"""Roll counts.csv up into windowed aggregates + a time series for charts.
Writes stats.json. Aggregate-only: everything here is per-snapshot totals
summed/averaged across cams. No individual vehicle is represented.
"""
import csv, json, os, datetime as dt
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "counts.csv")
OUT = os.path.join(HERE, "stats.json")

WINDOWS = {"1m": 60, "1h": 3600, "24h": 86400, "1mo": 2592000}


VEH_KEYS = ("car", "truck", "bus", "moto")   # vehicles only (person/bike dropped)


def _i(r, k):
    try:
        return int(r.get(k, 0) or 0)
    except Exception:
        return 0


def load_rows():
    """Return raw rows with parsed epoch. Keeps per-cam granularity for
    intersection / vehicle-mix / color rollups."""
    if not os.path.exists(CSV_PATH):
        return []
    rows = []
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            try:
                e = dt.datetime.fromisoformat(r["ts"]).timestamp()
            except Exception:
                continue
            rows.append((e, r))
    rows.sort(key=lambda x: x[0])
    return rows


def load_passes():
    """Return sorted [(epoch, cars, ped)] — one row per snapshot pass."""
    cars, ped = defaultdict(int), defaultdict(int)
    for _, r in load_rows():
        ts = r["ts"]
        cars[ts] += _i(r, "car") + _i(r, "truck") + _i(r, "bus")
        ped[ts] += _i(r, "person")
    out = []
    for ts in cars:
        try:
            e = dt.datetime.fromisoformat(ts).timestamp()
        except Exception:
            continue
        out.append((e, cars[ts], ped[ts]))
    out.sort()
    return out


def hour_of_day(rows):
    """Avg cars & peds by local hour (0-23), across all history."""
    if not rows:
        return []
    bucket = defaultdict(lambda: [0, 0, 0])  # cars, ped, samples (per snapshot)
    per_snap = defaultdict(lambda: [0, 0])
    ts_hour = {}
    for e, r in rows:
        ts = r["ts"]
        if ts not in ts_hour:
            ts_hour[ts] = dt.datetime.fromtimestamp(e).hour
        per_snap[ts][0] += _i(r, "car") + _i(r, "truck") + _i(r, "bus")
        per_snap[ts][1] += _i(r, "person")
    for ts, (c, p) in per_snap.items():
        h = ts_hour[ts]
        bucket[h][0] += c
        bucket[h][1] += p
        bucket[h][2] += 1
    return [{"h": h,
             "cars": round(bucket[h][0] / bucket[h][2], 1) if bucket[h][2] else 0,
             "ped": round(bucket[h][1] / bucket[h][2], 1) if bucket[h][2] else 0,
             "samples": bucket[h][2]}
            for h in range(24)]


def day_of_week(rows):
    """Avg cars & peds by weekday (Mon=0)."""
    per_snap = defaultdict(lambda: [0, 0])
    ts_dow = {}
    for e, r in rows:
        ts = r["ts"]
        if ts not in ts_dow:
            ts_dow[ts] = dt.datetime.fromtimestamp(e).weekday()
        per_snap[ts][0] += _i(r, "car") + _i(r, "truck") + _i(r, "bus")
        per_snap[ts][1] += _i(r, "person")
    bucket = defaultdict(lambda: [0, 0, 0])
    for ts, (c, p) in per_snap.items():
        d = ts_dow[ts]
        bucket[d][0] += c
        bucket[d][1] += p
        bucket[d][2] += 1
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return [{"d": names[d],
             "cars": round(bucket[d][0] / bucket[d][2], 1) if bucket[d][2] else 0,
             "ped": round(bucket[d][1] / bucket[d][2], 1) if bucket[d][2] else 0}
            for d in range(7)]


def vehicle_mix(rows):
    """Total counts per class, all-time."""
    tot = {k: 0 for k in VEH_KEYS}
    for _, r in rows:
        for k in VEH_KEYS:
            tot[k] += _i(r, k)
    return tot


def busiest_intersections(rows, limit=15):
    """Total cars+trucks+buses per intersection, all-time."""
    tot = defaultdict(lambda: [0, 0, 0])  # veh, ped, samples
    for _, r in rows:
        name = r.get("name") or r.get("cam_id") or "?"
        tot[name][0] += _i(r, "car") + _i(r, "truck") + _i(r, "bus")
        tot[name][1] += _i(r, "person")
        tot[name][2] += 1
    ranked = sorted(tot.items(), key=lambda x: -x[1][0])[:limit]
    return [{"name": n, "veh": v[0], "ped": v[1], "samples": v[2]}
            for n, v in ranked]


def window_stat(passes, now, secs):
    lo = now - secs
    sel = [(c, p) for (e, c, p) in passes if e >= lo]
    if not sel:
        return {"avg_cars": None, "avg_ped": None, "peak_cars": None, "samples": 0}
    n = len(sel)
    return {
        "avg_cars": round(sum(c for c, _ in sel) / n, 1),
        "avg_ped": round(sum(p for _, p in sel) / n, 1),
        "peak_cars": max(c for c, _ in sel),
        "samples": n,
    }


def yesterday_same(passes, now):
    target = now - 86400
    near = [(c, p) for (e, c, p) in passes if abs(e - target) <= 300]  # +/-5 min
    if not near:
        return None
    n = len(near)
    return {"cars": round(sum(c for c, _ in near) / n, 1),
            "ped": round(sum(p for _, p in near) / n, 1)}


def series(passes, now, secs=86400, bucket=60):
    """Bucketed avg cars/ped for charting over the last `secs`. 1-min buckets."""
    lo = now - secs
    buckets = defaultdict(lambda: [0, 0, 0])  # sum_cars, sum_ped, n
    for e, c, p in passes:
        if e < lo:
            continue
        b = int(e // bucket) * bucket
        buckets[b][0] += c
        buckets[b][1] += p
        buckets[b][2] += 1
    pts = []
    for b in sorted(buckets):
        s = buckets[b]
        pts.append({"t": int(b * 1000),
                    "cars": round(s[0] / s[2], 1),
                    "ped": round(s[1] / s[2], 1)})
    return pts


def compute():
    rows = load_rows()
    passes = load_passes()
    now = dt.datetime.now().timestamp()
    now_cars = now_ped = 0
    if passes:
        last_e = passes[-1][0]
        cur = [(c, p) for (e, c, p) in passes if e == last_e]
        now_cars = sum(c for c, _ in cur)
        now_ped = sum(p for _, p in cur)
    data = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "now": {"cars": now_cars, "ped": now_ped},
        "yesterday": yesterday_same(passes, now),
        "windows": {k: window_stat(passes, now, s) for k, s in WINDOWS.items()},
        "series": series(passes, now),
        "hour_of_day": hour_of_day(rows),
        "day_of_week": day_of_week(rows),
        "vehicle_mix": vehicle_mix(rows),
        "busiest": busiest_intersections(rows),
        "total_passes": len(passes),
    }
    json.dump(data, open(OUT, "w"))
    return data


if __name__ == "__main__":
    print(json.dumps(compute(), indent=2))
