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


def load_passes():
    """Return sorted [(epoch, cars, ped)] — one row per snapshot pass."""
    if not os.path.exists(CSV_PATH):
        return []
    cars, ped = defaultdict(int), defaultdict(int)
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            try:
                ts = r["ts"]
                cars[ts] += int(r.get("car", 0) or 0)
                cars[ts] += int(r.get("truck", 0) or 0)
                cars[ts] += int(r.get("bus", 0) or 0)
                ped[ts] += int(r.get("person", 0) or 0)
            except Exception:
                continue
    out = []
    for ts in cars:
        try:
            e = dt.datetime.fromisoformat(ts).timestamp()
        except Exception:
            continue
        out.append((e, cars[ts], ped[ts]))
    out.sort()
    return out


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
        "total_passes": len(passes),
    }
    json.dump(data, open(OUT, "w"))
    return data


if __name__ == "__main__":
    print(json.dumps(compute(), indent=2))
