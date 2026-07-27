# SkyLine — build notes

**Read this first to resume.** The page is `skyline.html`. Nothing is deployed yet;
Pedro has said hold. Local preview only.

---

## 1. What SkyLine is

Fifth item in the site nav (Modules · Library · BrainView · **SkyLine** · About).
A dark MapLibre cutaway of New York in the house palette (near-black ground,
beige `#c9b98a` / `#d4c9a8` ink), aiming at the Cities Skylines underground view:
a translucent city you look *through* to see the rail network, the trains moving
in it, and the crowds walking into the stations.

Nav is wired from `index.html` and `library.html`; the page carries its own
floating nav bar so it is not a dead end.

---

## 2. Files

| file | what it is | ship it? |
|---|---|---|
| `skyline.html` | the whole page — map, layers, simulation, UI | yes |
| `skyline_massing.geojson` | 2.1 MB · 9,341 buildings over 100 ft | yes |
| `subway.json` | 290 KB · 38 track paths, 496 stations | yes |
| `build_skyline_massing.py` | builds the massing file | build only |
| `build_subway.py` | builds the subway file | build only |
| `audit_subway.py` | **re-run after any subway data change** | build only |
| `osm_rail_cache.json` | 4.7 MB Overpass cache | build only |

**Deploy gotcha:** `.vercelignore` is an allow-list. `skyline.html`,
`skyline_massing.geojson` and `subway.json` must all be whitelisted or the page
renders empty. Deploy is local `vercel --prod --yes` — never burn the 100/day
account-wide cap.

---

## 3. Where every number comes from

Real, in order of trust:

- **Track geometry + stations** — MTA GTFS static feed
  (`web.mta.info/developers/data/nyct/subway/google_transit.zip`). 29 routes
  including the Staten Island Railway. Scope per Pedro: trains only — no buses,
  no LIRR; Metro-North and PATH excluded on the same basis.
- **Bridge vs tunnel** — OpenStreetMap `bridge=` / `tunnel=` tags on NYC subway
  ways, via Overpass. 1,287 stretches on structure, 1,896 buried, 2,218 at
  grade. This is the primary depth source. 8,638 of 8,703 track vertices snap to
  a tagged way within 70 m.
- **Deep tunnel vs open cut, and the 65 unsnapped vertices** — NY State station
  list `data.ny.gov/resource/39hk-dx4f`, `structure` column (Subway / Open Cut /
  At Grade / Embankment / Viaduct / Elevated).
- **Crowd size per station** — MTA monthly ridership per complex
  `data.ny.gov/resource/ak4z-sape`, averaged over recent months and **split
  across the stations sharing a complex** (Times Sq covers five, and would
  otherwise draw five full crowds).
- **Where people walk in from** — real street vertices pulled live out of the
  CARTO vector tiles with `querySourceFeatures('carto','transportation')`.
- **Buildings** — NYC Open Data `5zhs-2jue`, every building over 100 ft.
- **Car counts and lengths** — real rolling stock, from knowledge not a dataset:
  ten 51 ft cars on the numbered lines, ten 60 ft on the lettered, four on the
  shuttles and the SIR.

- **Train positions — LIVE.** The eight MTA GTFS-realtime feeds at
  `api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2F<feed>`: `gtfs`,
  `gtfs-ace`, `gtfs-bdfm`, `gtfs-g`, `gtfs-jz`, `gtfs-nqrw`, `gtfs-l`,
  `gtfs-si`. **No API key, and they send `Access-Control-Allow-Origin: *`** — so
  the page talks to the MTA directly. No proxy, no serverless function, no worker.

**Nothing is mock any more.** The simulation is kept only as a fallback when the
feeds are unreachable, and the HUD says which is running.

---

## 3a. How a live position is derived

**The feeds publish no coordinates.** NYCT sends stop predictions, not geometry:
0 of the vehicle entries carry a `position`. What arrives per trip is the stop it
is heading for, whether it is standing there, and predicted arrival times.

So a position has to be built:

1. Every stop in `subway.json` carries its **distance along the track**
   (`gstops`, from GTFS `stop_times` projected onto our polyline). This is the
   bridge between "arriving at 232 in 40 s" and a point on a drawn line.
2. Stops are keyed by **parent id** — the trailing `N`/`S` is a direction marker,
   and a northbound train must match the same table as a southbound one.
   Direction comes from whether the stop distances rise or fall.
3. Pick the path for that route whose stop table best covers the trip, weighted
   heavily toward one containing the target stop.
4. Interpolate between the previous stop's departure and the target's arrival.

**Gotchas, all of them paid for:**

