# Bilbo Data — Backlog

Shifts pick the top **unblocked** item, ship it, check it off, push. Add what you spot.
Two tracks every shift: **A = data/findings**, **B = features and fixes**.

## Rules

- Nothing that appends to a file on `main` ships without a size guard. The 100 MiB
  cliff has wedged this repo twice. See `STATE.md`.
- Colour, re-identification and make/model recognition are **settled as not working**
  from this footage. Don't re-open them without new evidence.
- No routine builds or deploys. The 19:00 publisher does that.
- Race profiling is declined, permanently.

---

## P0 — pipeline health

- [x] **Restart the worker chain** — dead 2026-07-20 → 2026-08-15, 27 days. One
  unretried `gh workflow run` hit a transient HTTP 503 and the chain had no
  `schedule:` restarter to recover it. *(2026-08-15, shift 1: 6-hourly cron restarter
  + 5-attempt backoff on the relay; generation/run_seconds routed through defaulted
  env vars because `inputs` is empty on a schedule event.)*
- [x] **Unwedge the harvest chain** — `fp/crops_meta.cloud.jsonl` hit 108 MB on
  2026-07-23, every push rejected from then on, and the workflow was later disabled by
  hand so even its cron couldn't recover it. *(2026-08-15, shift 1: `fp/rotate_meta.py`
  rolls manifests to the `crops` release before the cliff; 353,440 lines archived;
  workflow re-enabled.)*
- [x] **Verify the stale-frame bug** *(2026-08-15, shift 1: `stale_check.py`. 99 of 100
  cameras returned 4 distinct frames from 4 fetches over 135s — zero staleness at the
  endpoint, at the pipeline's own sampling cadence. See SHIFT_LOG for what this does
  and doesn't rule out.)*
- [ ] **Re-run the stale check against live ingest, not just the endpoint.** The shift-1
  measurement proves the DOT serves fresh frames. It does **not** prove the counter
  stores distinct frames — the pipeline was dead when it ran, so there was no ingest to
  observe. Now that the worker is alive, check `vehicles.csv` for consecutive
  byte-identical observations per camera.
- [ ] **Re-run the stale check at night.** 135s of daytime traffic is the easiest
  possible case for distinguishing frames. A static 03:00 scene is the hard case and is
  where a cache would actually hide.
- [ ] **Deal with `vehicles.csv.legacy`** — 99.6 MiB on `main`, 430 KB under the cliff,
  written by nothing, and `git add`ed every 5 minutes by `worker.yml`. Harmless only as
  long as it never changes. It's a superseded pre-parquet rebuild artefact; the parquet
  archives in `data_vehicles/` are the real forever-record. Decide deliberately whether
  to drop it from `main` (it stays in git history either way) — don't delete an original
  by reflex. Same question for `counts.csv.legacy` (1.7 MiB, not urgent).
- [ ] **Prune the retired camera.** `C5-VWE-20_NB_at_Main_Street-Ex8` (`ddd3f06a…`)
  hard-404s. It's still in `cams_all.json` and `cam_resolution_census.csv`, so every
  sweep wastes a fetch on it and it likely has a dead static page. Sweep all 917 for
  404s at the same time rather than special-casing one.

## P1 — data and findings

- [ ] **Say what the HD tier can see that the rest can't.** 24 cameras at 1920×1080
  against 775 at 352×240. Speed and size estimates from the HD tier should be
  measurably better; nothing has quantified the gap. This is the project's most
  under-used asset.
- [ ] **Company catalogue → individual fingerprinting.** `company_catalogue.csv` maps
  fleet livery to company. Livery is legible where colour is not.
- [ ] **Corpus variety, not volume.** 358,440 crops is past `pace.py`'s 250k plateau
  target. More crops from the same cameras at the same hours buys little. Weight the
  harvester toward under-represented cameras, hours and vehicle classes.

## P2 — site and surface

- [ ] **Search Console verification** — BLOCKED ON PEDRO. bilbodata.com has never been
  verified, so the property runs blind and no SEO sweep can measure anything.
- [ ] **Give the camera pages something that changes.** Six consecutive SEO sweeps
  reported "surface unchanged" because the pipeline behind the pages was dead. With the
  worker alive again, confirm the pages actually move.
