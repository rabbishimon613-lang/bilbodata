#!/usr/bin/env python3
"""
Build the SkyLine subway layer — the track geometry under the city, with each
stretch tagged by how it actually runs: deep tunnel, open cut, at grade, or
elevated. One file feeds both the tunnel drawing and the moving trains.

Track geometry comes from the MTA's own GTFS feed (the same feed the live
real-time API is keyed to, so swapping mock trains for real ones later means
changing the train source, not the tunnels).

Depth is not in GTFS. The primary source is OpenStreetMap, where NYC's subway
ways carry bridge= and tunnel= tags — that is ground truth for which stretches
ride on structure and which are buried, including every water crossing. The
state's station list (structure per station) is kept as a second opinion: it
tells a deep tunnel from an open cut, and covers the rare vertex with no OSM way
nearby. Depth is then smoothed along the track so a line ramps between levels
instead of teleporting.

A bridge is clamped so it can never smooth into a tunnel. Without that, the
Rockaway line's trestles across Jamaica Bay — five station-free kilometres over
open water — inherited "Subway" from stations on the far shore and sank into the
bay.

  python3 build_subway.py path/to/gtfs_dir
"""
import csv
import json
import math
import os
import sys
import urllib.request

STATIONS_URL = ("https://data.ny.gov/resource/39hk-dx4f.json"
                "?$select=stop_name,daytime_routes,structure,gtfs_latitude,gtfs_longitude"
                "&$limit=1000")
# monthly ridership per station complex — sets how big a crowd each entrance draws
RIDERS_URL = ("https://data.ny.gov/resource/ak4z-sape.json"
              "?$select=station_complex,ridership,latitude,longitude,month"
              "&$order=month%20DESC&$limit=1600")
RIDER_MATCH = 0.0045   # ~400 m; a complex sits near, not on, each of its stations
OUT = "subway.json"

# Structure type -> (class, depth in metres; negative is below street level).
# class 0 = deep tunnel, 1 = shallow cut, 2 = at grade, 3 = above the street.
STRUCT = {
    "Subway":     (0, -22.0),
    "Open Cut":   (1, -8.0),
    "At Grade":   (2, 0.0),
    "Embankment": (3, 5.0),
    "Viaduct":    (3, 10.0),
    "Elevated":   (3, 12.0),
}
OSM_URL = "https://overpass-api.de/api/interpreter"
OSM_QUERY = """[out:json][timeout:300];
(
  way["railway"="subway"](40.48,-74.30,40.95,-73.68);
  way["railway"="light_rail"](40.48,-74.30,40.95,-73.68);
);
out geom tags;"""
OSM_CACHE = "osm_rail_cache.json"
OSM_SNAP = 70.0     # metres; how close a track vertex must be to trust an OSM way
CELL = 0.002        # index cell, ~180 m
LAND = "nyc_land.geojson"

# depth in metres by what the track is actually doing there
D_BRIDGE, D_BRIDGE_WATER, D_TUNNEL, D_CUT, D_GRADE = 11.0, 14.0, -22.0, -8.0, 0.0

SMOOTH_M = 250      # depth moving average half-window, metres of track
MIN_RUN_M = 130     # shorter than this and a level change is speckle, not a ramp
SIMPLIFY = 2e-5     # ~2 m, in degrees
DENSIFY_M = 150     # no segment longer than this. Simplification is right about
                    # geometry and wrong about sampling: the Rockaway trestle is
                    # dead straight for five kilometres, so RDP reduced the whole
                    # Jamaica Bay crossing to ONE segment with both endpoints
                    # ashore — nothing was left over the water to tag as a bridge
NEAR_LIMIT = 0.02   # ~1.7 km; beyond this a vertex keeps the running structure
BRANCH_NEW = 0.08   # a branch is worth keeping if this much of it is new ground


def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def get_json(url):
    """urllib first; curl as a fallback for boxes whose Python has no CA bundle."""
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return json.load(r)
    except Exception:
        import subprocess
        return json.loads(subprocess.run(["curl", "-sL", url],
                                         capture_output=True, check=True).stdout)


def fetch_ridership():
    """Average daily entries per station complex, over the last few months on
    file so a partial month cannot halve a station's crowd."""
    rows = get_json(RIDERS_URL)
    per = {}
    for r in rows:
        try:
            key = r["station_complex"]
            per.setdefault(key, {"n": 0, "sum": 0.0,
                                 "ll": (float(r["longitude"]), float(r["latitude"]))})
            per[key]["sum"] += float(r["ridership"])
            per[key]["n"] += 1
        except (KeyError, TypeError, ValueError):
            continue
    return [(v["ll"][0], v["ll"][1], v["sum"] / max(1, v["n"]) / 30.0) for v in per.values()]


