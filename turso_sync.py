#!/usr/bin/env python3
"""Optional live mirror of the counting data into a Turso (libsql) database.

Fail-open and zero-config BY DESIGN. If TURSO_DATABASE_URL / TURSO_AUTH_TOKEN
are not set, every function here is a no-op, so the counter runs exactly as it
always has with files-in-repo as the source of truth (see DATA.md sections 5-6).
When the two vars ARE present (supplied as GitHub Actions secrets), each minute's
readings + tagged vehicles and every reconstructed trip are pushed into Turso so
the public site can run live SQL over the full archive without shipping Parquet.

No new dependency and no secret ever hardcoded:
  - talks the libsql/Hrana HTTP protocol (POST /v2/pipeline) over the same
    urllib3 the project already uses;
  - the URL + token come ONLY from the environment.

Any DB hiccup is swallowed (logged, never raised) so a Turso outage can never
stall or crash the counter — the CSV/Parquet pipeline stays authoritative.
"""
import os, sys, json, csv, urllib3

_URL = os.environ.get("TURSO_DATABASE_URL", "").strip()
_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "").strip()

CHUNK = 64   # statements per HTTP round-trip; keeps request bodies modest

# Column order for each table — must match the CSV writers in counter.py and the
# trips.csv header. `emb` is intentionally NOT mirrored: like the Parquet archive
# (storage.compact_vehicles), the appearance fingerprint is short-lived matching
# state, not something worth keeping forever in the query DB.
READINGS_COLS = ["ts", "cam_id", "name", "person", "bike", "car", "moto", "bus",
                 "truck", "veh_total", "red", "blue", "green", "yellow", "white",
                 "black", "silver"]
VEHICLE_COLS = ["ts", "epoch", "cam_id", "name", "cls", "box_w", "box_h",
                "area_px", "aspect", "color", "frames", "heading",
                "px_per_frame", "moving"]
TRIP_COLS = ["trip_id", "first_ts", "last_ts", "type", "color", "width_ft",
             "n_stops", "cams", "span_min", "match", "confidence", "path"]


def enabled():
    return bool(_URL and _TOKEN)


def _endpoint():
    u = _URL
    for a, b in (("libsql://", "https://"), ("wss://", "https://"),
                 ("ws://", "http://"), ("http://", "http://"), ("https://", "https://")):
        if u.startswith(a):
            u = b + u[len(a):]
            break
    else:
        u = "https://" + u
    return u.rstrip("/") + "/v2/pipeline"


def _pool():
    """Honour an outbound HTTPS proxy + custom CA if the environment sets them
    (dev sandboxes do); in CI neither is set, so this is a plain direct pool."""
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    kw = {"cert_reqs": "CERT_REQUIRED"}
    if ca:
        kw["ca_certs"] = ca
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        return urllib3.ProxyManager(proxy, **kw)
    return urllib3.PoolManager(**kw)


_HTTP = None


def _http():
    global _HTTP
    if _HTTP is None:
        _HTTP = _pool()
    return _HTTP


def _arg(v):
    """Encode a Python value as a Hrana typed argument."""
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        v = v.item()          # unwrap numpy scalars (int64/float64/bool_) to native
    if v is None or v == "":
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _pipeline(stmts):
    """Run [(sql, args), ...] in one round-trip. Raises on transport/SQL error."""
    reqs = [{"type": "execute",
             "stmt": {"sql": s, "args": [_arg(a) for a in (args or [])]}}
            for s, args in stmts]
    reqs.append({"type": "close"})
    body = json.dumps({"requests": reqs}).encode()
    r = _http().request("POST", _endpoint(), body=body, timeout=20.0,
                        headers={"Authorization": "Bearer " + _TOKEN,
                                 "Content-Type": "application/json"})
    if r.status != 200:
        raise RuntimeError("http %d: %s" % (r.status, r.data[:300]))
    out = json.loads(r.data.decode())
    for res in out.get("results", []):
        if res.get("type") == "error":
            raise RuntimeError("sql: %s" % res.get("error", {}).get("message"))
    return out


