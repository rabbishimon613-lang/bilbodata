#!/usr/bin/env python3
"""Merge per-head training reports into training/heads_status.json — the file
the Academy tab's "faculty" section reads. Append-only history: each publish
adds one generation point per head that has a fresh report.

  python3 fp/publish_heads.py --models fp_out/models --dest training/heads_status.json
"""
import argparse
import glob
import json
import os
import time

STATUS_KEYS = {"company": "Company / markings", "color": "Color",
               "vclass": "Vehicle class", "plate_state": "Plate state",
               "make_model": "Make & model", "bus": "Bus reads"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="fp_out/models")
    ap.add_argument("--dest", default="training/heads_status.json")
    args = ap.parse_args()

    cur = {"ts": int(time.time()), "heads": []}
    if os.path.exists(args.dest):
        try:
            cur = json.load(open(args.dest))
        except Exception:
            pass
    by_key = {h["key"]: h for h in cur.get("heads", [])}

    for rp in sorted(glob.glob(os.path.join(args.models, "*_report.json"))):
        r = json.load(open(rp))
        key = r["head"]
        h = by_key.setdefault(key, {"key": key, "name": STATUS_KEYS.get(key, key),
                                    "gens": []})
        gens = h["gens"]
        if not gens or gens[-1].get("ts") != r["ts"]:
            gens.append({"g": len(gens) + 1, "score": r["val_acc"],
                         "coverage": r.get("coverage_at_thr"),
                         "thr": r.get("abstain_thr"), "n": r["n_val"],
                         "ts": r["ts"]})
        h["best"] = max(g["score"] for g in gens)
        h["status"] = ("live" if r.get("abstain_thr") is not None else
                       "training — still below its public bar")
        h["classes"] = len(r.get("classes", []))

    cur["ts"] = int(time.time())
    cur["heads"] = list(by_key.values())
    os.makedirs(os.path.dirname(args.dest) or ".", exist_ok=True)
    json.dump(cur, open(args.dest, "w"), indent=1)
    print(f"[fp.publish] {len(cur['heads'])} heads -> {args.dest}")


if __name__ == "__main__":
    main()
