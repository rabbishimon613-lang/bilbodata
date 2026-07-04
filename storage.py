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
os.makedirs(DATA_DIR, exist_ok=True)


def _con():
    return duckdb.connect()


def compact(include_today=False):
    """Move finished days from the hot CSV into data/<date>.parquet (zstd, lossless)."""
    if not os.path.exists(CSV):
        return []
    c = _con()
    c.execute("CREATE VIEW raw AS SELECT * FROM read_csv_auto('%s', header=true)" % CSV)
    today = dt.date.today().isoformat()
    dates = [str(r[0]) for r in c.execute(
        "SELECT DISTINCT CAST(ts AS DATE) d FROM raw ORDER BY d").fetchall()]
    written = []
    for d in dates:
        if d == today and not include_today:
            continue
        out = os.path.join(DATA_DIR, d + ".parquet")
        c.execute(
            "COPY (SELECT * FROM raw WHERE CAST(ts AS DATE)='%s') "
            "TO '%s' (FORMAT parquet, COMPRESSION zstd)" % (d, out))
        written.append((out, os.path.getsize(out)))
    return written


def _readings_sql():
    """Build a UNION over every parquet archive file + today's hot CSV."""
    parts = []
    if glob.glob(os.path.join(DATA_DIR, "*.parquet")):
        parts.append("SELECT * FROM read_parquet('%s/*.parquet', union_by_name=true)"
                     % DATA_DIR)
    if os.path.exists(CSV):
        parts.append("SELECT * FROM read_csv_auto('%s', header=true)" % CSV)
    return " UNION ALL BY NAME ".join(parts) if parts else "SELECT NULL WHERE false"


def query(sql):
    """Run SQL against a `readings` table spanning the entire archive + hot log."""
    c = _con()
    c.execute("CREATE VIEW readings AS " + _readings_sql())
    return c.execute(sql).fetchall()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "compact":
        for path, size in compact(include_today="--all" in sys.argv):
            print("archived %-40s %6.1f KB" % (os.path.basename(path), size / 1024))
    elif len(sys.argv) > 1:
        for row in query(sys.argv[1]):
            print(row)
    else:
        # default: show how much history we hold
        r = query("SELECT count(*) n, count(DISTINCT cam_id) cams, "
                  "min(ts) first_ts, max(ts) last_ts FROM readings")[0]
        print("readings=%d  cameras=%d  span=%s -> %s" % r)