- In the real proto, `TripUpdate.stop_time_update` is **field 2** and `.vehicle`
  is field 3 — the reverse of the order they are usually listed in. Reading them
  the wrong way round yields zero stops and silently places nothing.
- The stop a train is standing at gets **pruned** from the prediction list once
  reached, so the vehicle's own `stop_id` often has no arrival time left against
  it. Use it to say "standing here", steer by the first stop that still has a
  prediction.
- The feed assigns **several future runs to the same physical train**, so a
  berthed train appears once per run it is booked for. Without an "has it
  started?" test the system reports ~670 trains when it owns about 460, and
  terminals pile up with phantoms. Test: some stop already behind it, or the next
  one within 120 s.
- NYCT reports `STOPPED_AT` for about **four trains in five** at any instant.
  Taking that literally freezes the map. Anchor the train to the reported
  platform, then run it out on its own next prediction; each poll re-anchors.
- A stale prediction can imply **900 km/h**. Speeds are capped at 24 m/s.

Verified against the feed: every moving train sits between the two stops it is
running between (0 out of bracket), speeds land at p10 24 / median 42 / p90 86
km/h, and about 400 trains across 27 routes at mid-morning — inside the real
fleet size. Crowd bursts fire on a real arrival: a change of target station
between polls means the previous target has just been served.

---

## 4. How the illusion is built

### The hard constraint
**MapLibre will not extrude below ground.** Tested directly: negative
`fill-extrusion-base`/`height` renders nothing. Everything below street level is
therefore faked; everything above street level is real geometry.

### Below ground — faked, two cues
1. Tunnel layers carry their own dimming (opacities around 0.17–0.58) rather than
   relying on the translucent land plane, because they now draw *above* the
   borough mask — see the layer order below and open issue 1.
2. Every frame, underground layers are offset up-screen by the number of pixels
   a point that deep would actually be displaced at the current pitch and zoom:
   `depth × sin(pitch) / metresPerPixel`, times a `DEPTH_GAIN` of 2.5 because
   true depth is a pixel or two and reads as a drawing error. Tilt the camera and
   the tunnels sink away under the streets. Applied via `line-translate` /
   `circle-translate` with `-anchor: viewport`.

### Above ground — real extrusions
Past `SOLID_ZOOM` (13.4) the flat lines switch off (`maxzoom`) and solid geometry
switches on (`minzoom`): 612 deck slabs, ~8,000 columns every 30 m, and a
route-coloured rail strip on the deck. Deck median 11 m; the named water
crossings use their real heights (see below).
Elevated train cars become extruded boxes standing on the deck.

**Decks are built from the raw vertices, not the merged runs.** An extrusion has
one height, and a run can climb from street level to a 12 m el — so stretches
break wherever the height moves more than 2 m (or every 400 m) and the deck
*steps* up the ramp instead of floating over it.

### The named crossings
Four places carry the subway over open water on structure, and the generic 14 m
bridge rule made them all look the same. They now use their real published
dimensions, in a `CROSSINGS` table in `skyline.html`:

| crossing | routes | deck | towers |
|---|---|---|---|
| Manhattan Bridge | B D N Q | 41 m | suspension, 102 m |
| Williamsburg Bridge | J M Z | 41 m | suspension, 94 m |
| Broadway Bridge | 1 | 8 m | vertical lift, 31 m |
| Jamaica Bay trestles | A, Rockaway shuttle | 9 m | none — piles every 14 m |

Tower *positions* are not hard-coded: they are derived from the widest-separated
pair of over-water vertices on that crossing, i.e. where the track leaves and
rejoins the shore. Main cables are parabolas from tower top down to deck+4 m at
mid-span, chopped into 46 short extruded boxes because a line cannot be lifted;
suspenders hang every 20 m. The two bbox entries for Manhattan and Williamsburg
overlap very slightly — harmless, but keep it in mind if a tower ever lands wrong.

### Buildings
CARTO's tiles carry no building layer below zoom 13, which is why the city used
to flatten when you pulled back. `skyline_massing.geojson` is client-tiled so it
draws at any zoom, with heights exaggerated ~7× at z9.5 easing to 1× by z13.6
where the CARTO set takes over. All buildings semi-transparent (0.42 / 0.45).

### Trains
Positions are live (see 3a). A consist is a polyline laid **along** the track for its real length, so it bends
through curves. Past `CAR_ZOOM` (13.4) it splits into individual cars with ~1.9 m
couplers showing. 470 trains — near the real rush-hour fleet. Brake into
stations, hold the platform 16–30 s, turn at terminals. `TIME_SCALE` 6, because
real speed is under a pixel a second at citywide zoom. `TIME_SCALE` applies to
the fallback simulation only — live trains run on the real clock.

