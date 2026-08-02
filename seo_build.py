#!/usr/bin/env python3
"""Static SEO surface generator for Bilbo Data.

The live site is a JS-rendered single page, which gives Google exactly one URL
to index. This builds the crawlable half of the site: one static page per NYC
DOT camera, borough hubs, a dataset page, sitemaps and robots.txt. Run it
whenever cams_all.json or counts.csv change, then deploy the shell.

    python3 seo_build.py
"""
import csv, json, math, os, re, html, collections, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = "https://bilbodata.com"
OUT = os.path.join(ROOT, "cams")
TODAY = datetime.date.today().isoformat()

BOROUGH_SLUG = {
    "Manhattan": "manhattan", "Brooklyn": "brooklyn", "Queens": "queens",
    "Bronx": "bronx", "Staten Island": "staten-island",
}


def slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def esc(s):
    return html.escape(str(s), quote=True)


# --------------------------------------------------------- SERP length fits
# Google renders roughly 60 characters of a <title> and 160 of a description
# before it truncates. Every one of the 917 camera titles used to blow past
# both, so the informative half — the street name — was being cut off in the
# result that actually matters. These two keep the generated pages inside the
# window without hand-editing hundreds of files.

def fit_title(head, tail=" | Bilbo Data", limit=60, keep=""):
    """Prefer the branded title; drop the brand before losing real words.

    `keep` is a short suffix that must survive truncation. The eastbound and
    westbound cameras at one interchange share every word except the direction
    marker, so without this they truncate to byte-identical titles.
    """
    head = " ".join(str(head).split())
    keep = " ".join(str(keep).split())
    full = f"{head} {keep}".strip() if keep else head
    if len(full) + len(tail) <= limit:
        return full + tail
    if len(full) <= limit:
        return full
    budget = limit - 1 - (len(keep) + 1 if keep else 0)
    cut = head[:budget]
    sp = cut.rfind(" ")
    if sp > budget * 0.6:
        cut = cut[:sp]
    cut = cut.rstrip(" ,;:–—-") + "…"
    return f"{cut} {keep}" if keep else cut


