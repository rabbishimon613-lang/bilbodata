#!/usr/bin/env python3
"""
Build the SkyLine massing layer — every NYC building over 100 ft, footprint
simplified and heights in metres, small enough to ship as one GeoJSON.

The CARTO basemap only carries buildings from zoom 13 up, so the city has no
skyline at all when you pull back. This file is a client-side source: MapLibre
tiles it in the browser, so it draws at every zoom, all the way out.

Source: NYC Open Data "BUILDING" (5zhs-2jue), height_roof / ground_elevation
in feet.

  python3 build_skyline_massing.py            # download + build
  python3 build_skyline_massing.py raw.geojson  # build from a saved download
"""
import json
import math
import sys
import urllib.parse
import urllib.request

DATASET = "https://data.cityofnewyork.us/resource/5zhs-2jue.geojson"
MIN_FEET = 100          # ~30 m — the cut that makes a skyline rather than a carpet
FT = 0.3048
OUT = "skyline_massing.geojson"
TOL = 6e-5              # ~5 m simplification tolerance, in degrees
PREC = 5                # ~1 m coordinate precision


def download():
    q = urllib.parse.urlencode({
        "$select": "the_geom,height_roof,ground_elevation",
        "$where": f"height_roof > {MIN_FEET}",
        "$limit": 12000,
    })
    with urllib.request.urlopen(f"{DATASET}?{q}", timeout=180) as r:
        return json.load(r)


def rdp(pts, tol):
    """Ramer-Douglas-Peucker on a ring."""
    if len(pts) < 3:
        return pts
    ax, ay = pts[0]
    bx, by = pts[-1]
    dx, dy = bx - ax, by - ay
    den = math.hypot(dx, dy)
    worst, at = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        d = abs(dy * (px - ax) - dx * (py - ay)) / den if den else math.hypot(px - ax, py - ay)
        if d > worst:
            worst, at = d, i
    if worst <= tol:
        return [pts[0], pts[-1]]
    return rdp(pts[:at + 1], tol)[:-1] + rdp(pts[at:], tol)


def outer_rings(geom):
    """Outer ring of every polygon in a Polygon/MultiPolygon. Holes dropped —
    at these zooms a courtyard is never visible and doubles the byte count."""
    if not geom:
        return []
    t = geom.get("type")
    if t == "Polygon":
        return [geom["coordinates"][0]]
    if t == "MultiPolygon":
        return [p[0] for p in geom["coordinates"] if p]
    return []


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            src = json.load(f)
    else:
        src = download()

    feats = []
    for f in src.get("features", []):
        p = f.get("properties") or {}
        try:
            h = float(p.get("height_roof"))
        except (TypeError, ValueError):
            continue
        if h <= MIN_FEET:
            continue
        try:
            base = float(p.get("ground_elevation") or 0)
        except ValueError:
            base = 0.0

        for ring in outer_rings(f.get("geometry")):
            r = rdp([(float(x), float(y)) for x, y, *_ in ring], TOL)
            if len(r) < 4:
                continue
            if r[0] != r[-1]:
                r.append(r[0])
            feats.append({
                "type": "Feature",
                "properties": {
                    "h": round(h * FT, 1),          # roof height, metres
                    "b": round(base * FT, 1),       # ground elevation, metres
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[round(x, PREC), round(y, PREC)] for x, y in r]],
                },
            })

    feats.sort(key=lambda f: -f["properties"]["h"])
    out = {"type": "FeatureCollection", "features": feats}
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))

    hs = [f["properties"]["h"] for f in feats]
    print(f"{OUT}: {len(feats)} massings, tallest {max(hs):.0f} m, "
          f"median {sorted(hs)[len(hs) // 2]:.0f} m")


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    main()