### Crowds
Appear past `CROWD_ZOOM` (13.0). Head count per station is its share of real
ridership inside a fixed on-screen budget (`CROWD_CAP` 520 inbound, plus a
ceiling of half that for outbound). Walkers spawn on real street vertices 45–230 m
out, walk in at 1.35 m/s (~15 s on screen) and vanish at the entrance. A train
berthing spills an outbound burst — inbound warm `#e6d3a4`, outbound cool
`#93b0d8`. Steady state ~780 walkers, tick cost ~3 ms per 110 ms.

### X-RAY
Button in the legend. Drops land to 0.12, buildings to 0.10, streets to 0.13 and
brightens the tunnel bores — the city becomes a ghost and the network is the
subject.

---

## 5. Layer order (matters enormously)

```
background
land                                        translucent city floor
streets
massing-3d, buildings-3d, buildings-edge    semi-transparent city
cover                                       kills the Jersey / Long Island clutter
river, river-edge                           water drawn back in over the mask
  sub-tube, sub-tube-edge                   tube casing under a river
  sub-deep-bore, sub-deep, sub-cut          tunnels, parallax-offset
  sub-train-glow, sub-train-under           underground trains (flat lines)
  sub-deck, sub-deck-edge                   flat bridge deck   (maxzoom 13.4)
  sub-el-glow, sub-el                       flat el lines      (maxzoom 13.4)
  sub-tower-3d, sub-cable-3d                suspension towers + cables
  sub-pier-3d, sub-deck-3d, sub-rail-3d     solid structure    (minzoom 13.4)
  sub-stop, sub-crowd
  sub-train-el-glow, sub-train-el           flat el trains     (maxzoom 13.4)
  sub-train-3d                              elevated cars, boxes (minzoom 13.4)
cams-dot, cams-live
```

**Nothing rail-related may ever be added below `cover` again** — that is what
made the water look empty.

---

## 6. Open issues — start here

### 1. Empty river — FIXED
`nyc_mask.geojson` is *bounding box minus the boroughs*, painted opaque black,
and the borough polygons are land-only — so the mask covered every river and bay
and sat above every rail layer. Confirmed by point-in-polygon: the East River at
both bridges, Jamaica Bay and the 60th St tube all tested MASKED. Bridges and
under-river tubes were being painted out entirely.

Fix applied: **all rail layers now draw above `cover`.** The mask only ever
existed to hide the New Jersey / Long Island streets riding along in the shared
CARTO tiles; our own data is confined to NYC and never needed masking. Two
consequences handled:
- water is drawn back in on top of the mask (`river`, `river-edge`, from the
  CARTO `water` source-layer) so a river reads as a river and not a hole
- the tunnels can no longer be dimmed by the translucent land plane, so their own
  opacity carries the buried look (roughly 45% of the old values) and X-RAY now
  turns them *up* instead of relying on the ground fading

### 2. Verification is blind
Neither the in-app browser nor Claude-in-Chrome runs `requestAnimationFrame`, so
MapLibre never paints and **every screenshot of the map comes back black.** Do
not read a black screenshot as a bug. Working methods:
- `map._render(0)` then `gl.readPixels` — the only way to see actual pixels;
  downsample to an ASCII luminance grid to read the shape
- `map.queryRenderedFeatures({layers:[id]})` for what is on screen (ignores
  occlusion by later layers — which is exactly why issue 1 could hide from it)
- drive the simulation with `__tPrev = performance.now()-100; tick();` in a loop
  instead of waiting on timers
- background tabs get heavily throttled after a few minutes: `setTimeout` stalls
  and CDP calls time out. Reload the page to reset the clock, then work fast.

### 3. Water detection misses narrow channels
`nyc_land.geojson` is simplified, and the Harlem River ship canal is swallowed by
the borough outline — so the Broadway Bridge never registered as being over water.
That is why the uptown crossings looked "clean" while the Brooklyn ones did not:
the water-only deck layer simply never drew up there. Papered over by making the
flat deck apply to *all* elevated track, which is the right look anyway, but the
`water` flag itself is still wrong at narrow channels. It still governs the tube
casing and the deck width bump. A real fix means a proper hydrography polygon
(OSM `natural=water`) instead of borough outlines.

### 4. `line-gap-width` is a trap
MapLibre draws `line-width` on **both** sides of the gap, so a width of 10 with a
gap of 6 is a 26 px band, not a 10 px one. This is what produced the big pale
smear around every Brooklyn river crossing (`sub-deck-edge`, since deleted) and
it is still lurking in `sub-tube-edge` — keep those widths near 1.

