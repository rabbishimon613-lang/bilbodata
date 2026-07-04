# Bilbo Data — how the data & storage work

Reference for how readings are captured, stored, and queried. Principle:
**keep every reading forever at full 1-minute detail, but store it tiny.**
Nothing is downsampled, averaged-away, or dropped.

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

## 2. The two storage tiers

| Tier | File | Role | Format |
|------|------|------|--------|
| **Hot** | `counts.csv` | today's readings, append-friendly | text CSV |
| **Cold** | `data/<date>.parquet` | every finished day, one file | Parquet + zstd |

- New readings append to the **hot log** all day (cheap to append to).
- Once a day finishes, `storage.py compact` rolls it into a **Parquet archive**
  file and it leaves the hot log. The hot log therefore only ever holds ~1 day.
- Parquet is columnar + compressed: measured **~17× smaller than CSV, lossless.**
  Every reading is still there, byte-for-byte recoverable.

Nothing is ever thinned. "Small" comes from *format*, not from *discarding data*.

---

## 3. Querying — all of history as one table

`storage.py` exposes a virtual table called **`readings`** that is the UNION of
every Parquet archive file **plus** today's hot CSV. DuckDB reads them together
as a single table, so any query spans all cameras and all of history at full
resolution:

```bash
python3 storage.py "SELECT name, avg(car) FROM readings GROUP BY name ORDER BY 2 DESC"
python3 storage.py                     # summary: rows / cameras / time span
python3 storage.py compact             # archive finished days (run nightly)
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