def fit_desc(text, limit=160):
    """Trim to a clean word boundary so the snippet never cuts mid-word."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    sp = cut.rfind(" ")
    if sp > limit * 0.6:
        cut = cut[:sp]
    return cut.rstrip(" ,;:–—-") + "…"


# ------------------------------------------------------------- camera names
# 146 of the 917 DOT names are machine strings ("C2-BQE-22-WB_at_Lee_Ave-Ex31").
# index.html already decodes them client-side; this is that same pretty()
# ported to Python so the static pages, their titles and their URLs read the
# way a person would actually search for them.
HWY = {
    "PE": "Prospect Expwy", "BQE": "Brooklyn-Queens Expwy", "GOW": "Gowanus Expwy",
    "LIE": "Long Island Expwy", "GCP": "Grand Central Pkwy", "VWE": "Van Wyck Expwy",
    "CVE": "Clearview Expwy", "WSE": "West Shore Expwy", "SIE": "Staten Island Expwy",
    "MDE": "Major Deegan Expwy", "BRE": "Bruckner Expwy", "CBX": "Cross Bronx Expwy",
    "CBE": "Cross Bronx Expwy", "SHE": "Sheridan Expwy", "HRP": "Hutchinson River Pkwy",
    "BRP": "Bronx River Pkwy", "HHP": "Henry Hudson Pkwy", "FDR": "FDR Drive",
    "NSP": "Northern State Pkwy", "KVP": "Korean War Veterans Pkwy",
    # codes index.html's map never covered, read off the cameras' own boroughs
    "GE": "Gowanus Expwy", "WST": "West Side Hwy",
    "MLK": "Martin Luther King Jr Expwy", "KWV": "Korean War Veterans Pkwy",
    "TNE": "Throgs Neck Expwy",
}
DIRW = {"NB": "northbound", "SB": "southbound", "EB": "eastbound", "WB": "westbound"}
ABBR = [(r"\bHamltn\b", "Hamilton"), (r"\bBrx\.?\s?Rvr\b", "Bronx River"),
        (r"\bStewrt\b", "Stewart"), (r"\bKosc\b", "Kosciuszko"), (r"\bTwn\b", "Town"),
        (r"\bHutch\b", "Hutchinson"), (r"[-_\s]Br\.?$", " Bridge"),
        (r"\bAvenue\b", "Ave"), (r"\bStreet\b", "St")]


def pretty(n):
    """Decode a DOT camera name into something readable. Returns (name, hwy_code)."""
    if not n:
        return n, None
    m = re.match(r"^C\d+-([A-Z]{2,4})-\d+[A-Z]?[-_](.*)$", n)
    if m and m.group(1) in HWY:
        rest, direction = m.group(2), ""
        dm = re.match(r"^(NB|SB|EB|WB|N|S|E|W)(?=[_-])", rest, re.I)
        if dm:
            direction = DIRW.get(dm.group(1).upper()[0] + "B", "")
        cross = re.sub(r"^(NB|SB|EB|WB|N|S|E|W|Ctr|Cntr|Center|Med|Btwn)(?=[_-])[_-]*",
                       "", rest, flags=re.I)
        am = re.search(r"at[_ ](.+)$", cross, re.I)
        if am:
            cross = am.group(1)
        exit_no = ""
        em = re.search(r"[-_]?Ex[_.]?(\w+)$", cross, re.I)
        if em:
            exit_no = em.group(1)
            cross = re.sub(r"[-_]?Ex[_.]?\w+$", "", cross, flags=re.I)
        cross = re.sub(r"[- ]+$", "", cross.replace("_", " ")).strip()
        for pat, rep in ABBR:
            cross = re.sub(pat, rep, cross, flags=re.I)
        out = HWY[m.group(1)] + (f" @ {cross}" if cross else "")
        if exit_no:
            out += f" · Exit {exit_no}"
        if direction:
            out += f" ({direction})"
        return out, m.group(1)
    # non-highway names: strip the trailing DOT asset number and tidy separators
    out = re.sub(r"\s*-?\s*\d{2,3}\.\d+\s*$", "", n)
    out = re.sub(r"\s+and\s+", " @ ", out).replace("_", " ")
    out = re.sub(r"\bFt\.\s?", "Ft ", out)
    return re.sub(r"\s{2,}", " ", out).strip(" -·"), None


# ---------------------------------------------------------------- data load
cams = json.load(open(os.path.join(ROOT, "cams_all.json")))
seen_slugs = {}
for c in cams:
    c["raw_name"] = c["name"]
    c["name"], c["hwy"] = pretty(c["name"])
    c["area"] = c.get("area") or "New York City"
    s = slug(c["name"]) or slug(c["raw_name"])
    # prettifying collapses a handful of names onto the same slug; keep them unique
    if s in seen_slugs:
        seen_slugs[s] += 1
        s = f"{s}-{seen_slugs[s]}"
    else:
        seen_slugs[s] = 1
    c["slug"] = s

by_id = {c["id"]: c for c in cams}

# --- picture quality: 775 of the 917 cameras are 352x240, so the handful of
# --- HD ones are genuinely worth telling people about.
GRADE = {}
census = os.path.join(ROOT, "cam_resolution_census.csv")
if os.path.exists(census):
    with open(census) as fh:
        for r in csv.DictReader(fh):
            try:
                w, h = int(r["width"]), int(r["height"])
            except (ValueError, KeyError):
                continue
            if w >= 1280:
                label = f"HD · {w}×{h}"
            elif w >= 640:
                label = f"Enhanced · {w}×{h}"
            else:
                label = f"Standard · {w}×{h}"
            GRADE[r["id"]] = (label, w, h)

# --- which way the lens points, where the DOT banner gave it away
FACING = {}
try:
    for cid, v in json.load(open(os.path.join(ROOT, "headings.json")))["headings"].items():
        if v.get("facing"):
            FACING[cid] = v["facing"]
except Exception:
    pass

# --- nearest subway station, from the SkyLine data already in the repo
STATIONS = []
try:
    STATIONS = [(s["n"], s["ll"][1], s["ll"][0], s.get("r", ""))
                for s in json.load(open(os.path.join(ROOT, "subway.json")))["stations"]]
except Exception:
    pass


def nearest_station(cam):
    if not STATIONS:
        return None
    scale = math.cos(math.radians(cam["lat"]))
    best = min(STATIONS, key=lambda s: (s[1] - cam["lat"]) ** 2
               + ((s[2] - cam["lon"]) * scale) ** 2)
    dy = (best[1] - cam["lat"]) * 69.0
    dx = (best[2] - cam["lon"]) * 69.0 * scale
    return best[0], best[3], math.hypot(dx, dy)

# per-camera observed traffic, where the counter has covered it
stats = collections.defaultdict(lambda: {"n": 0, "veh": 0, "car": 0, "bus": 0,
                                         "truck": 0, "moto": 0, "peak": 0,
                                         "hours": collections.Counter()})
counts_path = os.path.join(ROOT, "counts.csv")
if os.path.exists(counts_path):
    with open(counts_path) as fh:
        for r in csv.DictReader(fh):
            cid = r.get("cam_id")
            if cid not in by_id:
                continue
            try:
                veh = int(r.get("veh_total") or 0)
            except ValueError:
                continue
            s = stats[cid]
            s["n"] += 1
            s["veh"] += veh
            for k in ("car", "bus", "truck", "moto"):
                try:
                    s[k] += int(r.get(k) or 0)
                except ValueError:
                    pass
            s["peak"] = max(s["peak"], veh)
            ts = r.get("ts", "")
            if len(ts) >= 13:
                s["hours"][ts[11:13]] += veh

# ------------------------------------------------------- nearest neighbours
def neighbours(cam, k=6):
    lat, lon = cam["lat"], cam["lon"]
    scale = math.cos(math.radians(lat))
    out = []
    for o in cams:
        if o["id"] == cam["id"]:
            continue
        dy = (o["lat"] - lat) * 69.0
        dx = (o["lon"] - lon) * 69.0 * scale
        out.append((math.hypot(dx, dy), o))
    out.sort(key=lambda t: t[0])
    return out[:k]


# ------------------------------------------------------------------ chrome
CSS = """
:root{--bg:#000;--panel:#0c0d0f;--line:#1b1c1f;--line2:#2a2c31;--ink:#f3f4f5;
--dim:#8b909a;--mut:#585d66;--live:#4ad991;--accent:#5b8def;
--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
--sans:"Inter",system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
font-weight:300;font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:960px;margin:0 auto;padding:0 22px}
header{border-bottom:1px solid var(--line);background:#050505}
header .wrap{display:flex;align-items:center;gap:12px;min-height:60px;
flex-wrap:wrap;padding-top:8px;padding-bottom:8px}
header img{height:32px}
header .bn{font-size:19px;font-weight:500;white-space:nowrap}
header nav{margin-left:auto;display:flex;flex-wrap:wrap;gap:8px 16px;font-size:13px}
@media(max-width:520px){header nav{margin-left:0;width:100%}}
h1{font-size:27px;font-weight:400;letter-spacing:-.01em;margin:26px 0 6px}
h2{font-size:17px;font-weight:400;margin:34px 0 10px;
border-bottom:1px solid var(--line);padding-bottom:7px}
.eyebrow{font-family:var(--mono);font-size:10.5px;letter-spacing:.24em;
text-transform:uppercase;color:var(--mut)}
.lede{color:var(--dim);max-width:62ch}
.shot{width:100%;max-width:640px;border:1px solid var(--line2);border-radius:2px;
display:block;margin:18px 0;background:var(--panel);
aspect-ratio:22/15;object-fit:contain}
.kv{display:grid;grid-template-columns:170px 1fr;gap:7px 16px;
font-size:14px;margin:14px 0}
.kv dt{color:var(--mut);font-family:var(--mono);font-size:11px;
letter-spacing:.12em;text-transform:uppercase;padding-top:3px}
.kv dd{margin:0;color:var(--ink)}
ul.cols{list-style:none;padding:0;margin:10px 0;columns:3;column-gap:26px;font-size:14px}
ul.cols li{break-inside:avoid;padding:3px 0;color:var(--dim)}
@media(max-width:760px){ul.cols{columns:1}.kv{grid-template-columns:1fr}}
.cta{display:inline-block;margin:16px 0;font-family:var(--mono);font-size:12px;
letter-spacing:.16em;text-transform:uppercase;color:#04070d;background:var(--accent);
border-radius:2px;padding:12px 22px}
.cta:hover{text-decoration:none;filter:brightness(1.12)}
footer{border-top:1px solid var(--line);margin-top:56px;padding:22px 0 60px;
color:var(--mut);font-size:12.5px}
.crumb{font-size:12.5px;color:var(--mut);margin-top:18px}
.tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:18px 0}
table.rank{width:100%;min-width:620px;border-collapse:collapse;font-size:13.5px}
table.rank th{text-align:left;font-family:var(--mono);font-size:10.5px;
letter-spacing:.14em;text-transform:uppercase;color:var(--mut);font-weight:400;
border-bottom:1px solid var(--line2);padding:8px 10px 8px 0}
table.rank td{padding:7px 10px 7px 0;border-bottom:1px solid var(--line);color:var(--dim)}
table.rank td:nth-child(2){color:var(--ink)}
table.rank td:first-child{font-family:var(--mono);color:var(--mut);width:34px}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500'
         '&family=Inter:wght@200;300;400;500&display=swap" rel="stylesheet">')