### 5. Known cosmetic leftovers
- 22 class runs between 130–200 m (down from 171). Legitimate, but if any look
  like speckle, raise `MIN_RUN_M`.
- `Sheepshead Bay` drawn elevated where the station list says open cut; `Park Pl`
  on the Franklin shuttle drawn at grade where it says open cut. One stretch
  each, both from `deflicker` merging a short run. Harmless.
- The audit's "station says Elevated / track drawn deep tunnel" hits at Court Sq,
  Queensboro Plaza, 74 St-Broadway and 161 St are **false positives** — the check
  is route-blind and compares an elevated station (the 7, the 4) against the
  adjacent subway line's track. Verified correct per-route. Do not "fix" these.

---

## 7. Next session: walk the major points

Pedro's plan — step back and inspect the places where bridges, tunnels, trains
and crowds actually happen, rather than trusting aggregate counts. Suggested
circuit, each to be looked at on screen:

**Water crossings — the four bridges**
- Jamaica Bay, North & South Channel trestles (A, Rockaway shuttle) ~40.64,-73.83
- Manhattan Bridge (B D N Q) ~40.706,-73.989
- Williamsburg Bridge (J M Z) ~40.7135,-73.972
- Broadway Bridge, Harlem River ship canal (1) ~40.874,-73.914

**Water crossings — the tubes, which must stay buried**
- Joralemon St (4 5), Clark St (2 3), Montague St (R), Cranberry St (A C),
  Rutgers St (F), 14th St (L), Steinway (7), 53rd St (E M), 60th St (N R W),
  Harlem River tubes (4 5 6, 2, B D)

**Portals — where a line changes level**
- 60th St tunnel up to Queensboro Plaza el (N W)
- Culver Viaduct over the Gowanus, Smith–9th Sts (F G) — highest station
- Canarsie line surfacing east of Broadway Junction (L)
- Manhattanville viaduct at 125 St (1)
- Dyckman St / 207 St (1)

**Crowds and consists**
- Times Sq / 34 St-Penn / Grand Central — biggest crowds, deepest tunnels
- Astoria el (N W), Flushing el (7), Broadway el (J Z), Myrtle (M) — decks,
  columns, cars on structure
- A quiet outer stop for contrast — Van Cortlandt Park (1), Tottenville (SIR)

---

## 8. Tuning knobs (all near the top of the subway section in `skyline.html`)

```
GROUND_OPACITY  {surface 0.58, xray 0.12}   how see-through the city is
DEEP_M / CUT_M  22 / 8                      tunnel depths, metres
DEPTH_GAIN      2.5                         how much to overstate depth on screen
TIME_SCALE      6                           mock train speed multiplier
HEADWAY_M       4800                        metres between trains → fleet size
TICK            110                         ms between simulation pushes
CAR_ZOOM        13.4                        consist splits into cars
SOLID_ZOOM      13.4                        flat lines → real structure
CROWD_ZOOM      13.0                        crowds appear
CROWD_CAP       520                         inbound walkers on screen
DECK_W / DECK_T 5.6 / 1.8                   deck half-width, thickness
PIER_EVERY      30                          metres between columns
CAR_W / CAR_H   1.55 / 3.6                  car body half-width, height
```

In `build_subway.py`: `SMOOTH_M` 250 (depth averaging window), `MIN_RUN_M` 130
(de-speckle), `DENSIFY_M` 150 (**do not remove** — see below), `SIMPLIFY` 2e-5,
`OSM_SNAP` 70.

---

## 9. Lessons already paid for

- **Simplification is right about geometry and wrong about sampling.** RDP
  reduced the 5 km dead-straight Jamaica Bay trestle to one segment with both
  endpoints ashore, so there was no vertex over water to tag as a bridge. Hence
  `densify()`. Do not remove it.
- **"Untagged in OSM" means only "not a bridge and not a tunnel"** — which is
  exactly what an open cut is. Forcing those to ground level flattened the whole
  Sea Beach and Brighton lines.
- **Over open water only two things exist: a bridge or a full tube.** An open cut
  or at-grade stretch out there is a tagging gap, not a fact.
- **A bridge must be clamped so smoothing can never drag it underground.**
- AirTrain JFK comes back in the same Overpass query and runs beside the A at
  Howard Beach — it must be filtered by name or it poisons the nearest-way lookup.
- Coincident vertices survive simplify + densify + rounding and each becomes a
  zero-length class run — 171 speckles across the map before `dedupe()`.