def fetch_stations():
    rows = get_json(STATIONS_URL)
    riders = fetch_ridership()
    out = []
    for s in rows:
        try:
            lat, lon = float(s["gtfs_latitude"]), float(s["gtfs_longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        best, bd, at = 0.0, RIDER_MATCH ** 2, None
        for i, (rx, ry, daily) in enumerate(riders):
            d = (rx - lon) ** 2 + (ry - lat) ** 2 * 1.74
            if d < bd:
                bd, best, at = d, daily, i
        out.append({
            "n": s.get("stop_name", ""),
            "r": s.get("daytime_routes", "").strip(),
            "s": s.get("structure", "Subway"),
            "ll": [round(lon, 5), round(lat, 5)],
            "d": int(best),          # riders a day through this entrance
            "_cx": at,
        })

    # ridership is reported per COMPLEX, and a complex like Times Sq covers five
    # of these stations — split it so one platform does not draw the whole crowd
    share = {}
    for s in out:
        if s["_cx"] is not None:
            share[s["_cx"]] = share.get(s["_cx"], 0) + 1
    for s in out:
        if s["_cx"] is not None:
            s["d"] = int(s["d"] / share[s["_cx"]])
        del s["_cx"]
    return out


def rdp(pts, tol):
    if len(pts) < 3:
        return pts
    ax, ay = pts[0][:2]
    bx, by = pts[-1][:2]
    dx, dy = bx - ax, by - ay
    den = math.hypot(dx, dy)
    worst, at = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i][:2]
        d = abs(dy * (px - ax) - dx * (py - ay)) / den if den else math.hypot(px - ax, py - ay)
        if d > worst:
            worst, at = d, i
    if worst <= tol:
        return [pts[0], pts[-1]]
    return rdp(pts[:at + 1], tol)[:-1] + rdp(pts[at:], tol)


def densify(pts, step_m):
    """Put vertices back along long straights so every stretch gets sampled."""
    out = []
    for a, b in zip(pts, pts[1:]):
        out.append(a)
        d = math.hypot((b[0] - a[0]) * 84600, (b[1] - a[1]) * 111200)
        for k in range(1, int(d / step_m)):
            t = k * step_m / d
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    out.append(pts[-1])
    return out


def dedupe(pts):
    """Coincident vertices survive simplify+densify+rounding and each one becomes
    a zero-length class run — 171 of them showed up as speckle across the map."""
    out = [pts[0]]
    for q in pts[1:]:
        if math.hypot((q[0] - out[-1][0]) * 84600, (q[1] - out[-1][1]) * 111200) > 1.0:
            out.append(q)
    return out


def deflicker(pts, cum, min_m):
    """Fold any class run shorter than min_m into its longer neighbour. Depth is
    left alone, so the ramp still reads — only which layer draws it changes."""
    def runs_of():
        out, i, n = [], 0, len(pts)
        while i < n:
            j = i
            while j + 1 < n and pts[j + 1][2] == pts[i][2]:
                j += 1
            out.append((i, j))
            i = j + 1
        return out

    for _ in range(400):                       # converges fast; bounded anyway
        runs = runs_of()
        if len(runs) < 2:
            return pts
        short = min(runs, key=lambda r: cum[r[1]] - cum[r[0]])
        if cum[short[1]] - cum[short[0]] >= min_m:
            return pts
        k = runs.index(short)
        prev_len = cum[runs[k-1][1]] - cum[runs[k-1][0]] if k > 0 else -1
        next_len = cum[runs[k+1][1]] - cum[runs[k+1][0]] if k + 1 < len(runs) else -1
        cls = pts[runs[k-1][0]][2] if prev_len >= next_len else pts[runs[k+1][0]][2]
        for t in range(short[0], short[1] + 1):
            pts[t][2] = cls
    return pts


def pick_shapes(trips, shapes):
    """One set of shapes per route: the longest, plus any branch that covers
    ground the ones already kept do not. Both GTFS directions trace the same
    track, so only one direction is taken."""
    by_route = {}
    for t in trips:
        sid = t.get("shape_id")
        if sid and sid in shapes:
            by_route.setdefault(t["route_id"], {}).setdefault(t.get("direction_id", "0"), set()).add(sid)

    kept = []
    for route, dirs in sorted(by_route.items()):
        # whichever direction enumerates more distinct shapes sees more branches
        sids = max(dirs.values(), key=len) if dirs else set()
        cand = sorted(sids, key=lambda s: -len(shapes[s]))
        covered = set()
        for sid in cand:
            pts = shapes[sid]
            cells = {(round(x, 4), round(y, 4)) for x, y in pts}
            fresh = cells - covered
            if covered and len(fresh) < BRANCH_NEW * len(cells):
                continue
            covered |= cells
            kept.append((route, sid, pts))
    return kept


def osm_ways():
    """Every NYC subway way with its bridge/tunnel tags. Cached on disk — the
    Overpass call is slow and the answer changes about as often as the subway."""
    if os.path.exists(OSM_CACHE):
        with open(OSM_CACHE) as f:
            return json.load(f)
    import subprocess
    raw = subprocess.run(["curl", "-s", "--data-urlencode", "data=" + OSM_QUERY, OSM_URL],
                         capture_output=True, check=True).stdout
    doc = json.loads(raw)
    with open(OSM_CACHE, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    return doc


def osm_index(doc):
    """Grid index of way segments, each tagged bridge / tunnel / grade. AirTrain
    JFK comes back from the same query and runs alongside the A at Howard Beach,
    so it is dropped rather than left to poison the nearest-way lookup."""
    grid = {}
    counts = {"bridge": 0, "tunnel": 0, "grade": 0}
    for w in doc.get("elements", []):
        if w.get("type") != "way":
            continue
        t = w.get("tags", {})
        if "AirTrain" in (t.get("name") or ""):
            continue
        geom = w.get("geometry") or []
        if len(geom) < 2:
            continue
        if t.get("bridge") in ("yes", "trestle", "viaduct", "movable"):
            kind = "bridge"
        elif t.get("tunnel") == "yes":
            kind = "tunnel"
        else:
            kind = "grade"
        counts[kind] += 1
        for a, b in zip(geom, geom[1:]):
            seg = (a["lon"], a["lat"], b["lon"], b["lat"], kind)
            for px, py in ((a["lon"], a["lat"]), (b["lon"], b["lat"])):
                grid.setdefault((int(px / CELL), int(py / CELL)), []).append(seg)
    return grid, counts


def seg_metres(px, py, x1, y1, x2, y2):
    """Point-to-segment distance in metres, flat-earth at NYC's latitude."""
    ax, ay = (x1 - px) * 84600, (y1 - py) * 111200
    bx, by = (x2 - px) * 84600, (y2 - py) * 111200
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    t = 0.0 if den == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / den))
    return math.hypot(ax + t * dx, ay + t * dy)