_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS readings (
        ts TEXT, cam_id TEXT, name TEXT,
        person INTEGER, bike INTEGER, car INTEGER, moto INTEGER, bus INTEGER,
        truck INTEGER, veh_total INTEGER,
        red INTEGER, blue INTEGER, green INTEGER, yellow INTEGER, white INTEGER,
        black INTEGER, silver INTEGER,
        PRIMARY KEY (ts, cam_id)
    )""",
    """CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, epoch REAL, cam_id TEXT, name TEXT, cls TEXT,
        box_w INTEGER, box_h INTEGER, area_px INTEGER, aspect REAL, color TEXT,
        frames INTEGER, heading REAL, px_per_frame REAL, moving INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS vehicles_epoch ON vehicles(epoch)",
    "CREATE INDEX IF NOT EXISTS vehicles_cam ON vehicles(cam_id)",
    """CREATE TABLE IF NOT EXISTS trips (
        trip_id TEXT PRIMARY KEY,
        first_ts TEXT, last_ts TEXT, type TEXT, color TEXT, width_ft REAL,
        n_stops INTEGER, cams INTEGER, span_min REAL, match REAL,
        confidence REAL, path TEXT
    )""",
]

_ready = False


def _ensure():
    global _ready
    if not _ready:
        _pipeline([(s, []) for s in _SCHEMA])
        _ready = True


def _chunks(rows):
    for i in range(0, len(rows), CHUNK):
        yield rows[i:i + CHUNK]


def _insert(sql, rows):
    _ensure()
    for batch in _chunks(rows):
        _pipeline([(sql, r) for r in batch])


def sync_readings(rows):
    """Mirror this minute's per-camera averaged rows (one per camera)."""
    if not enabled() or not rows:
        return
    sql = ("INSERT OR REPLACE INTO readings (%s) VALUES (%s)"
           % (",".join(READINGS_COLS), ",".join(["?"] * len(READINGS_COLS))))
    try:
        _insert(sql, [list(r)[:len(READINGS_COLS)] for r in rows])
    except Exception as e:
        print("  ! turso readings:", e)


def sync_vehicles(rows):
    """Mirror this minute's tagged vehicles. Accepts rows WITH or without the
    trailing `emb` field; only the first len(VEHICLE_COLS) values are stored."""
    if not enabled() or not rows:
        return
    sql = ("INSERT INTO vehicles (%s) VALUES (%s)"
           % (",".join(VEHICLE_COLS), ",".join(["?"] * len(VEHICLE_COLS))))
    try:
        _insert(sql, [list(r)[:len(VEHICLE_COLS)] for r in rows])
    except Exception as e:
        print("  ! turso vehicles:", e)


def sync_trips(rows):
    """Upsert reconstructed journeys (trip_id is the key, so a refined trip
    overwrites its earlier version)."""
    if not enabled() or not rows:
        return
    sql = ("INSERT OR REPLACE INTO trips (%s) VALUES (%s)"
           % (",".join(TRIP_COLS), ",".join(["?"] * len(TRIP_COLS))))
    try:
        _insert(sql, [list(r)[:len(TRIP_COLS)] for r in rows])
    except Exception as e:
        print("  ! turso trips:", e)


def sync_trips_file(path):
    """Push every row of a trips.csv (the whole file is small)."""
    if not enabled() or not os.path.exists(path):
        return
    with open(path) as f:
        rows = [[row.get(c, "") for c in TRIP_COLS] for row in csv.DictReader(f)]
    sync_trips(rows)


# --- CLI: init / smoke test / one-shot backfill of existing history ----------

def _backfill():
    """Load the existing archive+hot logs into Turso once (idempotent)."""
    import storage
    _ensure()
    rd = storage.query("SELECT %s FROM readings" % ",".join(READINGS_COLS))
    sync_readings([list(r) for r in rd])
    print("backfilled readings: %d" % len(rd))
    vh = storage.query("SELECT %s FROM vehicles" % ",".join(VEHICLE_COLS))
    sync_vehicles([list(r) for r in vh])
    print("backfilled vehicles: %d" % len(vh))
    tp = storage.query("SELECT %s FROM trips" % ",".join(TRIP_COLS))
    sync_trips([list(r) for r in tp])
    print("backfilled trips:    %d" % len(tp))


if __name__ == "__main__":
    if not enabled():
        print("turso: DISABLED (set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)")
        sys.exit(0)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "init":
        _ensure()
        print("turso: schema ready at", _endpoint())
    elif cmd == "backfill":
        _backfill()
    else:  # status: prove connectivity + show row counts
        _ensure()
        for t in ("readings", "vehicles", "trips"):
            n = _pipeline([("SELECT count(*) FROM %s" % t, [])])
            val = n["results"][0]["response"]["result"]["rows"][0][0]["value"]
            print("turso %-9s rows=%s" % (t, val))
