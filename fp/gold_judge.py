#!/usr/bin/env python3
"""Gold labels — the Claude bench (runs on Pedro's Max plan, never the paid API).

Workflow, in a Claude Code session:
  1. `python3 fp/gold_judge.py sheet --out fp_out`  builds numbered 3x4 contact
     sheets of unjudged, sharp, tier-eligible crops (sheets/sheet_NNN.jpg).
  2. Claude READS the sheet image and, for each cell it is genuinely sure of,
     names what the pixels carry: make / model / color / company / plate_state /
     bus fields. Anything uncertain is an abstain — that is the whole doctrine.
  3. `python3 fp/gold_judge.py apply NNN "1:make=Toyota;model=Camry;color=white" \
         "2:abstain" "3:company=Penske;color=yellow" ...`
     Company reads are resolved against the living catalogue; a read that
     matches nothing is reported as a candidate row, not silently invented.

Batches of ~200-500 crops per run — gold is a garnish, not the firehose.
Self-labeling vehicles (a FedEx truck IS its own label) are the cheapest gold.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from company_match import match as co_match  # noqa: E402
from tiers import head_allowed  # noqa: E402

GRID = (3, 4)           # rows x cols per sheet
CELL = 300              # px per cell
MIN_SHARP = 60.0        # only crops worth a careful read
FIELDS = {"make", "model", "color", "company", "plate_state",
          "bus_route", "bus_dest", "bus_fleet", "vclass", "conf", "note"}


def _paths(out):
    return (os.path.join(out, "crops_meta.jsonl"),
            os.path.join(out, "labels_gold.jsonl"),
            os.path.join(out, "sheets"))


def _judged(gold_path):
    seen = set()
    if os.path.exists(gold_path):
        with open(gold_path) as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["file"])
                except Exception:
                    pass
    return seen


def build_sheets(out, batch, day_only=True):
    import cv2
    meta_path, gold_path, sheet_dir = _paths(out)
    os.makedirs(sheet_dir, exist_ok=True)
    seen = _judged(gold_path)
    cands = []
    with open(meta_path) as f:
        for line in f:
            try:
                m = json.loads(line)
            except Exception:
                continue
            if m["file"] in seen or m.get("sharp", 0) < MIN_SHARP:
                continue
            if day_only and not m.get("lit", True):
                continue
            if not os.path.exists(os.path.join(out, m["file"])):
                continue
            cands.append(m)
    # sharpest & biggest first — best gold per read
    cands.sort(key=lambda m: (m.get("sharp", 0) * m.get("h", 0)), reverse=True)
    cands = cands[:batch]
    if not cands:
        print("[fp.gold] nothing unjudged that clears the bar")
        return
    per = GRID[0] * GRID[1]
    existing = len([f for f in os.listdir(sheet_dir) if f.startswith("sheet_")])
    for s in range(0, len(cands), per):
        n = existing + s // per + 1
        canvas = cv2.imread(os.path.join(out, cands[0]["file"]))  # dtype/channel template
        import numpy as np
        canvas = np.zeros((GRID[0] * CELL, GRID[1] * CELL, 3), dtype="uint8")
        index = []
        for i, m in enumerate(cands[s:s + per]):
            img = cv2.imread(os.path.join(out, m["file"]))
            if img is None:
                continue
            h, w = img.shape[:2]
            sc = min(CELL / w, CELL / h)
            img = cv2.resize(img, (int(w * sc), int(h * sc)))
            r, c = divmod(i, GRID[1])
            y, x = r * CELL, c * CELL
            canvas[y:y + img.shape[0], x:x + img.shape[1]] = img
            cv2.putText(canvas, str(i + 1), (x + 8, y + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 128), 2)
            index.append({"cell": i + 1, "file": m["file"], "tier": m["tier"],
                          "cls": m["cls"], "lit": m.get("lit", True)})
        sp = os.path.join(sheet_dir, f"sheet_{n:03d}.jpg")
        cv2.imwrite(sp, canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
        json.dump(index, open(sp.replace(".jpg", ".json"), "w"), indent=1)
        print(f"[fp.gold] {sp}  ({len(index)} crops)")


def apply(out, sheet_n, readings):
    _, gold_path, sheet_dir = _paths(out)
    idx_path = os.path.join(sheet_dir, f"sheet_{int(sheet_n):03d}.json")
    index = {r["cell"]: r for r in json.load(open(idx_path))}
    new_companies = []
    with open(gold_path, "a") as f:
        for spec in readings:
            cell, _, body = spec.partition(":")
            m = index.get(int(cell))
            if not m:
                print(f"  !! no cell {cell} on sheet {sheet_n}")
                continue
            rec = {"file": m["file"], "tier": m["tier"], "lit": m["lit"],
                   "src": "gold", "sheet": int(sheet_n)}
            if body.strip() in ("abstain", "not_vehicle"):
                rec[body.strip()] = True
            else:
                for kv in body.split(";"):
                    k, _, v = kv.partition("=")
                    k, v = k.strip(), v.strip()
                    if k not in FIELDS or not v:
                        continue
                    # tier gate: never record a claim the tier can't support
                    hk = {"make": "make_model", "model": "make_model",
                          "plate_state": "plate_state", "company": "company",
                          "bus_route": "bus", "bus_dest": "bus",
                          "bus_fleet": "bus"}.get(k)
                    if hk and not head_allowed(hk, m["tier"]):
                        print(f"  !! dropped {k}={v} — {m['tier']} tier can't carry it")
                        continue
                    if k == "company":
                        hit = co_match(v)
                        if hit:
                            v = hit["company"]
                        else:
                            new_companies.append(v)
                    rec[k] = v
            f.write(json.dumps(rec) + "\n")
    if new_companies:
        print("[fp.gold] fleets NOT in the catalogue (add with company_match --add):")
        for c in sorted(set(new_companies)):
            print(f"    {c}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sheet", "apply"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--out", default=os.environ.get("FP_OUT", "fp_out"))
    ap.add_argument("--batch", type=int, default=240)
    ap.add_argument("--night", action="store_true", help="include night crops")
    args = ap.parse_args()
    if args.cmd == "sheet":
        build_sheets(args.out, args.batch, day_only=not args.night)
    else:
        apply(args.out, args.rest[0], args.rest[1:])


if __name__ == "__main__":
    main()
