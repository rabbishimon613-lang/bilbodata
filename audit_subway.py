#!/usr/bin/env python3
"""Audit the built subway layer for the same class of bug as Jamaica Bay."""
import json, math, sys
from collections import Counter, defaultdict

D = json.load(open('/Volumes/EOS_DIGITAL/bilbodata/subway.json'))
LAB = {0:'deep tunnel',1:'open cut',2:'at grade',3:'elevated'}
paths, stations = D['paths'], D['stations']

def m(ax,ay,bx,by): return math.hypot((bx-ax)*84600,(by-ay)*111200)

# ---------- A. stations with no track near them = missing branches ----------
print("="*72)
print("A. STATIONS WITH NO TRACK NEARBY  (missing track)")
verts = [(q[0],q[1]) for p in paths for q in p['pts']]
gridv = defaultdict(list)
for x,y in verts: gridv[(int(x/0.004),int(y/0.004))].append((x,y))
def near_track(x,y):
    best = 9e9
    cx,cy = int(x/0.004), int(y/0.004)
    for i in (cx-1,cx,cx+1):
        for j in (cy-1,cy,cy+1):
            for vx,vy in gridv.get((i,j),()):
                d = m(x,y,vx,vy)
                if d < best: best = d
    return best
orphans = []
for s in stations:
    d = near_track(s['ll'][0], s['ll'][1])
    if d > 250: orphans.append((round(d), s['n'], s['r'], s['s']))
orphans.sort(reverse=True)
print(f"  {len(orphans)} of {len(stations)} stations are >250 m from any drawn track")
for d,n,r,st in orphans[:40]: print(f"   {d:>5} m  {n}  ({r})  [{st}]")

# ---------- B. class vs the station list ----------
print("="*72)
print("B. OSM CLASS vs STATION STRUCTURE  (disagreements at stations)")
S2C = {'Subway':0,'Open Cut':1,'At Grade':2,'Embankment':3,'Viaduct':3,'Elevated':3}
gridp = defaultdict(list)
for p in paths:
    for q in p['pts']: gridp[(int(q[0]/0.004),int(q[1]/0.004))].append((q,p['route']))
bad = Counter(); examples = defaultdict(list)
for s in stations:
    x,y = s['ll']; want = S2C.get(s['s'],0)
    cx,cy = int(x/0.004), int(y/0.004)
    best, bq, br = 9e9, None, None
    for i in (cx-1,cx,cx+1):
        for j in (cy-1,cy,cy+1):
            for q,rt in gridp.get((i,j),()):
                d = m(x,y,q[0],q[1])
                if d < best: best, bq, br = d, q, rt
    if bq is None or best > 120: continue
    got = bq[2]
    # underground vs above is the only disagreement that shows
    if (want>=2) != (got>=2):
        bad[(s['s'], LAB[got])] += 1
        examples[(s['s'], LAB[got])].append(f"{s['n']} ({br})")
for k,v in bad.most_common():
    print(f"  station says {k[0]:<11} track drawn {k[1]:<12} x{v}")
    for e in examples[k][:6]: print(f"      {e}")

# ---------- C. flicker: very short class runs ----------
print("="*72)
print("C. FLICKER  (class runs shorter than 200 m)")
flick = []
for p in paths:
    pts = p['pts']
    cum=[0.0]
    for a,b in zip(pts,pts[1:]): cum.append(cum[-1]+m(a[0],a[1],b[0],b[1]))
    i=0
    while i < len(pts):
        j=i
        while j+1 < len(pts) and pts[j+1][2]==pts[i][2]: j+=1
        length = cum[j]-cum[i]
        if length < 200 and (i>0 or j<len(pts)-1):
            flick.append((round(length), p['route'], LAB[pts[i][2]], round(pts[i][1],4), round(pts[i][0],4)))
        i=j+1
print(f"  {len(flick)} short runs")
for f in sorted(flick)[:18]: print(f"   {f[0]:>4} m  {f[1]:<3} {f[2]:<12} at {f[3]},{f[4]}")

# ---------- D. tunnels over water = river tubes, enumerate them ----------
print("="*72)
print("D. TRACK UNDER WATER  (should be the river tubes, nothing else)")
land = json.load(open('/Volumes/EOS_DIGITAL/bilbodata/nyc_land.geojson'))
rings=[]
for f in land['features']:
    g=f['geometry']; polys = g['coordinates'] if g['type']=='MultiPolygon' else [g['coordinates']]
    for poly in polys:
        for r in poly:
            xs=[q[0] for q in r]; ys=[q[1] for q in r]
            rings.append((min(xs),min(ys),max(xs),max(ys),r))
def wet(x,y):
    inside=False
    for x0,y0,x1,y1,r in rings:
        if x<x0 or x>x1 or y<y0 or y>y1: continue
        c=False; n=len(r)
        for k in range(n):
            ax,ay=r[k]; bx,by=r[(k+1)%n]
            if (ay>y)!=(by>y) and x < (bx-ax)*(y-ay)/(by-ay)+ax: c = not c
        if c: inside = not inside
    return not inside
groups=defaultdict(lambda: [0,set()])
for p in paths:
    for q in p['pts']:
        if wet(q[0],q[1]):
            k=(round(q[1],2),round(q[0],2),LAB[q[2]])
            groups[k][0]+=1; groups[k][1].add(p['route'])
for k in sorted(groups):
    n,rts=groups[k]
    print(f"   {k[0]:.2f},{k[1]:.2f}  {k[2]:<12} x{n:<3} routes {','.join(sorted(rts))}")

# ---------- E. terminals: does each route reach where it should ----------
print("="*72)
print("E. ROUTE EXTENTS  (northmost / southmost drawn point per route)")
for p in sorted(paths, key=lambda p:p['route']):
    lats=[q[1] for q in p['pts']]; lons=[q[0] for q in p['pts']]
    print(f"   {p['route']:<3} {len(p['pts']):>4} pts  lat {min(lats):.3f}–{max(lats):.3f}  lon {min(lons):.3f}–{max(lons):.3f}")
