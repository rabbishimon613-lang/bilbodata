# Bilbo vehicle-detector training — START HERE (safe handoff for a new window)

> **SUPERSEDED IN PART (2026-07-12):** the detector loop below still works, but
> the project's direction is now the FINGERPRINT platform — tiers, handles,
> abstain bar — specified in `handoff/REBUILD_SPEC.md` and implemented in
> `fp/` + `.github/workflows/harvest.yml` + `gate.yml` + `kaggle/`. Read
> `fp/README.md` first; use this doc only for the legacy count-detector rig.

This folder is a **turnkey, self-contained handoff.** A fresh Claude/Fable
window should be able to read these three docs and execute the whole thing
mechanically. All the design decisions are already made and explained; the
scripts are written out in full below and in the two spec files. Nothing here
requires re-deriving anything or touching the live site.

## Paste this into the new window

> Read `bilbodata/handoff/START_HERE.md`, `TRAIN_SPEC.md`, and `DASHBOARD_SPEC.md`
> in full. Then execute the pipeline in the order listed in START_HERE:
> (1) create the scripts exactly as written in the specs, (2) build the split
> dataset, (3) auto-label it with the teacher model, (4) start the read-only
> dashboard on localhost, (5) train the student detector and watch it on the
> dashboard, (6) evaluate on the held-out camera. Obey every rule in the
> GUARDRAILS section. Do NOT touch the live Bilbo site, Vercel, the running
> worker, or the Turso DB. Do NOT re-harvest from the archive. This is a
> local-only training + visualization job. Verify each step's output before
> moving to the next; report the final mAP sliced by day vs night.

## What already exists (do not rebuild)
- `training_library/` — **2,160 distinct 640×480 frames**, 11 all-borough
  highway cameras × {sunny 2026-06-20, overcast 2026-07-08, rain 2026-07-06} ×
  6 hours (day+night). Layout:
  `training_library/<slug>_<camid>/<date>_<weather>/<HH>_<day|night>/HH_ii.jpg`
- `training_library_contactsheet.jpg` — visual index of the whole set.
- `TRAINING_PLAYBOOK.md` — the big-picture plan (Phase 0 = how the library was
  built; this handoff is the training that comes after).
- Harvest scripts (`tca_*.py/.csv`) — only re-run if you deliberately want MORE
  data; not needed for training.

## The goal
Turn the unlabeled library into a trained **vehicle detector** for NYC DOT
footage, and watch it train on a **read-only localhost dashboard**. Coarse
classes only: `car, truck, bus, motorcycle, person`. NO make/model/color — this
footage is 640×480; that stays a separate hi-res job (see playbook).

## Order of operations
Each step's full script is in `TRAIN_SPEC.md` (steps 1–4) and
`DASHBOARD_SPEC.md` (the dashboard). Create the file, then run it.

| # | Do this | Script | Watch |
|---|---------|--------|-------|
| 0 | Install deps | `pip install ultralytics flask` | — |
| 1 | Build camera-disjoint split (symlinks) | `prepare_dataset.py` | prints split counts |
| 2 | Start the dashboard (leave running) | `dashboard.py` → open http://127.0.0.1:8800 | labeling + training live |
| 3 | Auto-label with the teacher | `label_teacher.py` | dashboard "Labeling" bar + sample |
| 4 | Train the student, ~overnight/1–2h | `train.py` | dashboard mAP curve + live predictions |
| 5 | Evaluate on held-out camera | `eval.py` | prints mAP by day/night |

Start the dashboard (step 2) BEFORE labeling (step 3) so you can watch both
phases. The dashboard auto-detects whether labeling or training is happening.

## The two choices already defaulted (flip if you want)
1. **Fully-automatic labels** (default) vs hand-correcting ~400 frames first.
   Default gets you training tonight. Phase-2 quality bump = load
   `dataset/` into Label Studio, fix ~400 night/rain frames, retrain. Written
   up at the end of `TRAIN_SPEC.md`.
2. **YOLO11-nano** (default, fast, deploys faster than current) vs **-small**
   (a bit more accurate, slower). Change one string in `train.py`.

## GUARDRAILS (the "safe" in safe prompt)
- **Local only.** Everything runs on this Mac (or free Colab). No frames or
  models get uploaded anywhere. No external services.
- **The dashboard is READ-ONLY.** It only *reads* training output files and
  displays them. It has no button, endpoint, or code path that starts, stops,
  or changes a training run. Do not add one.
- **Do NOT touch the live Bilbo product:** not the Vercel deploy, not the
  running recognition worker (gen 14 on the new schema), not the Turso DB, not
  `deploy.yml`. This job is isolated under `bilbodata/dataset/` and
  `bilbodata/runs/`.
- **Do NOT re-run the old pipeline/worker.** It was deliberately separated from
  this. Training here produces a `.pt` weights file and nothing else.
- **Do NOT re-harvest** from trafficcamarchive.com as part of this. The library
  is already built. (If the user later asks for more data, the harvest scripts
  exist and are rate-mild — but that's a separate, explicit request.)
- **No make/model/color/re-ID heads.** Coarse vehicle classes only. This is a
  proven ceiling for this footage, not a limitation to engineer around.
- **Nothing destructive.** `prepare_dataset.py` uses symlinks — it never copies
  or moves the original library. Never delete `training_library/`.
- Writes are confined to: `bilbodata/dataset/`, `bilbodata/runs/`,
  `bilbodata/handoff/*.py`. If a step wants to write elsewhere, stop.

## Definition of done
- `runs/bilbo1/weights/best.pt` exists.
- Dashboard showed the mAP curve climbing and live predictions improving.
- `eval.py` printed test-camera mAP split by day vs night. Expected honest
  result: solid daytime car/truck detection across weather; weaker at night
  (that's the footage, and it's the thing the next data round targets).
