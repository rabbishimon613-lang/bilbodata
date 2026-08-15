# Bilbo Data — Product Shift Log

Newest last. Every shift does two tracks and ends with an explicit handoff.

---

## Shift 1 — 2026-08-15 (Saturday, 15:00 local)

First product shift on this project. `STATE.md`, `DIARY.md`, `SHIFT_LOG.md` and
`FEATURE_BACKLOG.md` did not exist; created them in the Roman Maps shape per the brief.

Per the rotation Saturday is Bilbo until the pipeline is alive again, and the brief is
explicit that **the pipeline IS the shift** — so both tracks went into it.

### The diagnosis the last six sweeps were carrying was wrong

The standing hypothesis was that a workflow authenticated with the default
`GITHUB_TOKEN` can't trigger another workflow, which would explain why the two
self-perpetuating chains died while the cron-triggered one lived. It costs ten minutes
to test, so I tested it first: **both chains already relay via a stored `WORKER_PAT`,
and always did.** That was never the cause.

The asymmetry was real, but it was two unrelated failures that happened to look alike:

**worker — dead 2026-07-20T00:29Z, 27 days.** The chain's last generation succeeded.
Its relay step ran, had the PAT, called `gh workflow run`, and got
`HTTP 503: No server is currently available to service your request`. The step was a
single unretried attempt ending in `|| echo "relay dispatch failed"`, so it shrugged and
exited 0. And `worker.yml` had **no `schedule:` trigger at all** — harvest.yml had a
6-hourly restarter from the start, worker never did. One transient 503, no retry, no
restarter: the whole vehicle pipeline was down for 27 days on a five-second network blip.

**harvest — dead 2026-07-23T17:31Z.** Different cause entirely.
`fp/crops_meta.cloud.jsonl` reached 108.38 MB and GitHub rejected the push:
*"exceeds GitHub's file size limit of 100.00 MB"*. Three retries, all rejected, every
generation after that too. The file sat on `main` at 104,615,046 bytes — **99.77 MiB,
about 430 KB under the 100 MiB limit** — so every possible append was permanently
unpushable. The workflow was then **`disabled_manually`**, which is why not one of its
~92 scheduled restarts since 23 July ever fired. `gh workflow list` showed it in three
seconds; nothing had looked.

Worth noting `storage.py`'s own comments record this same cliff eating `vehicles.csv`
once before. It is the single most expensive recurring failure in this project.

### Track B — features and fixes

- **`fp/rotate_meta.py`** (new). Rolls the append-only cloud manifests into the `crops`
  release before they reach the cliff, keeping a 5,000-line tail on `main`. Verified on
  synthetic data first, then run for real: 353,440 lines → a 15.9 MB gzip in the release,
  5,000 kept, `353,440 + 5,000 = 358,440` matching the original exactly, contiguous
  across the boundary, gzip integrity checked. `main`'s copy went 104.6 MB → 1.4 MB.
  The full pre-rotation file also remains in git history regardless of the release copy.
- **The counter trap.** Rotation would have quietly broken the two things that read the
  manifest's raw line count as corpus size — `gate.yml`'s training bank and `pace.py`'s
  plateau clock. Both would have seen the corpus collapse from 358,440 to 5,000 and
  never recover, and the Kaggle bursts would have stopped firing with no error anywhere.
  Both now read `rotate_meta.py --total crops`, which is monotonic across rotations and
  equals the old line count exactly for every pre-rotation stamp, so the per-account
  `last_count` stamps in `kaggle/rotation.json` stay valid. Verified: `pace.py` still
  reads 358,440, matching the pre-rotation `pace.json` committed on main.
- **`harvest.yml`** — rotation + release upload wired in ahead of the commit step, and a
  failed upload can't fail the run.
- **`worker.yml`** — added the missing 6-hourly `schedule:` restarter (offset to `:43`
  so it doesn't queue against harvest's `:17`; concurrency makes it a no-op whenever a
  generation is alive). Routed `generation`/`run_seconds` through defaulted env vars,
  because `inputs` is empty on a schedule event and `${{ inputs.run_seconds }}` would
  have expanded to nothing and broken `END=$(( now + ))` on every cron restart — that
  bug would have made the new restarter useless.
- **Relay retries** on both chains: 5 attempts, 15s incremental backoff, tested against
  first-try-success / transient-failure / total-failure. Exhaustion warns and exits 0,
  leaving the cron as the backstop, so a relay failure can never fail a good generation.
- Re-enabled the `harvest` workflow. All five workflows now report `active`.

### Track A — data

- **The stale-frame check is clean, and that is a real answer.** New `stale_check.py`
  fetched 100 cameras (all 25 census HD cameras + a seeded random 75 of the 352×240
  majority — the sample fixed *before* any fetching, so it can't have been drawn around
  a result) four times over a 135-second window in mid-afternoon NYC traffic.
  **99 of 100 returned 4 distinct frames from 4 fetches. Zero repeats, zero staleness.**
  Round spacing was 45s, deliberately under the pipeline's own ~60s sampling cadence,
  so this tests the cadence the pipeline actually uses.

  **What it does not show, and I'm not going to claim it does:** the pipeline was dead
  while this ran, so this measures the DOT endpoint, not our ingest. It doesn't rule out
  the counter storing duplicate observations further down. And 135 seconds of daytime
  traffic is the *easiest* case for telling two frames apart — a still 03:00 scene is
  where a cache would actually hide. Both follow-ups are in the backlog rather than
  written up as a finding.

- **One of the HD "good seats" is gone.** `C5-VWE-20_NB_at_Main_Street-Ex8` (Queens,
  `ddd3f06a…`) returns a hard 404 on five consecutive attempts — retired by DOT, not a
  blip. **The HD tier is 24 cameras, not 25.** It's still listed in `cams_all.json` and
  `cam_resolution_census.csv`.

- **The crop corpus is past its own target.** 358,440 crops against `pace.py`'s 250,000
  "first plateau". More volume from the same cameras at the same hours buys very little
  now; variety is the constraint. Backlogged.

### Standing, and blocked on Pedro

**bilbodata.com is still unverified in Google Search Console.** The property has run
blind for the entire life of the SEO routine. Nothing on this side can fix it.

### Housekeeping

The working tree carried ~40 untracked files predating this shift (research scripts,
`dot_crops/`, `gallery/`, `handoff/`, `ad/`). I did not sweep them — the contract says
stage your own work by explicit path, never `git add -A`. I did fold in one orphaned
`.gitignore` change (ignoring `.env`) since it's unambiguously correct and reduces the
debt. The rest is still there for the watchdog.

### Next shift should pick up

- **Track A:** re-run the stale check two ways now that the worker is alive — against
  live ingest (`vehicles.csv` for consecutive byte-identical observations per camera,
  which is the half this shift could not test), and **at night**, which is the hard case.
  Then the real open question: quantify what the 24 HD cameras can see that the 775
  352×240 ones can't. That's the project's most under-used asset and nothing has measured it.
- **Track B:** decide deliberately what to do about `vehicles.csv.legacy` — 99.6 MiB on
  `main`, 430 KB under the cliff, written by nothing, `git add`ed every 5 minutes. It's
  a superseded pre-parquet artefact and the parquet archives are the real forever-record,
  but it's still an original, so decide rather than reflexively delete. Then sweep all
  917 cameras for 404s and prune the retired ones.
- **Verify first, before anything else:** confirm the worker chain actually relayed and
  is still running (`gh run list --workflow=worker.yml`), and that harvest's cron fired
  and pushed a manifest. If either is dead again, that is the shift.

---
