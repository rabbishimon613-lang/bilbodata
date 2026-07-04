#!/usr/bin/env python3
"""Within-minute vehicle tracking — the foundation everything else stands on.

The DOT feeds refresh ~every 2s, so during one 50s pass a camera yields ~25
frames. The counter used to average those into a number and throw the frames
away. Here we instead LINK detections across consecutive frames of the SAME
camera into short tracks, so one physical vehicle = one identity for that pass.

That single change unlocks the rest of the system:
  - a stable box to MEASURE (calibrate.py turns pixels -> feet -> body type),
  - a signature to MATCH across cameras (crosscam.py -> speed + routes),
  - a per-camera vehicle mix to AGGREGATE (fleet.py -> fingerprints).

Pure-python IOU linker: no global tracker state, no torch, safe to run at the
edge on every shard. Input is per-frame boxes (already produced by YOLO in the
counter), so tracking adds negligible cost on top of detection.
"""
import math
from collections import defaultdict

VEH_CLASSES = {"car", "truck", "bus", "moto"}


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def _center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def link_tracks(frames, iou_thresh=0.2, max_gap=2):
    """Link per-frame detections into tracks by greedy IOU association.

    `frames` = ordered list (one per captured frame) of detection lists;
    each detection = {"box":(x1,y1,x2,y2), "cls":str, "color":str}.
    Returns a list of tracks; each track summarises one vehicle's pass.
    """
    active = []   # {last_frame, boxes:[...], cls:Counter-ish, colors:[...], centers:[...]}
    done = []

    def close(tr):
        done.append(tr)

    for fi, dets in enumerate(frames):
        # expire tracks unseen for too long
        still = []
        for tr in active:
            if fi - tr["last_frame"] > max_gap:
                close(tr)
            else:
                still.append(tr)
        active = still

        used = set()
        # match existing tracks to detections (greedy, best IOU first)
        pairs = []
        for ti, tr in enumerate(active):
            for di, d in enumerate(dets):
                iou = _iou(tr["boxes"][-1], d["box"])
                if iou >= iou_thresh:
                    pairs.append((iou, ti, di))
        pairs.sort(reverse=True)
        matched_tracks = set()
        for iou, ti, di in pairs:
            if ti in matched_tracks or di in used:
                continue
            tr, d = active[ti], dets[di]
            tr["boxes"].append(d["box"])
            tr["centers"].append(_center(d["box"]))
            tr["colors"].append(d["color"])
            tr["cls"].append(d["cls"])
            tr["last_frame"] = fi
            matched_tracks.add(ti)
            used.add(di)
        # unmatched detections start new tracks
        for di, d in enumerate(dets):
            if di in used:
                continue
            active.append({"first_frame": fi, "last_frame": fi, "boxes": [d["box"]],
                           "centers": [_center(d["box"])],
                           "colors": [d["color"]], "cls": [d["cls"]]})
    for tr in active:
        close(tr)

    return [summarize(tr) for tr in done if _is_vehicle(tr)]


def _is_vehicle(tr):
    return any(c in VEH_CLASSES for c in tr["cls"])


def _mode(seq):
    if not seq:
        return None
    counts = defaultdict(int)
    for s in seq:
        counts[s] += 1
    return max(counts, key=counts.get)


def summarize(tr):
    """Collapse a track into one per-vehicle record for logging."""
    # pick the biggest box as the "best look" (nearest / clearest)
    best = max(tr["boxes"], key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    w, h = best[2] - best[0], best[3] - best[1]
    area = w * h
    aspect = round(w / h, 3) if h else 0.0
    # heading + pixel speed from first->last center
    (x0, y0), (x1, y1) = tr["centers"][0], tr["centers"][-1]
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy)
    frames_span = max(len(tr["boxes"]) - 1, 1)
    heading = round((math.degrees(math.atan2(dy, dx)) + 360) % 360, 1)
    return {
        "cls": _mode([c for c in tr["cls"] if c in VEH_CLASSES]) or _mode(tr["cls"]),
        "box_w": int(w), "box_h": int(h), "area_px": int(area), "aspect": aspect,
        "color": _mode(tr["colors"]),
        "frames": len(tr["boxes"]),
        "heading": heading,
        "px_per_frame": round(dist / frames_span, 2),
        "moving": dist > max(w, h) * 0.4,   # moved ~half its own size => not parked
        "f0": tr["first_frame"], "f1": tr["last_frame"],   # frame indices (for wall-clock timing)
    }


VEH_FIELDS = ["cls", "box_w", "box_h", "area_px", "aspect", "color",
              "frames", "heading", "px_per_frame", "moving"]