def page(path, title, desc, body, jsonld, image=None, canon=None):
    """Write one static page. `path` is relative to the repo root."""
    canon = canon or f"{SITE}/{path}"
    img = image or f"{SITE}/assets/og-card.png"
    up = "../" * path.count("/")   # asset prefix: root pages "", cams/* "../"
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canon}">
<link rel="icon" href="/assets/bilbo-pup.png">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Bilbo Data">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canon}">
<meta property="og:image" content="{img}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(desc)}">
<meta name="twitter:image" content="{img}">
{FONTS}
<style>{CSS}</style>
<link rel="stylesheet" href="{up}assets/mobile.css">
<link rel="stylesheet" href="{up}assets/desktop.css">
<script src="{up}assets/mobile.js" defer></script>
<script type="application/ld+json">{json.dumps(jsonld, separators=(",", ":"))}</script>
</head>
<body>
<header><div class="wrap">
<img src="/assets/bilbo-pup.png" alt="Bilbo Data">
<a class="bn" href="/" style="color:var(--ink)">Bilbo Data</a>
<nav>
<a href="/cams/">Cameras</a>
<a href="/busiest.html">Busiest</a>
<a href="/data.html">Dataset</a>
<a href="/skyline.html">SkyLine</a>
<a href="/about.html">About</a>
</nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer><div class="wrap">
Bilbo Data reads the public NYC DOT traffic-camera network and turns it into
counts. Imagery belongs to NYC DOT; the counts are ours. Updated {TODAY}.
</div></footer>
</body>
</html>
"""
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(doc)
    return canon


# ------------------------------------------------------------- camera pages
os.makedirs(OUT, exist_ok=True)
urls = []

STREET_SPLIT = re.compile(r"\s*(?:@|at|&)\s*", re.I)

for cam in cams:
    name, area = cam["name"], cam["area"]
    parts = [p.strip() for p in STREET_SPLIT.split(name) if p.strip()]
    _dm = re.search(r"\s*(\((?:north|south|east|west)bound\))\s*$", name)
    _core = name[:_dm.start()] if _dm else name
    title = fit_title(f"{_core} Traffic Camera — {area}, NYC",
                      keep=_dm.group(1) if _dm else "")
    s = stats.get(cam["id"])

    if s and s["n"]:
        avg = s["veh"] / s["n"]
        # Lead with the measured number: it is the one thing this page has that
        # every other NYC camera listing does not.
        desc = fit_desc(f"Live NYC DOT camera at {name}, {area}. "
                        f"{s['veh']:,} vehicle passes counted here across "
                        f"{s['n']:,} samples — {avg:.1f} per frame, peaking at "
                        f"{s['peak']}.")
    else:
        desc = fit_desc(f"Live NYC DOT traffic camera at {name} in {area}, "
                        f"New York City — street view, exact location and the "
                        f"nearest cameras on the network.")

    # enrichment rows — these are what stop 917 pages reading as one template
    grade_label = GRADE.get(cam["id"], ("Not yet measured", 0, 0))[0]
    corridor_row = ""
    if cam["hwy"]:
        corridor_row = (f'<dt>Corridor</dt><dd><a href="/cams/road/'
                        f'{slug(HWY[cam["hwy"]])}.html">{esc(HWY[cam["hwy"]])}</a></dd>')
    facing_row = (f'<dt>Camera faces</dt><dd>{esc(FACING[cam["id"]])}</dd>'
                  if cam["id"] in FACING else "")
    st = nearest_station(cam)
    subway_row = ""
    if st and st[2] < 1.2:
        subway_row = (f'<dt>Nearest subway</dt><dd>{esc(st[0])}'
                      f'{f" ({esc(st[1])})" if st[1] else ""} · {st[2]:.2f} mi</dd>')

    nb = neighbours(cam)
    nb_html = "\n".join(
        f'<li><a href="/cams/{o["slug"]}.html">{esc(o["name"])}</a> '
        f'<span style="color:var(--mut)">· {d:.2f} mi</span></li>'
        for d, o in nb)

    if s and s["n"]:
        avg = s["veh"] / s["n"]
        mix = []
        for k, lbl in (("car", "cars"), ("truck", "trucks"), ("bus", "buses"),
                       ("moto", "motorcycles")):
            if s[k]:
                mix.append(f"{s[k]:,} {lbl}")
        busiest = s["hours"].most_common(1)
        busy_txt = (f"{int(busiest[0][0]):02d}:00–{(int(busiest[0][0]) + 1) % 24:02d}:00"
                    if busiest else "—")
        obs = f"""