def osm_kind(grid, x, y):
    cx, cy = int(x / CELL), int(y / CELL)
    best, bd = None, OSM_SNAP
    for i in (cx - 1, cx, cx + 1):
        for j in (cy - 1, cy, cy + 1):
            for x1, y1, x2, y2, kind in grid.get((i, j), ()):
                d = seg_metres(x, y, x1, y1, x2, y2)
                if d < bd:
                    bd, best = d, kind
    return best


def land_rings():
    """Outer rings of the five boroughs, with bboxes, for an over-water test."""
    with open(LAND) as f:
        doc = json.load(f)
    rings = []
    for feat in doc.get("features", []):
        g = feat.get("geometry") or {}
        polys = g["coordinates"] if g.get("type") == "MultiPolygon" else [g.get("coordinates", [])]
        for poly in polys:
            for ring in poly:
                xs = [p[0] for p in ring]
                ys = [p[1] for p in ring]
                rings.append((min(xs), min(ys), max(xs), max(ys), ring))
    return rings


def over_water(rings, x, y):
    inside = False
    for x0, y0, x1, y1, ring in rings:
        if x < x0 or x > x1 or y < y0 or y > y1:
            continue
        c = False
        n = len(ring)
        for k in range(n):
            ax, ay = ring[k]
            bx, by = ring[(k + 1) % n]
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                c = not c
        if c:
            inside = not inside
    return not inside


