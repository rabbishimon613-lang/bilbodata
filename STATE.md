# Bilbo Data — STATE

*Read first, written last, every run. Keep this to a screen or two — detail belongs
in `SHIFT_LOG.md`, one-liners in `DIARY.md`, backlog in `FEATURE_BACKLOG.md`.*

Last updated: **2026-08-15** (product shift 1)

---

## What this is

NYC DOT traffic-camera vision. 917 cameras, sampled continuously, counted and tagged.
~917 static camera pages live at **bilbodata.com** (the canonical host).

## Live systems

| Chain | Trigger | State | Notes |
|---|---|---|---|
| **worker** | dispatch + 6-hourly cron | **restarted 2026-08-15** | the vehicle pipeline: samples, counts, tags, commits |
| **harvest** | dispatch + 6-hourly cron | **re-enabled 2026-08-15** | crop harvester feeding the fingerprint training set |
| **train-gate** | cron `*/30` | healthy throughout | rotates 5 Kaggle accounts, fires training bursts |
| publisher | 19:00 daily | external | the only thing permitted to build + deploy |

Data never goes to `main` in bulk. Crops and rolled manifests go to the **`crops`
release**; weights go to the **`models`** release; day archives go to
`data/` + `data_vehicles/` parquet.

## The 100 MiB rule — the thing that keeps killing this project

GitHub hard-rejects any push containing a file over 100 MiB, and it has now wedged
this repo **twice**:

- `vehicles.csv` outgrew it once (noted in `storage.py`'s own comments — a CSV
  dialect bug had silently stopped compaction).
- `fp/crops_meta.cloud.jsonl` reached 108 MB on 2026-07-23 and killed the entire
  harvest chain for 23 days.

Both hot logs and both cloud manifests now have guards. **Anything appended to and
committed on `main` needs one.** Current headroom:

| File | Size on main | Guard |
|---|---|---|
| `fp/crops_meta.cloud.jsonl` | 1.4 MB | rolls to `crops` release at 50 MiB (`fp/rotate_meta.py`) |
| `fp/labels_auto.cloud.jsonl` | 3.3 MB | same |
| `vehicles.csv` | 76 MiB → self-heals on next run | `compact --all` at 80 MB, plus `compact` each generation start |
| `counts.csv` | 3.8 MB | same |
| `vehicles.csv.legacy` | **99.6 MiB — 430 KB under the cliff** | **none. Static leftover, never written. See backlog.** |

Two things read the crop manifest's line count as corpus size (`gate.yml`'s training
bank, `fp/pace.py`'s plateau clock). Both now go through
`fp/rotate_meta.py --total crops`, which is monotonic across rotations. **Never
reintroduce a bare `wc -l` on a rotated file** — it reads as the corpus collapsing and
silently stops all training bursts.

## What the cameras can actually see

Settled, do not re-litigate: **count, type, size, speed and tracking work. Colour,
re-identification and make/model do not.** The ceiling is per-camera footage quality,
and the fleet is not uniform — 775 of 917 cameras are 352×240.

**The HD tier is 24 cameras, not 25.** `C5-VWE-20_NB_at_Main_Street-Ex8` (Queens,
`ddd3f06a…`) returns a hard 404 and has been retired by DOT. The census CSV still
lists it.

Crop corpus: **358,440 crops**, past the 250k "first plateau" target in `pace.py`.
More volume is no longer the constraint — variety is.

## Open, and blocked on Pedro

- **bilbodata.com is still unverified in Google Search Console.** The property has run
  blind for the whole life of the SEO routine. Nothing on this side can fix it; it
  needs Pedro to complete verification. Say it every shift until it's done.

---

## Files that matter

- `BUILD.md` / `DATA.md` / `DEPLOY.md` — how the site, storage and deploys work
- `SEO-LOG.md` — the nightly sweep's long log
- `SHIFT_LOG.md` — product-shift history + the handoff
- `FEATURE_BACKLOG.md` — what's queued
- `DIARY.md` — one line per run