<h2>What we have counted here</h2>
<p class="lede">Bilbo Data's counter has taken {s['n']:,} samples from this camera
and logged {s['veh']:,} vehicle passes — an average of {avg:.1f} vehicles in frame,
with a peak of {s['peak']} in a single sample. The busiest hour of the day at this
location is {busy_txt}.</p>
<dl class="kv">
<dt>Samples</dt><dd>{s['n']:,}</dd>
<dt>Vehicle passes</dt><dd>{s['veh']:,}</dd>
<dt>Average in frame</dt><dd>{avg:.1f}</dd>
<dt>Peak in frame</dt><dd>{s['peak']}</dd>
<dt>Vehicle mix</dt><dd>{esc(", ".join(mix)) if mix else "—"}</dd>
<dt>Busiest hour</dt><dd>{busy_txt}</dd>
</dl>"""
    else:
        obs = f"""
<h2>Counting status</h2>
<p class="lede">This camera is mapped on the Bilbo Data network but is not yet in
the counted set — the counter currently runs a rotating subset of the {len(cams)}
public NYC DOT cameras. The live image above is the current frame straight from
the DOT feed.</p>"""

    body = f"""
<div class="crumb"><a href="/">Bilbo Data</a> ›
<a href="/cams/">Cameras</a> ›
<a href="/cams/{BOROUGH_SLUG.get(area, slug(area))}.html">{esc(area)}</a> ›
{esc(name)}</div>
<p class="eyebrow">NYC DOT camera · {esc(area)}</p>
<h1>{esc(name)} — live traffic camera</h1>
<p class="lede">A live view of {esc(name)}{f", where {esc(parts[0])} meets {esc(parts[1])}" if len(parts) > 1 else ""},
in {esc(area)}, New York City. The frame below comes straight from the New York City
Department of Transportation camera network and refreshes on load. Bilbo Data reads
this network with computer vision and turns the pictures into vehicle counts.</p>
<img class="shot" src="{esc(cam['img'])}" alt="Live traffic camera view of {esc(name)}, {esc(area)}, New York City" fetchpriority="high" decoding="async">
<a class="cta" href="/cam.html?id={esc(cam['id'])}">Open the live counter →</a>
<h2>Location</h2>
<dl class="kv">
<dt>Intersection</dt><dd>{esc(name)}</dd>
<dt>Borough</dt><dd><a href="/cams/{BOROUGH_SLUG.get(area, slug(area))}.html">{esc(area)}</a></dd>
<dt>Coordinates</dt><dd>{cam['lat']:.6f}, {cam['lon']:.6f}</dd>
{corridor_row}
{facing_row}
{subway_row}
<dt>Picture quality</dt><dd>{esc(grade_label)}</dd>
<dt>Camera ID</dt><dd style="font-family:var(--mono);font-size:12px">{esc(cam['id'])}</dd>
<dt>Source</dt><dd>NYC DOT traffic camera network</dd>
</dl>
{obs}
<h2>Nearest cameras</h2>
<ul class="cols">
{nb_html}
</ul>
<h2>About this feed</h2>
<p class="lede">Bilbo Data is an open, independent read of public street cameras —
counts of what passes, not who passes. No faces, no plates, no identities. Read
<a href="/about.html">why we build it this way</a>, or browse
<a href="/cams/{BOROUGH_SLUG.get(area, slug(area))}.html">every camera in {esc(area)}</a>.</p>
"""

    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebPage",
                "@id": f"{SITE}/cams/{cam['slug']}.html",
                "name": title,
                "description": desc,
                "isPartOf": {"@type": "WebSite", "name": "Bilbo Data", "url": SITE},
                "about": {
                    "@type": "Place",
                    "name": f"{name}, {area}, New York, NY",
                    "geo": {"@type": "GeoCoordinates",
                            "latitude": cam["lat"], "longitude": cam["lon"]},
                    "address": {"@type": "PostalAddress",
                                "addressLocality": area,
                                "addressRegion": "NY",
                                "addressCountry": "US"},
                },
                "primaryImageOfPage": {"@type": "ImageObject", "contentUrl": cam["img"]},
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Bilbo Data", "item": SITE},
                    {"@type": "ListItem", "position": 2, "name": "Cameras",
                     "item": f"{SITE}/cams/"},
                    {"@type": "ListItem", "position": 3, "name": area,
                     "item": f"{SITE}/cams/{BOROUGH_SLUG.get(area, slug(area))}.html"},
                    {"@type": "ListItem", "position": 4, "name": name},
                ],
            },
        ],
    }
    urls.append((page(f"cams/{cam['slug']}.html", title, desc, body, ld), 0.6, "cam"))

# ---------------------------------------------------------- corridor pages
# "BQE traffic" and "Cross Bronx traffic cameras" are searched constantly and
# the borough hubs answer neither — a road is not a borough.
roads = collections.defaultdict(list)
for c in cams:
    if c["hwy"]:
        roads[HWY[c["hwy"]]].append(c)

for road, group in sorted(roads.items()):
    group.sort(key=lambda c: c["name"])
    rslug = slug(road)
    boroughs = sorted({c["area"] for c in group})
    counted = sum(1 for c in group if stats.get(c["id"], {}).get("n"))
    counted_line = (f" {counted} of them are counted frame by frame by Bilbo Data."
                    if counted else "")
    title = fit_title(f"{road} Traffic Cameras — {len(group)} Live Views")
    desc = fit_desc(f"Every NYC DOT traffic camera on the {road}: {len(group)} live "
                    f"views across {', '.join(boroughs)}, with exit numbers, "
                    f"direction of travel and measured vehicle counts.")
    items = "\n".join(
        f'<li><a href="/cams/{c["slug"]}.html">{esc(c["name"])}</a></li>' for c in group)
    body = f"""
