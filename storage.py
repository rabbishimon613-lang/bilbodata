#!/usr/bin/env python3
"""Packed storage + full-history query layer for Bilbo Data.

Design (see DATA.md):
  - counts.csv          = today's HOT log (append-friendly, small)
  - data/<date>.parquet = compressed cold ARCHIVE, one file per day, LOSSLESS
  - every reading is kept forever at full 1-minute detail — nothing is dropped.

`compact()` rolls finished days out of the hot log into zstd-compressed Parquet.
`query(sql)` runs DuckDB SQL over the archive + today's hot log as one table
called `readings`, so any analysis spans all cameras and all of history at once.
"""
import os, glob, sys, datetime as dt
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "counts.csv")
DATA_DIR = os.path.join(HERE, "data")
# Per-vehicle tags get their OWN forever-archive, same hot->cold->query design.
VEH_CSV = os.path.join(HERE, "vehicles.csv")
VEH_DIR = os.path.join(HERE, "data_vehicles")
# Reconstructed journeys (cross-camera trips) — the third forever table.
TRIPS_CSV = os.path.join(HERE, "trips.csv")
TRIPS_DIR = os.path.join(HERE, "data_trips")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(VEH_DIR, exist_ok=True)
os.makedirs(TRIPS_DIR, exist_ok=True)


def _con():
    return duckdb.connect()


def _compact(csv_path, archive_dir, include_today, drop_cols=None):
    """Move finished days from a hot CSV into <archive_dir>/<date>.parquet (zstd,
    lossless) AND prune those days out of the hot CSV, so the hot log only ever
    holds unarchived days and archive+hot never double-count. `drop_cols` are
    excluded from the ARCHIVE only (e.g. fingerprints, useful only while fresh)."""
    if not os.path.exists(csv_path):
        return []
    c = _con()
    # read_csv (not _auto) with an explicit dialect + strict_mode=false: the hot
    # logs carry mixed CRLF/LF line endings (two writers), which makes the auto
    # dialect sniffer bail out entirely — that once silently blocked compaction
    # until vehicles.csv outgrew GitHub's 100 MB push limit.
    c.execute("CREATE VIEW raw AS SELECT * FROM read_csv('%s', header=true, "
              "delim=',', strict_mode=false)" % csv_path)
    # Only exclude drop_cols that actually exist (schema varies over time, e.g. the
    # old `emb` fingerprint column is gone in the vehicles-only rebuild).
    have = {r[0] for r in c.execute("DESCRIBE raw").fetchall()}
    present_drop = [d for d in (drop_cols or []) if d in have]
    sel = "* EXCLUDE (%s)" % ", ".join(present_drop) if present_drop else "*"
    today = dt.date.today().isoformat()
    dates = [str(r[0]) for r in c.execute(
        "SELECT DISTINCT CAST(ts AS DATE) d FROM raw ORDER BY d").fetchall()]
    written, archived = [], []
    for d in dates:
        if d == today and not include_today:
            continue
        out = os.path.join(archive_dir, d + ".parquet")
        c.execute(
            "COPY (SELECT %s FROM raw WHERE CAST(ts AS DATE)='%s') "
            "TO '%s' (FORMAT parquet, COMPRESSION zstd)" % (sel, d, out))
        written.append((out, os.path.getsize(out)))
        archived.append(d)
    if archived:                                   # prune archived days from the hot log
        keep = " AND ".join("CAST(ts AS DATE)<>'%s'" % d for d in archived)
        tmp = csv_path + ".tmp"
        c.execute("COPY (SELECT * FROM raw WHERE %s) TO '%s' (FORMAT csv, HEADER)"
                  % (keep, tmp))
        os.replace(tmp, csv_path)
    return written


def compact(include_today=False):
    return _compact(CSV, DATA_DIR, include_today)


def compact_vehicles(include_today=False):
    """Same hot->cold roll for the per-vehicle log: finished days -> Parquet.
    Keeps every tag forever, but DROPS the appearance fingerprint (`emb`) from the
    archive — it's only useful for matching within hours, and keeping it forever
    would bloat the store. Every other tag is preserved byte-for-byte."""
    return _compact(VEH_CSV, VEH_DIR, include_today, drop_cols=["emb"])


