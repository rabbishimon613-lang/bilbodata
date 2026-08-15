#!/usr/bin/env python3
"""Keep the append-only cloud manifests below GitHub's 100 MiB file cliff.

WHY THIS EXISTS
---------------
fp/crops_meta.cloud.jsonl is appended by every harvest generation and
committed to main. On 2026-07-23 it reached 108.38 MB and GitHub rejected
the push outright ("exceeds GitHub's file size limit of 100.00 MB"). The
harvest chain has been wedged ever since: every generation harvested crops
fine, shipped them to the `crops` release fine, then failed to push its
manifest, three retries, forever. worker.yml already had an 80 MB guard on
counts.csv/vehicles.csv for exactly this reason — harvest.yml never got one.

So: roll the manifest before it hits the cliff, not after. The historical
bulk goes to the `crops` release as a gzipped archive (originals are never
deleted, only moved out of git), and main keeps a recent tail.

THE COUNTER PROBLEM
-------------------
Two things read this file's LINE COUNT as a measure of total corpus size:
  - gate.yml, to decide whether enough new crops have banked to fire a
    Kaggle training burst
  - fp/pace.py, to compute the crops/hour rate and the plateau ETA
Truncating the file would make both read a sudden collapse to ~5000 and
never recover — the training gate would stop firing entirely.

So rotation keeps a cumulative count in fp/crops_total.json:

    total = rotated_lines (sum of everything rolled out) + current line count

which is exact across any number of rotations. Both callers ask this script
for the total instead of running `wc -l`.
"""
import argparse
import gzip
import json
import os
import time

STATE = "fp/crops_total.json"

# Roll well before the cliff. A harvest generation adds ~4 MB, so 50 MiB
# leaves roughly a dozen generations of headroom even if rotation itself
# fails a couple of times.
ROTATE_AT = 50 * 1024 * 1024

FILES = {
    "crops": {"path": "fp/crops_meta.cloud.jsonl", "keep_tail": 5000},
    "labels": {"path": "fp/labels_auto.cloud.jsonl", "keep_tail": 5000},
}


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(state):
    state["updated"] = int(time.time())
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE)


def count_lines(path):
    if not os.path.exists(path):
        return 0
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def entry(state, key):
    return state.get(key) or {"rotated_lines": 0, "archives": []}


def total_for(key, state=None):
    """Cumulative lines ever written, across every rotation."""
    state = load_state() if state is None else state
    return entry(state, key)["rotated_lines"] + count_lines(FILES[key]["path"])


def needs_rotation(key):
    path = FILES[key]["path"]
    return os.path.exists(path) and os.path.getsize(path) >= ROTATE_AT


def rotate(key, outdir):
    """Move all but the tail into a gzipped archive. Returns archive path."""
    spec = FILES[key]
    path, keep_tail = spec["path"], spec["keep_tail"]

    total = count_lines(path)
    split = total - keep_tail
    if split <= 0:
        print(f"[rotate] {path}: only {total} lines, nothing to roll")
        return None

    os.makedirs(outdir, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    base = os.path.basename(path).replace(".jsonl", "")
    archive = os.path.join(outdir, f"{base}_{stamp}.jsonl.gz")

    # Stream both halves — the live file is ~100 MB and the runner is small.
    tmp = path + ".tmp"
    with open(path, "rb") as src, gzip.open(archive, "wb") as arc, open(tmp, "wb") as tail:
        for i, line in enumerate(src):
            (arc if i < split else tail).write(line)
    os.replace(tmp, path)

    state = load_state()
    ent = entry(state, key)
    ent["rotated_lines"] += split
    ent["archives"].append({
        "name": os.path.basename(archive),
        "lines": split,
        "ts": int(time.time()),
    })
    state[key] = ent
    state[f"{key}_total"] = ent["rotated_lines"] + count_lines(path)
    save_state(state)

    mb = os.path.getsize(archive) / 1e6
    print(f"[rotate] {path}: rolled {split} lines -> {archive} ({mb:.1f} MB), "
          f"kept {keep_tail}, cumulative total {state[f'{key}_total']}")
    return archive


def refresh_totals():
    """Keep the convenience totals current even when nothing rotated."""
    state = load_state()
    for key in FILES:
        ent = entry(state, key)
        state[key] = ent
        state[f"{key}_total"] = ent["rotated_lines"] + count_lines(FILES[key]["path"])
    save_state(state)
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", metavar="KEY", help="print cumulative line total and exit")
    ap.add_argument("--check", action="store_true", help="report sizes, rotate nothing")
    ap.add_argument("--rotate", action="store_true", help="roll any file over the threshold")
    ap.add_argument("--force", action="store_true", help="roll regardless of size")
    ap.add_argument("--out", default="rotate_out", help="where to write archives")
    args = ap.parse_args()

    if args.total:
        print(total_for(args.total))
        return

    if args.check:
        for key, spec in FILES.items():
            path = spec["path"]
            size = os.path.getsize(path) if os.path.exists(path) else 0
            print(f"[check] {key}: {size / 1e6:.1f} MB  total={total_for(key)}  "
                  f"{'ROTATE' if size >= ROTATE_AT else 'ok'}")
        return

    if args.rotate or args.force:
        rolled = []
        for key in FILES:
            if args.force or needs_rotation(key):
                a = rotate(key, args.out)
                if a:
                    rolled.append(a)
        refresh_totals()
        # Workflows read this to decide whether to upload anything.
        gh_out = os.environ.get("GITHUB_OUTPUT")
        if gh_out:
            with open(gh_out, "a") as f:
                f.write(f"rolled={'true' if rolled else 'false'}\n")
        for a in rolled:
            print(f"[rotate] archive ready: {a}")
        if not rolled:
            print("[rotate] nothing over the threshold")
        return

    refresh_totals()
    for key in FILES:
        print(f"[total] {key}={total_for(key)}")


if __name__ == "__main__":
    main()