<div class="crumb"><a href="/">Bilbo Data</a> › <a href="/cams/">Cameras</a> › {esc(road)}</div>
<p class="eyebrow">Corridor · {esc(", ".join(boroughs))}</p>
<h1>{esc(road)} traffic cameras</h1>
<p class="lede">The {esc(road)} is watched by {len(group)} public NYC DOT cameras.
This is all of them in one place, in order, with the exit and direction of travel
each one covers — so you can see the whole run of the road rather than guessing at
one intersection.{counted_line}</p>
<a class="cta" href="/">Open the live map →</a>
<h2>Every camera on the {esc(road)}</h2>
<ul class="cols">
{items}
</ul>
<h2>Other corridors</h2>
<ul class="cols">
{chr(10).join(f'<li><a href="/cams/road/{slug(r)}.html">{esc(r)} ({len(g)})</a></li>' for r, g in sorted(roads.items()) if r != road)}
</ul>
"""
    ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "description": desc,
        "url": f"{SITE}/cams/road/{rslug}.html",
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(group),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": c["name"],
                 "url": f"{SITE}/cams/{c['slug']}.html"}
                for i, c in enumerate(group)
            ],
        },
    }
    urls.append((page(f"cams/road/{rslug}.html", title, desc, body, ld), 0.85, "hub"))

# ------------------------------------------------------------ borough hubs
areas = collections.defaultdict(list)
for c in cams:
    areas[c["area"]].append(c)

for area, group in sorted(areas.items()):
    group.sort(key=lambda c: c["name"])
    aslug = BOROUGH_SLUG.get(area, slug(area))
    counted = sum(1 for c in group if stats.get(c["id"], {}).get("n"))
    counted_line = (f" {counted} of them are currently being counted frame-by-frame "
                    f"by Bilbo Data." if counted else "")
    title = fit_title(f"{area} Traffic Cameras — All {len(group)} Live Feeds")
    desc = fit_desc(f"All {len(group)} public NYC DOT traffic cameras in {area}, "
                    f"mapped and listed with live views. {counted} are counted "
                    f"frame by frame by Bilbo Data.")
    items = "\n".join(
        f'<li><a href="/cams/{c["slug"]}.html">{esc(c["name"])}</a></li>' for c in group)
    body = f"""