def compact_trips(include_today=False):
    """Roll completed journeys into the forever archive (data_trips/<date>.parquet).
    Keyed on first_ts, so a trip lands in the day it started."""
    if not os.path.exists(TRIPS_CSV):
        return []
    # trips.csv has no `ts` column; _compact keys on the first column named ts.
    # Give it one via a view alias by temporarily reading first_ts AS ts.
    c = _con()
    c.execute("CREATE VIEW traw AS SELECT *, first_ts AS ts FROM read_csv_auto('%s', header=true)"
              % TRIPS_CSV)
    today = dt.date.today().isoformat()
    dates = [str(r[0]) for r in c.execute(
        "SELECT DISTINCT CAST(first_ts AS DATE) d FROM traw ORDER BY d").fetchall()]
    written, archived = [], []
    for d in dates:
        if d == today and not include_today:
            continue
        out = os.path.join(TRIPS_DIR, d + ".parquet")
        c.execute("COPY (SELECT * EXCLUDE (ts) FROM traw WHERE CAST(first_ts AS DATE)='%s') "
                  "TO '%s' (FORMAT parquet, COMPRESSION zstd)" % (d, out))
        written.append((out, os.path.getsize(out)))
        archived.append(d)
    if archived:
        keep = " AND ".join("CAST(first_ts AS DATE)<>'%s'" % d for d in archived)
        tmp = TRIPS_CSV + ".tmp"
        c.execute("COPY (SELECT * EXCLUDE (ts) FROM traw WHERE %s) TO '%s' (FORMAT csv, HEADER)"
                  % (keep, tmp))
        os.replace(tmp, TRIPS_CSV)
    return written


def _union_sql(archive_dir, hot_glob):
    parts = []
    if glob.glob(os.path.join(archive_dir, "*.parquet")):
        parts.append("SELECT * FROM read_parquet('%s/*.parquet', union_by_name=true)"
                     % archive_dir)
    for hot in sorted(glob.glob(hot_glob)):
        parts.append("SELECT * FROM read_csv_auto('%s', header=true)" % hot)
    return " UNION ALL BY NAME ".join(parts) if parts else "SELECT NULL WHERE false"


def _readings_sql():
    """UNION over every counts archive + today's hot CSV (+ any shard logs)."""
    return _union_sql(DATA_DIR, os.path.join(HERE, "counts*.csv"))


def _vehicles_sql():
    """UNION over every vehicle archive + today's hot per-vehicle log(s)."""
    return _union_sql(VEH_DIR, os.path.join(HERE, "vehicles*.csv"))


def _trips_sql():
    """UNION over every trips archive + today's hot trips log."""
    return _union_sql(TRIPS_DIR, os.path.join(HERE, "trips*.csv"))


def query(sql):
    """Run SQL against three forever tables, each spanning archive + hot log:
      readings  — aggregate per-camera/minute counts
      vehicles  — every individually tagged vehicle sighting
      trips     — every reconstructed cross-camera journey
    All of history, one query."""
    c = _con()
    c.execute("CREATE VIEW readings AS " + _readings_sql())
    c.execute("CREATE VIEW vehicles AS " + _vehicles_sql())
    c.execute("CREATE VIEW trips AS " + _trips_sql())
    return c.execute(sql).fetchall()


def vehicle_rows(since_epoch=None):
    """Every tagged vehicle across ALL history (archive + hot), as dicts.
    `since_epoch` pushes a time filter into DuckDB so 24h views stay fast even
    as the archive grows to millions of rows. This is what the analytics read,
    so aggregation accumulates forever instead of resetting to today's hot log."""
    c = _con()
    c.execute("CREATE VIEW vehicles AS " + _vehicles_sql())
    where = ""
    if since_epoch is not None:
        where = " WHERE TRY_CAST(epoch AS DOUBLE) >= %f" % float(since_epoch)
    try:
        cur = c.execute("SELECT * FROM vehicles" + where)
    except Exception:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "compact":
        inc = "--all" in sys.argv
        failed = False
        # one table's failure must never block the others (a counts.csv parse
        # error once stopped vehicles.csv from ever being archived)
        for label, fn in (("counts", compact), ("vehicles", compact_vehicles),
                          ("trips", compact_trips)):
            try:
                for path, size in fn(include_today=inc):
                    print("archived %-8s %-28s %6.1f KB"
                          % (label, os.path.basename(path), size / 1024))
            except Exception as e:
                failed = True
                print("COMPACT FAILED for %s: %s" % (label, e), file=sys.stderr)
        if failed:
            sys.exit(1)
    elif len(sys.argv) > 1:
        for row in query(sys.argv[1]):
            print(row)
    else:
        # default: show how much history we hold across all three tables
        r = query("SELECT count(*) n, count(DISTINCT cam_id) cams, "
                  "min(ts) first_ts, max(ts) last_ts FROM readings")[0]
        print("readings=%d  cameras=%d  span=%s -> %s" % r)
        try:
            v = query("SELECT count(*) FROM vehicles")[0][0]
            t = query("SELECT count(*) FROM trips")[0][0]
            print("vehicles=%d  trips=%d" % (v, t))
        except Exception:
            pass
