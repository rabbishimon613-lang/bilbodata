#!/usr/bin/env python3
"""Push the whole URL set to IndexNow, and write llms.txt.

IndexNow is the one indexing channel that needs no account and no console:
you host a key file at the site root and POST your URLs. Bing, Yandex,
Seznam and DuckDuckGo consume it directly. Google does not, which is why
Search Console still matters — but this gets 900+ pages discovered today
instead of whenever a crawler wanders past.

    python3 seo_submit.py            # writes files, submits
    python3 seo_submit.py --dry-run  # writes files only
"""
import json, os, ssl, sys, urllib.request, xml.etree.ElementTree as ET

# this Mac's system Python ships without a usable CA bundle
try:
    import certifi
    SSLCTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSLCTX = ssl.create_default_context()

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = "https://bilbodata.com"
HOST = "bilbodata.com"
KEY = "371ad4d7ca1c478080ed2b8bf85b9a5c"
DRY = "--dry-run" in sys.argv

# the key file proves we control the host
with open(os.path.join(ROOT, f"{KEY}.txt"), "w") as fh:
    fh.write(KEY)
print(f"key file    /{KEY}.txt")

# ------------------------------------------------------------------ llms.txt
# A plain-language map of the site for AI answer engines, which increasingly
# read this before they read the HTML.
llms = f"""# Bilbo Data

> Independent computer vision on New York City's 917 public Department of
> Transportation traffic cameras. We count what passes — cars, trucks, buses,
> motorcycles — per camera, per timestamp, and publish it as open data.
> We do not identify people: no faces, no plate numbers, no tracking of
> individuals. "Can't tell" is an allowed answer.

## What is here

- [Live dashboard]({SITE}/): real-time counts across the counted camera set.
- [All 917 cameras]({SITE}/cams/): every public NYC DOT camera, with a live
  view, coordinates, observed counts and its nearest neighbours.
- [Open dataset]({SITE}/data.html): the vehicle-count CSV and Parquet files,
  free, no login, with the caveats stated in full.
- [Vehicle library]({SITE}/library.html): what the system can and cannot tell
  apart at NYC DOT camera resolution.
- [SkyLine]({SITE}/skyline.html): a 3D cutaway of the city's subway tunnels
  with live MTA train positions.
- [About]({SITE}/about.html): the privacy line, the method, and the ceiling.

## Boroughs

- [Manhattan]({SITE}/cams/manhattan.html) — 350 cameras
- [Brooklyn]({SITE}/cams/brooklyn.html) — 200 cameras
- [Queens]({SITE}/cams/queens.html) — 194 cameras
- [Staten Island]({SITE}/cams/staten-island.html) — 99 cameras
- [Bronx]({SITE}/cams/bronx.html) — 74 cameras

## Data

- CSV: https://raw.githubusercontent.com/rabbishimon613-lang/bilbodata/main/counts.csv
- Fields: timestamp, camera id, name, car, moto, bus, truck, total,
  brightness, lit, samples, stale.
- Licence: free to use with attribution to Bilbo Data. Camera imagery
  belongs to NYC DOT; the counts are ours.

## Honest limits

The cameras are low resolution and many are unusable at night. Counts are of
objects in a frame, not a traffic census. The `brightness`, `lit` and `stale`
columns exist so you can filter on exactly that. We publish the flaws next to
the numbers rather than smoothing them away.
"""
with open(os.path.join(ROOT, "llms.txt"), "w") as fh:
    fh.write(llms)
print("llms.txt    written")

# ------------------------------------------------------------------ submit
urls = []
for sm in ("sitemap-core.xml", "sitemap-cameras.xml"):
    tree = ET.parse(os.path.join(ROOT, sm))
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    urls += [loc.text for loc in tree.iter(f"{ns}loc")]
print(f"urls        {len(urls)}")

if DRY:
    print("dry run — nothing submitted")
    sys.exit(0)

# IndexNow caps a batch at 10,000; we are well under, but chunk anyway.
for i in range(0, len(urls), 5000):
    chunk = urls[i:i + 5000]
    payload = json.dumps({
        "host": HOST, "key": KEY,
        "keyLocation": f"{SITE}/{KEY}.txt",
        "urlList": chunk,
    }).encode()
    req = urllib.request.Request(
        "https://api.indexnow.org/IndexNow", data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSLCTX) as r:
            print(f"indexnow    {r.status} for {len(chunk)} urls")
    except urllib.error.HTTPError as e:
        print(f"indexnow    HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        print(f"indexnow    failed: {e}")
