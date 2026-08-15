#!/usr/bin/env python3
"""Measure how many DOT cameras actually serve a FRESH frame.

The counter treats every fetch as a new observation. If a camera's endpoint
returns the same cached JPEG for minutes at a time, those are not new
observations — they are one observation counted many times, and every count,
speed and tracking figure derived from that camera is inflated accordingly.
counter.py already appends a `?t=<clock>` cache-buster, so anything stale
past that point is the DOT's own serving layer, not ours.

Method: fetch each sampled camera R times, spaced S seconds apart, and count
DISTINCT image hashes. A camera on a busy road that returns 1 distinct frame
across several minutes is serving a cached image.

The sample is drawn BEFORE any fetching, from a fixed seed, and deliberately
covers both tiers — all 25 HD highway cameras (the good seats) and a random
draw of the 352x240 majority — so the result can't be an artefact of picking
whichever cameras looked lively.

Usage:
    python3 stale_check.py --rounds 3 --spacing 40 --sample 60
"""
import argparse
import csv
import hashlib
import json
import os
import random
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import urllib3

urllib3.disable_warnings()

CAMS = "cams_all.json"
CENSUS = "cam_resolution_census.csv"
OUT = "training/stale_check.json"
SEED = 613
WORKERS = 16


def load_cams():
    cams = {c["id"]: c for c in json.load(open(CAMS))}
    dims = {}
    if os.path.exists(CENSUS):
        for r in csv.DictReader(open(CENSUS)):
            if r["width"] and r["width"].isdigit():
                dims[r["id"]] = (int(r["width"]), int(r["height"]))
    return cams, dims


def pick_sample(cams, dims, n_sd):
    """All HD cameras + a seeded random draw of standard-def ones."""
    hd = sorted(i for i, wh in dims.items() if wh[0] >= 1280 and i in cams)
    sd = sorted(i for i, wh in dims.items() if wh[0] < 1280 and i in cams)
    rng = random.Random(SEED)
    return hd, rng.sample(sd, min(n_sd, len(sd)))


def fetch(http, cam):
    url = cam["img"] + "?t=" + str(time.time())
    try:
        r = http.request("GET", url, timeout=10.0, retries=False)
        if r.status != 200 or not r.data:
            return {"ok": False, "status": r.status}
        return {
            "ok": True,
            "hash": hashlib.sha1(r.data).hexdigest(),
            "bytes": len(r.data),
            "last_modified": r.headers.get("Last-Modified"),
            "age": r.headers.get("Age"),
        }
    except Exception as e:
        return {"ok": False, "status": type(e).__name__}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--spacing", type=int, default=40, help="seconds between rounds")
    ap.add_argument("--sample", type=int, default=60, help="standard-def cameras to draw")
    args = ap.parse_args()

    cams, dims = load_cams()
    hd, sd = pick_sample(cams, dims, args.sample)
    sample = hd + sd
    tier = {**{i: "hd" for i in hd}, **{i: "sd" for i in sd}}
    print(f"[stale] sampling {len(sample)} cameras ({len(hd)} HD, {len(sd)} SD), "
          f"{args.rounds} rounds, {args.spacing}s apart")

    http = urllib3.PoolManager(cert_reqs="CERT_NONE", maxsize=WORKERS * 2)
    seen = defaultdict(list)
    for rnd in range(args.rounds):
        if rnd:
            time.sleep(args.spacing)
        t0 = time.time()
        with ThreadPoolExecutor(WORKERS) as ex:
            results = list(ex.map(lambda i: (i, fetch(http, cams[i])), sample))
        for cid, res in results:
            seen[cid].append(res)
        ok = sum(1 for _, r in results if r["ok"])
        print(f"[stale] round {rnd + 1}/{args.rounds}: {ok}/{len(sample)} fetched "
              f"in {time.time() - t0:.1f}s")

    rows, by_tier = [], defaultdict(lambda: {"cams": 0, "stale": 0, "dead": 0, "fresh": 0})
    for cid in sample:
        res = seen[cid]
        good = [r for r in res if r["ok"]]
        hashes = {r["hash"] for r in good}
        if not good:
            verdict = "dead"
        elif len(good) < 2:
            verdict = "insufficient"
        elif len(hashes) == 1:
            verdict = "stale"
        elif len(hashes) < len(good):
            verdict = "partial"
        else:
            verdict = "fresh"
        t = tier[cid]
        by_tier[t]["cams"] += 1
        if verdict in by_tier[t]:
            by_tier[t][verdict] += 1
        rows.append({
            "id": cid,
            "name": cams[cid]["name"],
            "area": cams[cid].get("area"),
            "tier": t,
            "res": dims.get(cid),
            "fetches_ok": len(good),
            "distinct_frames": len(hashes),
            "verdict": verdict,
            "last_modified": good[0].get("last_modified") if good else None,
        })

    span = (args.rounds - 1) * args.spacing
    summary = {
        "ts": int(time.time()),
        "rounds": args.rounds,
        "spacing_s": args.spacing,
        "window_s": span,
        "sampled": len(sample),
        "seed": SEED,
        "by_tier": {k: dict(v) for k, v in by_tier.items()},
        "verdicts": {v: sum(1 for r in rows if r["verdict"] == v)
                     for v in {r["verdict"] for r in rows}},
        "cameras": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(summary, open(OUT, "w"), indent=1)

    print(f"\n[stale] over a {span}s window:")
    for v, n in sorted(summary["verdicts"].items(), key=lambda x: -x[1]):
        print(f"  {v:13} {n:4}  ({n / len(sample) * 100:.0f}%)")
    for t in ("hd", "sd"):
        if t in by_tier:
            d = by_tier[t]
            print(f"  [{t}] {d['cams']} cams: fresh={d['fresh']} stale={d['stale']} dead={d['dead']}")
    print(f"[stale] wrote {OUT}")


if __name__ == "__main__":
    main()