<div class="crumb"><a href="/">Bilbo Data</a> › <a href="/cams/">Cameras</a> › {esc(area)}</div>
<p class="eyebrow">Borough index</p>
<h1>{esc(area)} traffic cameras</h1>
<p class="lede">All {len(group)} public traffic cameras the New York City Department
of Transportation operates in {esc(area)}, each with a live view, coordinates and its
nearest neighbours.{counted_line} Pick an intersection.</p>
<a class="cta" href="/">Open the live map →</a>
<h2>All cameras in {esc(area)}</h2>
<ul class="cols">
{items}
</ul>
<h2>Other boroughs</h2>
<ul class="cols">
{chr(10).join(f'<li><a href="/cams/{BOROUGH_SLUG.get(a, slug(a))}.html">{esc(a)} ({len(g)})</a></li>' for a, g in sorted(areas.items()) if a != area)}
</ul>
"""
    ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "description": desc,
        "url": f"{SITE}/cams/{aslug}.html",
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(group),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": c["name"],
                 "url": f"{SITE}/cams/{c['slug']}.html"}
                for i, c in enumerate(group)
            ],
        },
    }
    urls.append((page(f"cams/{aslug}.html", title, desc, body, ld), 0.8, "hub"))

# --------------------------------------------------------- camera directory
total_counted = sum(1 for c in cams if stats.get(c["id"], {}).get("n"))
title = fit_title(f"All {len(cams)} NYC Traffic Cameras, by Borough")
desc = fit_desc(f"A browsable index of all {len(cams)} public New York City DOT "
                f"traffic cameras, sorted by borough, each with a live image "
                f"and location. Free, no login.")
body = f"""
<div class="crumb"><a href="/">Bilbo Data</a> › Cameras</div>
<p class="eyebrow">Full network index</p>
<h1>All {len(cams)} NYC traffic cameras</h1>
<p class="lede">New York City's Department of Transportation runs {len(cams)} public
street cameras. This is the whole list, borough by borough — every one with a live
view, its exact coordinates and the cameras nearest to it. Bilbo Data points computer
vision at this network and counts what passes: cars, trucks, buses, motorcycles.
No faces, no plates.</p>
<a class="cta" href="/">Open the live map →</a>
<h2>By borough</h2>
<dl class="kv">
{chr(10).join(f'<dt>{esc(a)}</dt><dd><a href="/cams/{BOROUGH_SLUG.get(a, slug(a))}.html">{len(g)} cameras</a></dd>' for a, g in sorted(areas.items(), key=lambda t: -len(t[1])))}
<dt>Counted now</dt><dd>{total_counted}</dd>
<dt>Total</dt><dd>{len(cams)}</dd>
</dl>
<h2>By road</h2>
<p class="lede">The expressways and parkways are watched end to end, so it is often
more useful to follow a corridor than a borough.</p>
<ul class="cols">
{chr(10).join(f'<li><a href="/cams/road/{slug(r)}.html">{esc(r)} ({len(g)})</a></li>' for r, g in sorted(roads.items(), key=lambda t: -len(t[1])))}
</ul>
<h2>What Bilbo Data does with them</h2>
<p class="lede">Every camera in this network is already public — the pictures are
there whether anyone looks or not. What has never existed is the aggregate: how many
vehicles actually move through a given intersection, hour by hour, in a form anyone
can download. That is the <a href="/data.html">open dataset</a> we publish. The
reasoning behind it is on the <a href="/about.html">about page</a>.</p>
"""
ld = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    "name": title,
    "description": desc,
    "url": f"{SITE}/cams/",
    "mainEntity": {
        "@type": "ItemList",
        "numberOfItems": len(areas),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": a,
             "url": f"{SITE}/cams/{BOROUGH_SLUG.get(a, slug(a))}.html"}
            for i, a in enumerate(sorted(areas))
        ],
    },
}
urls.append((page("cams/index.html", title, desc, body, ld, canon=f"{SITE}/cams/"), 0.9, "hub"))

# -------------------------------------------------------------- dataset page
net = {}
try:
    net = json.load(open(os.path.join(ROOT, "stats.json")))
except Exception:
    pass
w = (net.get("windows") or {}).get("1mo") or {}
title = fit_title("NYC Traffic Camera Vehicle Count Dataset — Free CSV")
desc = fit_desc("An open dataset of vehicle counts from New York City's public DOT "
                "traffic cameras: cars, trucks, buses and motorcycles per camera "
                "per timestamp. CSV and Parquet, free, no login.")
body = f"""
<div class="crumb"><a href="/">Bilbo Data</a> › Dataset</div>
<p class="eyebrow">Open data</p>
<h1>NYC traffic-camera vehicle counts — open dataset</h1>
<p class="lede">New York City publishes {len(cams)} live street cameras but publishes
no counts. Bilbo Data runs computer vision across that network and writes down what
passes: cars, trucks, buses and motorcycles, per camera, per timestamp, with a
brightness and lit/unlit flag so you can separate day from night. It is free, it needs
no login, and it is the same file the site itself reads.</p>
<dl class="kv">
<dt>Coverage</dt><dd>{total_counted} cameras counted, of {len(cams)} mapped</dd>
<dt>Rows</dt><dd>{sum(s['n'] for s in stats.values()):,} and growing</dd>
<dt>Fields</dt><dd>timestamp, camera id, name, car, moto, bus, truck, total, brightness, lit, samples, stale</dd>
<dt>Formats</dt><dd>CSV (rolling) and Parquet (daily)</dd>
<dt>Cadence</dt><dd>continuous; the counter commits straight to the repo</dd>
<dt>Licence</dt><dd>Free to use with attribution to Bilbo Data</dd>
<dt>30-day average</dt><dd>{w.get('avg_cars', '—')} vehicles in frame</dd>
<dt>30-day peak</dt><dd>{w.get('peak_cars', '—')} vehicles in frame</dd>
</dl>
<a class="cta" href="https://raw.githubusercontent.com/rabbishimon613-lang/bilbodata/main/counts.csv">Download the CSV →</a>
<h2>What is in it, honestly</h2>
<p class="lede">These are counts of objects in a frame, not a census. The cameras are
low-resolution and many are dark at night, which the <code>brightness</code> and
<code>lit</code> columns let you filter on. The <code>stale</code> column flags frames
the DOT feed repeated instead of refreshing. We publish the flaws with the data rather
than smoothing them away — see the <a href="/about.html">about page</a> for where the
ceiling actually is.</p>
<h2>What people use it for</h2>
<p class="lede">Traffic-volume comparisons between intersections, before-and-after
studies around street redesigns, congestion-pricing effects, bus-lane utilisation,
truck-route enforcement questions, and time-of-day demand curves for anyone modelling
deliveries in the city. If you want a specific intersection, every camera has its own
page under <a href="/cams/">the camera index</a>.</p>
"""
ld = {
    "@context": "https://schema.org",
    "@type": "Dataset",
    "name": "NYC Traffic Camera Vehicle Counts",
    "description": desc,
    "url": f"{SITE}/data.html",
    "keywords": ["New York City", "traffic", "vehicle counts", "traffic cameras",
                 "NYC DOT", "computer vision", "open data", "transportation"],
    "license": "https://creativecommons.org/licenses/by/4.0/",
    "isAccessibleForFree": True,
    "creator": {"@type": "Organization", "name": "Bilbo Data", "url": SITE},
    "spatialCoverage": {
        "@type": "Place",
        "name": "New York City, NY, USA",
        "geo": {"@type": "GeoShape", "box": "40.4774 -74.2591 40.9176 -73.7004"},
    },
    "variableMeasured": [
        {"@type": "PropertyValue", "name": "car", "description": "cars in frame"},
        {"@type": "PropertyValue", "name": "truck", "description": "trucks in frame"},
        {"@type": "PropertyValue", "name": "bus", "description": "buses in frame"},
        {"@type": "PropertyValue", "name": "moto", "description": "motorcycles in frame"},
        {"@type": "PropertyValue", "name": "brightness", "description": "mean frame brightness"},
    ],
    "distribution": [
        {"@type": "DataDownload", "encodingFormat": "text/csv",
         "contentUrl": "https://raw.githubusercontent.com/rabbishimon613-lang/bilbodata/main/counts.csv"},
    ],
}
urls.append((page("data.html", title, desc, body, ld), 0.9, "hub"))

# ------------------------------------------------------- busiest-cameras page
# A ranked table is the one thing on this site people link to without being
# asked, and it is the only page that answers "which NYC intersection is
# busiest" with a number rather than an opinion.
ranked = sorted(((cid, s) for cid, s in stats.items() if s["n"] >= 50),
                key=lambda t: t[1]["veh"] / t[1]["n"], reverse=True)
title = fit_title("The Busiest NYC Intersections, Ranked")
desc = fit_desc(f"Every camera Bilbo Data counts, ranked by how many vehicles are "
                f"actually in frame on average. {len(ranked)} New York City "
                f"intersections, measured from public DOT cameras, not estimated.")
rows = []
for i, (cid, s) in enumerate(ranked, 1):
    c = by_id[cid]
    avg = s["veh"] / s["n"]
    busiest = s["hours"].most_common(1)
    hr = f"{int(busiest[0][0]):02d}:00" if busiest else "—"
    rows.append(
        f'<tr><td>{i}</td><td><a href="/cams/{c["slug"]}.html">{esc(c["name"])}</a></td>'
        f'<td>{esc(c["area"])}</td><td>{avg:.1f}</td><td>{s["peak"]}</td>'
        f'<td>{hr}</td><td>{s["n"]:,}</td></tr>')

body = f"""
<div class="crumb"><a href="/">Bilbo Data</a> › Busiest intersections</div>
<p class="eyebrow">Ranking · updated {TODAY}</p>
<h1>The busiest NYC intersections we have counted</h1>
<p class="lede">New York City argues about which corner is worst without ever
measuring it. These are the {len(ranked)} intersections Bilbo Data currently counts
frame by frame, ranked by the average number of vehicles actually visible in a
frame. Not modelled, not estimated from a survey — counted off the city's own
public cameras. The counted set is a rotating subset of the {len(cams)} cameras;
every one of them has <a href="/cams/">its own page</a>.</p>
<div class="tscroll"><table class="rank">
<thead><tr><th>#</th><th>Intersection</th><th>Borough</th><th>Avg in frame</th>
<th>Peak</th><th>Busiest hour</th><th>Samples</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table></div>
<h2>How to read this</h2>
<p class="lede">"Average in frame" is how many vehicles the counter sees in a single
picture, averaged over every sample taken at that camera. It is a density measure,
not a flow rate — a jammed intersection scores high because the cars are sitting
there. Night frames are included, which drags the average down at cameras without
good lighting. The raw numbers behind this table are in the
<a href="/data.html">open dataset</a>.</p>
"""
ld = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    "name": "Busiest NYC intersections by measured vehicle density",
    "description": desc,
    "url": f"{SITE}/busiest.html",
    "numberOfItems": len(ranked),
    "itemListElement": [
        {"@type": "ListItem", "position": i, "name": by_id[cid]["name"],
         "url": f"{SITE}/cams/{by_id[cid]['slug']}.html"}
        for i, (cid, s) in enumerate(ranked, 1)
    ],
}
urls.append((page("busiest.html", title, desc, body, ld), 0.9, "hub"))

# ------------------------------------------------------------------- 404
# Vercel serves this for any unmatched path. A dead end here is a lost visitor;
# every borough and corridor is one click away instead.
body404 = f"""
<p class="eyebrow">404</p>
<h1>That page is not here</h1>
<p class="lede">The camera you were after may have been renamed by the DOT, or the
link is old. Nothing is lost — all {len(cams)} cameras are indexed below.</p>
<a class="cta" href="/cams/">Browse all {len(cams)} cameras →</a>
<h2>By borough</h2>
<ul class="cols">
{chr(10).join(f'<li><a href="/cams/{BOROUGH_SLUG.get(a, slug(a))}.html">{esc(a)} ({len(g)})</a></li>' for a, g in sorted(areas.items(), key=lambda t: -len(t[1])))}
</ul>
<h2>By road</h2>
<ul class="cols">
{chr(10).join(f'<li><a href="/cams/road/{slug(r)}.html">{esc(r)}</a></li>' for r in sorted(roads))}
</ul>
"""
page("404.html", "Page not found | Bilbo Data",
     "That page is not here. Every NYC DOT traffic camera Bilbo Data tracks is "
     "indexed by borough and by road.", body404,
     {"@context": "https://schema.org", "@type": "WebPage", "name": "Page not found"})
print("404.html    written")

# ------------------------------------------------------------------ sitemaps
core = [(f"{SITE}/", 1.0), (f"{SITE}/about.html", 0.7),
        (f"{SITE}/library.html", 0.6), (f"{SITE}/skyline.html", 0.7)]


def write_sitemap(path, entries):
    body = "\n".join(
        f"  <url><loc>{u}</loc><lastmod>{TODAY}</lastmod>"
        f"<changefreq>daily</changefreq><priority>{p}</priority></url>"
        for u, p in entries)
    with open(os.path.join(ROOT, path), "w") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                 f"{body}\n</urlset>\n")


cam_urls = [(u, p) for u, p, kind in urls if kind == "cam"]
hub_urls = [(u, p) for u, p, kind in urls if kind == "hub"]
write_sitemap("sitemap-cameras.xml", cam_urls)
write_sitemap("sitemap-core.xml", core + hub_urls)

with open(os.path.join(ROOT, "sitemap.xml"), "w") as fh:
    fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
             f'  <sitemap><loc>{SITE}/sitemap-core.xml</loc><lastmod>{TODAY}</lastmod></sitemap>\n'
             f'  <sitemap><loc>{SITE}/sitemap-cameras.xml</loc><lastmod>{TODAY}</lastmod></sitemap>\n'
             "</sitemapindex>\n")

with open(os.path.join(ROOT, "robots.txt"), "w") as fh:
    fh.write(f"""User-agent: *
Allow: /

# The counts are the point — crawlers and AI answer engines are welcome to them.
User-agent: GPTBot
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: CCBot
Allow: /

Sitemap: {SITE}/sitemap.xml
""")

print(f"cameras     {len(cam_urls)}")
print(f"hubs+data   {len(hub_urls)}")
print(f"sitemap     {len(cam_urls) + len(hub_urls) + len(core)} urls")
print("robots.txt  written")
