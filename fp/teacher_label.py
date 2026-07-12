#!/usr/bin/env python3
"""Bulk auto-labels — the cheap teacher pass.

Runs a strong detector (yolo11x by default) over unlabeled harvested crops and
keeps only HIGH-CONFIDENCE type/class calls. These are the bulk labels; they
never assert make/model/color/company — that's the gold judge's job. Output is
append-only labels_auto.jsonl next to the manifest.

  python3 fp/teacher_label.py --out fp_out --limit 2000
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CLS = {2: "car", 3: "moto", 5: "bus", 7: "truck"}
KEEP_CONF = 0.75  # below this the teacher stays silent — abstain doctrine


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.environ.get("FP_OUT", "fp_out"))
    ap.add_argument("--model", default="yolo11x.pt")
    ap.add_argument("--limit", type=int, default=2000, help="crops per run")
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    from ultralytics import YOLO

    meta_path = os.path.join(args.out, "crops_meta.jsonl")
    auto_path = os.path.join(args.out, "labels_auto.jsonl")
    done = set()
    if os.path.exists(auto_path):
        with open(auto_path) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["file"])
                except Exception:
                    pass
    todo = []
    with open(meta_path) as f:
        for line in f:
            try:
                m = json.loads(line)
            except Exception:
                continue
            if m["file"] not in done and os.path.exists(os.path.join(args.out, m["file"])):
                todo.append(m)
    todo = todo[-args.limit:]
    if not todo:
        print("[fp.teacher] nothing new to label")
        return

    model = YOLO(args.model)
    kept = abstained = 0
    with open(auto_path, "a") as out:
        for m in todo:
            fp = os.path.join(args.out, m["file"])
            try:
                r = model.predict(fp, imgsz=args.imgsz, conf=0.25,
                                  device="cpu", verbose=False)[0]
            except Exception:
                continue
            best = None
            for b in r.boxes:
                c = int(b.cls)
                if c in CLS and (best is None or float(b.conf) > best[1]):
                    best = (CLS[c], float(b.conf))
            rec = {"file": m["file"], "cam": m["cam"], "tier": m["tier"],
                   "lit": m.get("lit", True), "h": m["h"], "src": "teacher"}
            if best and best[1] >= KEEP_CONF:
                rec.update({"vclass": best[0], "conf": round(best[1], 3)})
                kept += 1
            else:
                rec["abstain"] = True  # logged so it is never re-served
                abstained += 1
            out.write(json.dumps(rec) + "\n")
    print(f"[fp.teacher] {kept} labeled, {abstained} abstained "
          f"(bar: conf >= {KEEP_CONF})")


if __name__ == "__main__":
    main()
