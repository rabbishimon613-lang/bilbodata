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
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(VEH_DIR, exist_ok=True)


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
    c.execute("CREATE VIEW raw AS SELECT * FROM read_csv_auto('%s', header=true)" % csv_path)
    sel = "* EXCLUDE (%s)" % ", ".join(drop_cols) if drop_cols else "*"
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


def query(sql):
    """Run SQL against `readings` (aggregate counts) AND `vehicles` (per-vehicle),
    each spanning the entire archive + hot log — all of history as one table."""
    c = _con()
    c.execute("CREATE VIEW readings AS " + _readings_sql())
    c.execute("CREATE VIEW vehicles AS " + _vehicles_sql())
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
        for path, size in compact(include_today=inc):
            print("archived counts   %-28s %6.1f KB" % (os.path.basename(path), size / 1024))
        for path, size in compact_vehicles(include_today=inc):
            print("archived vehicles %-28s %6.1f KB" % (os.path.basename(path), size / 1024))
    elif len(sys.argv) > 1:
        for row in query(sys.argv[1]):
            print(row)
    else:
        # default: show how much history we hold
        r = query("SELECT count(*) n, count(DISTINCT cam_id) cams, "
                  "min(ts) first_ts, max(ts) last_ts FROM readings")[0]
        print("readings=%d  cameras=%d  span=%s -> %s" % r)
