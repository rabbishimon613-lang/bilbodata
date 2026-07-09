#!/usr/bin/env python3
"""The compute architecture that has to hold 900+ cameras up.

900 cams x ~25 frames/min is a firehose, so the design is a CASCADE — do the
cheap thing on everything, the expensive thing only where it pays off — spread
across many workers so it never chokes:

  TIER 1 (every camera, every pass)  detect + track + measure boxes.
         Cheap. Runs on the edge inside counter.py. Shardable N ways
         (PEDCOUNT_SHARD_COUNT); each worker owns cams[idx::N] and writes its
         own counts_shardK.csv / vehicles_shardK.csv, so workers never collide.

  TIER 2 (aggregate, once per cycle)  merge shards -> derive analytics.
         This orchestrator stitches the shard logs back together and runs the
         heavy rollups over the combined data exactly once:
             stats     -> live counts, windows, hour/day trends
             calibrate -> per-camera scale + body types
             fleet     -> per-camera fingerprints
             crosscam  -> corridor speeds + routes

Run `python pipeline.py aggregate` on the coordinator after the shard workers
finish a cycle. Single-runner setups get the same result for free (counter.py
already calls stats inline; call this for the richer layers).
"""
import os, glob, csv, sys

import stats as statsmod
import calibrate, fleet, crosscam, trajectories
import turso_sync

HERE = os.path.dirname(os.path.abspath(__file__))


def _merge(pattern, out):
    """Concatenate shard CSVs into one combined file (header once)."""
    shards = sorted(glob.glob(os.path.join(HERE, pattern)))
    if not shards:
        return 0
    rows, header = [], None
    for path in shards:
        with open(path) as f:
            r = csv.reader(f)
            h = next(r, None)
            if h is None:
                continue
            header = header or h
            rows.extend(list(r))
    if header is None:
        return 0
    with open(os.path.join(HERE, out), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


def aggregate():
    # TIER 2 merge: only if we're actually running sharded (shard files present)
    merged_counts = _merge("counts_shard*.csv", "counts.csv")
    merged_veh = _merge("vehicles_shard*.csv", "vehicles.csv")
    print("merged: %d count-rows, %d vehicle-rows" % (merged_counts, merged_veh))

    # heavy rollups, each guarded so one failure doesn't sink the cycle
    for name, fn in (("stats", statsmod.compute),
                     ("calibrate", calibrate.compute),
                     ("fleet", fleet.compute),
                     ("crosscam", crosscam.compute),
                     ("trajectories", trajectories.build)):
        try:
            fn()
            print("  ok  %s" % name)
        except Exception as e:
            print("  !!  %s: %s" % (name, e))

    # Live mirror of the freshly (re)built journeys to Turso (no-op if unset).
    turso_sync.sync_trips_file(os.path.join(HERE, "trips.csv"))


if __name__ == "__main__":
    aggregate()