def main():
    gdir = sys.argv[1] if len(sys.argv) > 1 else "gtfs"
    routes = {r["route_id"]: r for r in load_csv(os.path.join(gdir, "routes.txt"))}
    trips = load_csv(os.path.join(gdir, "trips.txt"))

    shapes = {}
    with open(os.path.join(gdir, "shapes.txt"), newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            shapes.setdefault(row["shape_id"], []).append(
                (int(row["shape_pt_sequence"]), float(row["shape_pt_lon"]), float(row["shape_pt_lat"])))
    for sid in shapes:
        shapes[sid] = [(x, y) for _, x, y in sorted(shapes[sid])]

    stations = fetch_stations()
    stn = [(s["ll"][0], s["ll"][1], *STRUCT.get(s["s"], STRUCT["Subway"])) for s in stations]
    grid, osm_counts = osm_index(osm_ways())
    rings = land_rings()
    print(f"  osm ways: {osm_counts['bridge']} on structure, {osm_counts['tunnel']} buried, "
          f"{osm_counts['grade']} at grade")

    paths = []
    snapped = missed = 0
    for route, sid, pts in pick_shapes(trips, shapes):
        pts = rdp(pts, SIMPLIFY)
        if len(pts) < 4:
            continue
        pts = densify(pts, DENSIFY_M)
        pts = dedupe(pts)

        # What is the track DOING here? OSM's bridge/tunnel tags answer that
        # directly. The nearest station only refines it — deep tunnel vs open
        # cut — or stands in when no OSM way is close enough to trust.
        raw = []      # (depth, is_bridge, over_water)
        last = STRUCT["Subway"]
        for x, y in pts:
            best, bd = None, NEAR_LIMIT ** 2
            for sx, sy, cls, dep in stn:
                d = (sx - x) ** 2 + (sy - y) ** 2 * 1.74  # crude lat/lon aspect fix
                if d < bd:
                    bd, best = d, (cls, dep)
            last = best or last

            wet = over_water(rings, x, y)
            kind = osm_kind(grid, x, y)
            if kind is None:
                missed += 1
                raw.append((last[1], last[0] == 3, wet))
                continue
            snapped += 1
            if kind == "bridge":
                raw.append((D_BRIDGE_WATER if wet else D_BRIDGE, True, wet))
            elif kind == "tunnel":
                # the station knows whether this is a deep bore or a cut — but a
                # cut cannot exist under a river, so over water it is a full tube
                raw.append((D_TUNNEL if wet or last[0] != 1 else D_CUT, False, wet))
            elif wet:
                # untagged, but out over open water: there is no at-grade over a
                # river. Untagged stretches in the middle of a crossing are gaps
                # in OSM's tagging, not gaps in the bridge.
                raw.append((D_BRIDGE_WATER, True, True))
            else:
                # Untagged in OSM means only "not a bridge and not a tunnel" —
                # which is exactly what an open cut is. So trust the station here
                # for everything except a station claiming a tunnel, since OSM
                # has already ruled a tunnel out.
                raw.append((D_GRADE if last[0] == 0 else last[1], last[0] == 3, wet))

        # cumulative track distance, so the depth average spans a fixed length
        # rather than a fixed number of vertices — vertex spacing varies wildly
        # after simplification (long straights keep almost none).
        cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            cum.append(cum[-1] + math.hypot((b[0] - a[0]) * 84600, (b[1] - a[1]) * 111200))

        n = len(raw)
        out_pts = []
        for i, (x, y) in enumerate(pts):
            lo = i
            while lo > 0 and cum[i] - cum[lo - 1] <= SMOOTH_M:
                lo -= 1
            hi = i
            while hi < n - 1 and cum[hi + 1] - cum[i] <= SMOOTH_M:
                hi += 1
            dep = sum(raw[j][0] for j in range(lo, hi + 1)) / (hi - lo + 1)
            # A bridge never smooths into a tunnel. This is the clamp that keeps
            # the Rockaway trestles up out of Jamaica Bay.
            if raw[i][1]:
                dep = max(dep, 1.0)
            # class follows the smoothed depth so segment breaks land on the ramp
            cls = 0 if dep <= -14 else 1 if dep < -2 else 2 if dep < 3 else 3
            # Over open water only two things are possible: a bridge or a tube.
            # An open cut or an at-grade stretch out there is a tagging gap.
            if raw[i][2] and cls in (1, 2):
                cls = 0 if dep < 0 else 3
            pt = [round(x, 5), round(y, 5), cls, round(dep, 1)]
            if raw[i][2] and cls == 3:
                pt.append(1)          # on structure over open water — gets a deck
            out_pts.append(pt)

        out_pts = deflicker(out_pts, cum, MIN_RUN_M)

        r = routes.get(route, {})
        paths.append({
            "route": route,
            "id": sid,
            "color": "#" + (r.get("route_color") or "888888"),
            "name": r.get("route_long_name", ""),
            "pts": out_pts,
        })

    doc = {"paths": paths, "stations": stations}
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"))

    tally = {}
    water = 0
    for p in paths:
        for q in p["pts"]:
            tally[q[2]] = tally.get(q[2], 0) + 1
            if len(q) > 4:
                water += 1
    total = sum(tally.values()) or 1
    label = {0: "deep tunnel", 1: "open cut", 2: "at grade", 3: "elevated"}
    mix = ", ".join(f"{label[k]} {100*v/total:.0f}%" for k, v in sorted(tally.items()))
    size = os.path.getsize(OUT) / 1e6
    print(f"{OUT}: {len(paths)} track paths over {len(set(p['route'] for p in paths))} routes, "
          f"{len(stations)} stations, {size:.2f} MB")
    print(f"  track mix: {mix}")
    print(f"  osm snap: {snapped} vertices matched, {missed} fell back to the station list")
    print(f"  {water} vertices on structure over open water (the bridges)")


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    main()
