# Bilbo Data — how the data & storage work

Reference for how readings are captured, stored, and queried. Principle:
**keep every reading forever at full 1-minute detail, but store it tiny.**
Nothing is downsampled, averaged-away, or dropped.

> **2026-07-12, fingerprint rebuild:** a second data plane now exists alongside
> the counts. `fp/crops_meta.cloud.jsonl` (manifest, on `main`) describes
> vehicle close-ups whose IMAGE files live in the `crops` GitHub Release —
> never in git. Labels: `fp/labels_auto.cloud.jsonl` (teacher, class-only) and
> `fp/labels_gold.jsonl` (Claude gold bench: make/model/color/company/
> plate-state/bus, or abstain). Trained-head telemetry:
> `training/heads_status.json`. The living fleet catalogue:
> `company_catalogue.csv`. See `fp/README.md` for the loop.

---

## 1. What a "reading" is

The cameras' *images are never stored.* Each frame is analyzed and thrown away;
only the derived **counts** are kept. One reading = one camera, one minute:

```
ts, cam_id, person, bike, car, moto, bus, truck, veh_total, <color tallies>
```

Values are averages of ~15–25 frames sampled during that minute (the finest
grain in the system is 1 minute). ~20 bytes of signal from ~20 KB of pixels —
a ~1000× reduction before anything else happens.

---

## 2. Three forever tables, each hot→cold

Everything is kept forever. There are three parallel logs, all on the same
hot-CSV → cold-Parquet design:

| Table | Hot (today) | Cold (archive) | What one row is |
|-------|-------------|----------------|-----------------|
| **readings** | `counts.csv` | `data/<date>.parquet` | one camera, one minute: class counts + colour tallies |
| **vehicles** | `vehicles.csv` | `data_vehicles/<date>.parquet` | one tagged vehicle: class, size, aspect, colour, heading, moving, epoch (+ a short-lived appearance fingerprint `emb`, kept in hot only) |
| **trips** | `trips.csv` | `data_trips/<date>.parquet` | one reconstructed cross-camera journey: type, colour, match confidence, and the full ordered path of (camera, time, lat/lon) stops |

- New rows append to the **hot log** all day (cheap to append to).
- Once a day finishes, `storage.py compact` rolls it into a **Parquet archive**
  and prunes it from the hot log, so hot only ever holds ~1 day and archive+hot
  never double-count.
- Parquet is columnar + compressed: measured **~17× smaller than CSV, lossless.**
  The one deliberate exception: the per-vehicle fingerprint (`emb`) is dropped on
  archive — it only helps match cars within hours, so keeping it forever would
  bloat the store. That's why **trips are persisted as their own records**: the
  fingerprints that built them are gone from the archive, so the journey itself
  is the durable artifact.

Nothing else is ever thinned. "Small" comes from *format*, not from *discarding data*.

---

## 3. Querying — all of history as one table

`storage.py` exposes three virtual tables — **`readings`**, **`vehicles`**, and
**`trips`** — each the UNION of its Parquet archive **plus** today's hot CSV.
DuckDB reads them together, so any query spans all cameras and all of history at
full resolution:

```bash
python3 storage.py "SELECT name, avg(car) FROM readings GROUP BY name ORDER BY 2 DESC"
python3 storage.py "SELECT color, count(*) FROM vehicles GROUP BY color ORDER BY 2 DESC"
python3 storage.py "SELECT type, avg(cams), count(*) FROM trips GROUP BY type"
python3 storage.py                     # summary: readings / vehicles / trips totals
python3 storage.py compact             # archive finished days for all three (run nightly)
python3 storage.py compact --all       # include today (testing only)
```

DuckDB is an in-process engine — no server, no account, free. It can also read
the Parquet files directly from object storage later without changing queries.

---

## 4. Size at full scale (all 917 NYC cameras, full 1-min detail, nothing dropped)

- Raw text CSV: ~198 MB/day → unworkable
- Packed Parquet (measured ~17× shrink, lossless): **~10–12 MB/day**
- → ~**4 GB per year**, full fidelity, every camera, every minute, forever.

That fits in free, no-credit-card storage (GitHub repo/releases, or a free DB
tier) with lots of headroom — and stays instantly queryable the whole time.

---

## 5. How it scales across machines (see counter sharding)

At 900 cameras the counter runs **sharded**: `PEDCOUNT_SHARD_COUNT=20` splits the
camera list across up to 20 free parallel GitHub runners. Each shard writes its
own hot log (`counts_shard<i>.csv`) so runners never collide; a compaction step
merges the day's shards into one `data/<date>.parquet`. Compute is cheap
(~75 ms/camera); storage is the real constraint, and Parquet is the answer.

---

## 6. When (and only when) a signup is needed

Everything above is free and account-free — files live in the repo, DuckDB is a
library. A hosted database (Supabase / Turso, both no-credit-card) becomes useful
**only** if the public website needs to run live SQL over the full archive itself.
Until then, the Parquet-in-repo + DuckDB setup covers capture, full-history
storage, and analysis with zero signups.

### Optional Turso mirror (wired, off by default)

`turso_sync.py` mirrors the three tables into a Turso (libsql) database so the
site can run live SQL without shipping Parquet. It is **fail-open**: with the env
vars unset it is a complete no-op, and if the DB is ever unreachable the write is
logged and skipped — the CSV/Parquet pipeline stays authoritative and the counter
never stalls. To turn it on, add two GitHub Actions **secrets** (never commit
them — this repo is public):

    TURSO_DATABASE_URL   libsql://<db>-<org>.aws-<region>.turso.io
    TURSO_AUTH_TOKEN     <token from `turso db tokens create <db>`>

`worker.yml` / `count.yml` already pass them through. From then on every minute's
`readings` + tagged `vehicles` (minus the ephemeral `emb` fingerprint) and every
reconstructed `trip` land in Turso. It talks the libsql HTTP protocol directly
over urllib3, so there is no extra dependency. One-time load of existing history:

    python turso_sync.py init       # create the schema
    python turso_sync.py backfill    # push the current archive + hot logs
    python turso_sync.py status      # connectivity check + row counts
