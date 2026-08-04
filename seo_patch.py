#!/usr/bin/env python3
"""Inject the SEO head block into the five hand-written pages, and link the
generated static camera index from the homepage footer so crawlers can reach it.

Idempotent — re-running replaces the block between the markers.

    python3 seo_patch.py
"""
import json, os, re

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = "https://bilbodata.com"
OPEN, CLOSE = "<!--SEO:START-->", "<!--SEO:END-->"

WEBSITE_LD = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    "name": "Bilbo Data",
    "alternateName": "Bilbo Data NYC",
    "url": SITE + "/",
    "description": ("Independent computer vision on New York City's 917 public DOT "
                    "traffic cameras. Live vehicle counts, open data, no faces and "
                    "no plates."),
    "publisher": {"@type": "Organization", "name": "Bilbo Data", "url": SITE + "/",
                  "logo": {"@type": "ImageObject",
                           "url": SITE + "/assets/bilbo-pup.png"}},
}

PAGES = {
    "index.html": dict(
        title="Bilbo Data — Live NYC Traffic Camera Counts, All 917 Cameras",
        desc=("Live vehicle counts read off New York City's 917 public DOT cameras "
              "by computer vision. Dashboard, per-camera history and an open "
              "dataset. No faces, no plates."),
        canon=SITE + "/",
        ld=[WEBSITE_LD],
    ),
    "about.html": dict(
        title="About Bilbo Data — An Ethical Read of NYC's Public Cameras",
        desc=("Why Bilbo Data counts vehicles instead of identifying people: the "
              "privacy line, the technical ceiling, and what an open read of "
              "NYC's cameras is for."),
        canon=SITE + "/about.html",
        ld=[{"@context": "https://schema.org", "@type": "AboutPage",
             "name": "About Bilbo Data", "url": SITE + "/about.html"}],
    ),
    "library.html": dict(
        title="Vehicle Library — What Bilbo Data Tells Apart on Camera",
        desc=("The body types, fleet liveries and markings Bilbo Data recognises "
              "on New York City traffic cameras, and where the resolution ceiling "
              "stops it."),
        canon=SITE + "/library.html",
        ld=[{"@context": "https://schema.org", "@type": "CollectionPage",
             "name": "Bilbo Data Vehicle Library", "url": SITE + "/library.html"}],
    ),
    "skyline.html": dict(
        title="SkyLine — 3D Map of NYC Subway Tunnels and Live Trains",
        desc=("A 3D cutaway of New York City showing the subway tunnels under the "
              "streets and live train positions from the MTA feed, rendered in the "
              "browser."),
        canon=SITE + "/skyline.html",
        ld=[{"@context": "https://schema.org", "@type": "WebPage",
             "name": "SkyLine — NYC subway in 3D", "url": SITE + "/skyline.html"}],
    ),
    "research.html": dict(
        title="Research Library — How Bilbo Data Reads NYC Cameras",
        desc=("The write-ups behind Bilbo Data: how vehicles are counted, what the "
              "camera resolution ceiling allows, and what the open dataset covers."),
        canon=SITE + "/research.html",
        ld=[{"@context": "https://schema.org", "@type": "CollectionPage",
             "name": "Bilbo Data Research Library", "url": SITE + "/research.html"}],
    ),
    "cam.html": dict(
        title="Camera Detail — Live Vehicle Counts | Bilbo Data",
        desc=("Live vehicle counts, hourly history and vehicle mix for a single New "
              "York City DOT traffic camera."),
        canon=SITE + "/cams/",
        ld=[],
        # ?id= query strings would otherwise mint thousands of near-duplicate URLs;
        # the crawlable version of every camera lives under /cams/.
        noindex=True,
    ),
}


def block(cfg):
    img = SITE + "/assets/og-card.png"
    lines = [OPEN,
             f'<meta name="description" content="{cfg["desc"]}">',
             f'<link rel="canonical" href="{cfg["canon"]}">']
    if cfg.get("noindex"):
        lines.append('<meta name="robots" content="noindex,follow">')
    else:
        lines.append('<meta name="robots" content="index,follow,max-image-preview:large,'
                     'max-snippet:-1,max-video-preview:-1">')
    lines += [
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Bilbo Data">',
        f'<meta property="og:title" content="{cfg["title"]}">',
        f'<meta property="og:description" content="{cfg["desc"]}">',
        f'<meta property="og:url" content="{cfg["canon"]}">',
        f'<meta property="og:image" content="{img}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{cfg["title"]}">',
        f'<meta name="twitter:description" content="{cfg["desc"]}">',
        f'<meta name="twitter:image" content="{img}">',
        '<meta name="theme-color" content="#000000">',
    ]
    for ld in cfg["ld"]:
        lines.append('<script type="application/ld+json">'
                     + json.dumps(ld, separators=(",", ":")) + "</script>")
    lines.append(CLOSE)
    return "\n".join(lines)


for fname, cfg in PAGES.items():
    path = os.path.join(ROOT, fname)
    src = open(path).read()

    # title, and use it as the anchor — several of these pages were authored
    # without a closing </head> tag, so we cannot rely on one being there.
    title_tag = f'<title>{cfg["title"]}</title>'
    src, n = re.subn(r"<title>.*?</title>", title_tag, src, count=1, flags=re.S)
    assert n == 1, f"{fname}: no <title> to anchor to"

    # head block, replacing any previous run
    if OPEN in src:
        # lambda repl: the JSON-LD payload contains \uXXXX escapes that re.sub
        # would otherwise try to interpret as regex escapes.
        src = re.sub(re.escape(OPEN) + ".*?" + re.escape(CLOSE),
                     lambda _m, b=block(cfg): b, src, count=1, flags=re.S)
    else:
        src = src.replace(title_tag, title_tag + "\n" + block(cfg), 1)

    open(path, "w").write(src)
    print(f"head    {fname}")

# --------------------------------------------- crawl path from the homepage
FOOT_OPEN, FOOT_CLOSE = "<!--SEO:FOOTLINKS-->", "<!--SEO:/FOOTLINKS-->"
foot = f"""{FOOT_OPEN}
      <div class="fgrid">
        <a href="/cams/">All 917 NYC traffic cameras</a>
        <a href="/cams/manhattan.html">Manhattan cameras</a>
        <a href="/cams/brooklyn.html">Brooklyn cameras</a>
        <a href="/cams/queens.html">Queens cameras</a>
        <a href="/cams/bronx.html">Bronx cameras</a>
        <a href="/cams/staten-island.html">Staten Island cameras</a>
        <a href="/busiest.html">Busiest NYC intersections, ranked</a>
        <a href="/data.html">Open dataset (CSV)</a>
      </div>
      {FOOT_CLOSE}"""

idx = os.path.join(ROOT, "index.html")
src = open(idx).read()
if FOOT_OPEN in src:
    src = re.sub(re.escape(FOOT_OPEN) + ".*?" + re.escape(FOOT_CLOSE),
                 lambda _m: foot, src, count=1, flags=re.S)
else:
    src = src.replace('      <div class="fine">', foot + '\n      <div class="fine">', 1)
open(idx, "w").write(src)
print("footer  index.html")
