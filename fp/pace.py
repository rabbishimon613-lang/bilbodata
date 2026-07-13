#!/usr/bin/env python3
"""Publish training/pace.json — the plateau clock.

Reads fp/crops_meta.cloud.jsonl (cumulative crop manifest across all
harvest generations), samples (now, line_count), stitches it against
the earliest sample seen, computes the crops-per-hour rate, and
extrapolates when the corpus should reach the "first plateau" mark
(PLATEAU_TARGET crops). Site reads pace.json to render an ETA banner.

PLATEAU_TARGET is not a scientific claim — it's the empirical point at
which most of the heads for a MobileNet-scale multi-head fingerprint
network stop meaningfully improving from more raw crops. We treat 250k
as "first plateau"; a real second plateau would need more variety, not
more volume.
"""
import json
import os
import subprocess
import sys
import time

MANIFEST = "fp/crops_meta.cloud.jsonl"
PACE = "training/pace.json"
PLATEAU_TARGET = 250_000
HISTORY_MAX = 96  # keep last N samples (~2 days at 30-min cadence)


def line_count(path):
    if not os.path.exists(path):
        return 0
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def load(path):
    try:
        return json.load(open(path))
    except Exception:
        return {}


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=1)


def main():
    now = int(time.time())
    crops = line_count(MANIFEST)
    state = load(PACE)

    hist = state.get("history", [])
    hist.append({"ts": now, "crops": crops})
    hist = hist[-HISTORY_MAX:]

    first = state.get("first") or {"ts": now, "crops": crops}
    if "first" not in state:
        state["first"] = first

    # Rate estimation — prefer a stable long baseline (first sample); fall
    # back to short-window if we're too fresh to be reliable.
    dt = max(1, now - first["ts"])
    dc = max(0, crops - first["crops"])
    rate_per_hour = dc / dt * 3600.0 if dt >= 900 else 0.0

    remaining = max(0, PLATEAU_TARGET - crops)
    if rate_per_hour > 1:
        eta_ts = now + int(remaining / rate_per_hour * 3600)
    else:
        eta_ts = 0

    out = {
        "ts": now,
        "crops": crops,
        "target": PLATEAU_TARGET,
        "first": first,
        "rate_per_hour": round(rate_per_hour, 1),
        "remaining": remaining,
        "eta_ts": eta_ts,
        "history": hist,
    }
    save(PACE, out)
    print(f"[pace] crops={crops} rate={rate_per_hour:.1f}/h "
          f"remaining={remaining} eta_ts={eta_ts}")


if __name__ == "__main__":
    main()
