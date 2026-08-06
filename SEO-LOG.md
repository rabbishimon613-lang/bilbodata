# SEO log — Bilbo Data

One dated section per nightly sweep. Read the most recent entry before the next
sweep so the routine builds on itself instead of re-auditing the same ground.
Anything found but deliberately left alone is written down with the reason.

Deploy doctrine for this project (from `DEPLOY.md`): redeploys are **rare and
manual**. The sweep commits its changes and stops there — it never runs
`vercel --prod`, and it never re-enables git auto-deploy.

---

## 2026-08-02 — first sweep

Baseline run. No prior log existed, so this entry doubles as the starting state.

### Checked

- **Surface size:** 917 camera pages, 5 borough hubs, 17 corridor hubs, plus the
  directory, dataset and ranking pages — 946 URLs across two sitemaps under a
  sitemap index.
- **Search Console:** still **unverified** for bilbodata.com, exactly as the
  previous check found. No verification file on the host (the only key file at
  the root is the IndexNow key), no service account, no gcloud config, and
  nothing Google-related in the keyring registry. **Blocked.**
- **Canonical host:** correct and enforced. `www.bilbodata.com` and
  `bilbodata.vercel.app` both 308 to `bilbodata.com`, verified live.
- **robots.txt:** correct — opens everything, names the sitemap, explicitly
  welcomes the AI answer engines. Nothing blocked that shouldn't be.
- **noindex:** exactly one page, `cam.html`, deliberately `noindex,follow` so its
  `?id=` query strings don't mint 917 near-duplicates of the real `/cams/` pages.
  Correct. No accidental noindex anywhere else.
- **Canonical tags:** present on all 946 pages, absolute, on the canonical host.
- **Structured data:** valid on every page — 918 `WebPage` + 917
  `BreadcrumbList` (camera pages use an `@graph` with `Place` and
  `GeoCoordinates`), 23 `CollectionPage` on the hubs, `Dataset` on the dataset
  page, `ItemList` on the rankings. Zero parse errors, zero missing `@context`.
- **Internal linking:** 14,552 distinct internal links. **Zero broken links and
  zero orphan pages** — every camera and hub page has inbound links.
- **Sitemap accuracy:** every sitemap URL resolves to a real file, and every
  generated file is in a sitemap. No stale pages left over from earlier slug
  changes.
- **Weight:** camera pages ~9 KB, hubs ~9–16 KB — fine. The homepage shell is
  127 KB, but that is the JS app itself, not the crawlable surface.

### Changed

- **Every title and description on the static surface was over the SERP limit;
  the templates in `seo_build.py` were rewritten and all 942 pages regenerated.**
  This was systematic, not per-page, so it was fixed once in the generator:
  - Titles: **all 923 camera titles exceeded 60 characters** (average 82, worst
    126), so Google was cutting off the half that matters. Dropped the "Live
    View" filler and moved the brand suffix behind a length check. Average title
    is now **55 characters, with none over 60**.
    Before: `1 Ave @ 110 St Traffic Camera — Live View, Manhattan NYC | Bilbo Data`
    After:  `1 Ave @ 110 St Traffic Camera — Manhattan, NYC | Bilbo Data`
  - Descriptions: **907 of 923 exceeded 160 characters** (worst 245). Rewritten
    to lead with the measured vehicle count — the one thing these pages have
    that no other NYC camera listing does — and clamped at a word boundary.
    Average is now **151 characters, none over 160**.
  - The same fix was applied to the corridor hubs, borough hubs, camera
    directory, dataset page and rankings page, which were all over too.
- **Two pages had identical titles.** The eastbound and westbound cameras at
  Stewart Ave / Kosciuszko Bridge differ only by the direction marker, which is
  exactly what truncation was cutting. The title fitter now preserves a trailing
  direction marker through truncation. **Zero duplicate titles and zero
  duplicate descriptions** across all 942 pages now.
- Sitemaps, `robots.txt` and `404.html` regenerated as part of the same run.

### Blocked — needs the user, once

- **bilbodata.com is not verified in Search Console.** Nothing here can read
  indexed-vs-excluded counts, coverage errors, top queries, or impressions, so
  **no indexing or ranking numbers appear in this entry — none were
  measurable.** To unblock, one of:
  1. Add the property in Search Console and verify by DNS TXT record (simplest —
     the domain's DNS is already managed for the Vercel setup), or drop the
     Google HTML verification file at the repo root **and un-ignore it in
     `.vercelignore`**, which is an allowlist: an un-listed file silently 404s in
     production. Then, for automated reads, create a Google Cloud service
     account, enable the Search Console API, add its email as a full user on the
     property, and store the JSON key where this routine can read it.

  Until then this line repeats in every sweep.

### Waiting on a manual redeploy

**The metadata fixes above are committed but NOT live.** Per `DEPLOY.md` the
shell is deployed by hand, so the sweep stopped at the commit. To publish:

```bash
vercel --prod --yes
```

(from the repo root, which holds the `.vercel/` link). `git pull --rebase`
first — two pulse committers race `main`.

### Found, not changed — with reasons

- **IndexNow was deliberately not submitted this run.** The URL set did not
  change; only the metadata on existing pages did, and none of it is live yet.
  Submitting now would spend the signal on pages that still serve the old tags.
  Run `python3 seo_submit.py` **after** the manual redeploy — its notes are
  right that it 403s if run before the host serves the key file.
- **`/cams/road/` returns 404.** There is no corridor index page, only the 17
  individual corridor hubs, all of which are live and linked. Nothing points at
  the bare directory, so this is invisible to crawlers rather than a broken
  link. A corridor index would be a reasonable addition, but it is a new page,
  not a fix.
- **Git auto-deploy stays disabled** (`vercel.json` sets
  `git.deploymentEnabled.main = false`). Left exactly as is, per doctrine.

---

## 2026-08-04 — second sweep

### The headline: last sweep's work is still not live, and had never been pushed

The metadata fix from 2026-08-02 is **still not deployed**. Verified directly:
`bilbodata.com/cams/atlantic-ave-111-st.html` serves the old 76-character title
(`… Traffic Camera — Live View, Brooklyn NYC | Bilbo Data`) while the file on
disk carries the fixed 51-character one.

Worse, that commit had never left this machine — the branch was **ahead 1** on
`main`, so the fix existed only in this working copy. It is now rebased onto
origin and pushed, together with this sweep's commit. Pushing is safe here:
`vercel.json` still sets `git.deploymentEnabled.main = false`, so nothing
deploys off a push. That setting was not touched.

**Two sweeps of metadata work are now queued behind one manual redeploy.**

### Checked

- **Surface size:** 917 camera pages + 25 hubs/data pages = 932 audited;
  **947 sitemap URLs** (up 1 — see research.html below).
- **Search Console:** still **unverified** for bilbodata.com, second sweep
  running. Re-checked: no Google verification file in the repo, no service
  account, no `gcloud` config, no Google environment variables, and none of the
  keyring's 28 entries is a Google credential. **No indexing, impression or
  ranking figures appear in this entry because none were measurable.**
- **Canonical host:** enforced and verified live — `www.bilbodata.com` and
  `bilbodata.vercel.app` both 308 to `bilbodata.com`.
- **robots.txt:** correct, opens everything, names the sitemap index, welcomes
  the AI answer engines.
- **noindex:** exactly one page, `cam.html`, deliberate and correct.
- **Canonicals:** now present on all 932 pages (was 931 — see below).
- **Structured data:** 919 `WebPage`, 917 `BreadcrumbList`, 8 `CollectionPage`,
  plus `WebSite`, `AboutPage`, `Dataset` and `ItemList`. **Zero parse errors.**
- **Duplicates:** zero duplicate titles, zero duplicate descriptions.
- **Internal links / orphans:** **zero broken internal links, zero orphans.**
  A first pass flagged 1,848 broken links and 1 orphan; both were artefacts of
  the audit script resolving relative hrefs against the repo root instead of the
  page directory. `assets/desktop.css` and `assets/mobile.css` are present and
  return 200 live. The only two remaining "links" are JavaScript template
  fragments (`$2`, `'+d.file+'`) inside research.html, not markup.
- **Weight:** unchanged; camera pages ~9 KB.

### Changed

- **The five hand-written pages were still over the SERP limits.** The last
  sweep fixed the *generated* templates, and those hold up — all 923 camera
  pages measure inside the window. The hand-written ones were missed:
  - `skyline.html` title 67 chars → 54 (dropped the `| Bilbo Data` suffix, the
    same treatment the camera titles already get behind a length check).
  - `library.html` title 63 → 54.
  - `index.html` description 181 → 157, keeping the "No faces, no plates."
    differentiator and cutting elsewhere.
  - `about.html` description 182 → 148.
  - `library.html` description 181 → 140.
  Fixed in `seo_patch.py`, not by hand-editing the HTML, so the next
  regeneration keeps them.
- **`research.html` was invisible to search.** It ships with the Research
  Library (commit `f8cc68a8`), is live, returns 200 and is linked from
  `library.html` — but it had **no meta description, no canonical, no Open
  Graph, no structured data, and appeared in no sitemap**. It was the only page
  on the site missing a canonical. Added to `seo_patch.py` with a real title,
  description and `CollectionPage` schema, and added to the core sitemap in
  `seo_build.py`. That is the +1 URL.
- **Whole surface regenerated** against current counts
  (`seo_build.py` → `seo_patch.py` → `seo_ogcard.py`), so the vehicle counts
  quoted in every camera description are current rather than two days stale.

### A measurement note for future sweeps

An audit that measures `<title>` and `<meta description>` straight out of the
HTML **overcounts by 4 characters for every `&`**, because the source carries
`&amp;`. That produced a false alarm this run: 14 titles and 10 descriptions
looked over-limit, and after unescaping only 2 titles and 3 descriptions
actually were — all of them on the hand-written pages, none on a camera page.
Measure what Google renders, not what the file stores.

### Blocked — needs the user, once

- **bilbodata.com is not verified in Search Console.** Unchanged. To unblock:
  add the property and verify by DNS TXT record (simplest — the domain's DNS is
  already managed for Vercel), or drop the Google HTML verification file at the
  repo root **and un-ignore it in `.vercelignore`**, which is an allowlist — an
  unlisted file silently 404s in production. Then, for automated reads, create a
  Google Cloud service account, enable the Search Console API, add its email as
  a full user on the property, and store the JSON key where this routine can
  read it.

  Until then this line repeats in every sweep.

### Waiting on a manual redeploy

**Everything above is committed and pushed but NOT live.** Per `DEPLOY.md` the
shell is deployed by hand. To publish, from the repo root:

```bash
vercel --prod --yes
```

`git pull --rebase` first — the pulse committers race `main`.

**After the redeploy, run `python3 seo_submit.py`** to push the URL set to
IndexNow. It 403s if run before the host serves the changes.

### Found, not changed — with reasons

- **IndexNow was again deliberately not submitted.** Same reasoning as last
  sweep, and it still holds: the URL set barely changed (one addition), while
  everything that *did* change is metadata on pages that still serve the old
  tags in production. Submitting now spends the signal on stale pages. It should
  run immediately after the redeploy — at which point two sweeps of metadata
  changes plus `research.html` all become worth announcing at once.
- **`/cams/road/` still returns 404.** Unchanged: there is no corridor index,
  only the 17 individual corridor hubs, all live and linked. Nothing points at
  the bare directory, so it is invisible to crawlers rather than broken. A
  corridor index would be a new page, not a fix.
- **Git auto-deploy stays disabled.** Left exactly as is, per doctrine.
- **The repo needs housekeeping.** Git reported "too many unreachable loose
  objects" and a stale `.git/gc.log` blocking automatic cleanup — a side effect
  of the pulse committers' churn. Not an SEO matter and not touched, but it will
  keep nagging on every git operation until someone runs `git prune`.

---

## 2026-08-05 — third sweep

### The headline: two sweeps of work are finally live

The 08-02 and 08-04 entries both ended with everything committed, pushed and
**not deployed**, waiting on a manual redeploy that never came. That rule is
retired as of 2026-08-04 (Pedro's call) precisely because the queue kept
growing. This run deployed.

Confirmed stale before deploying — live vs. local titles:

| page | live (before) | local (now) |
|---|---|---|
| `skyline.html` | 67 chars, `… Live Trains \| Bilbo Data` | 54 |
| `library.html` | 63 chars, `… Can Tell Apart on NYC Cameras` | 54 |

So the SERP-window fixes from both previous sweeps had been sitting unpublished
for three days. They are live now.

### Search Console — still blocked, and now confirmed at the source

Checked directly in the signed-in console this run: the account holds exactly
**two** properties, `kiripedia.org` and `https://cyberputa.vercel.app/`.
**There is no bilbodata.com property at all** — it was never added, so there is
nothing to verify and nothing to read. No impressions, ranking or coverage
figures appear in this entry because none are measurable.

To unblock, once: add `bilbodata.com` as a property and verify by DNS TXT
record (simplest — the domain's DNS is already managed for Vercel), or drop the
Google HTML verification file at the repo root **and un-ignore it in
`.vercelignore`**, which is an allowlist — an unlisted file silently 404s in
production. Then, for automated reads, create a Google Cloud service account,
enable the Search Console API, add its email as a full user on the property,
and store the JSON key where this routine can read it.

This line repeats every sweep until it is done.

### Changed

- **`research.html` was orphaned for crawlers, and the last sweep's note that
  it "is linked from `library.html`" was true only in a browser.** Its sole
  inbound link is built in JavaScript — `href="research.html?doc='+d.id+'"`
  inside a template string — which no crawler follows. So the page was
  reachable by a human, present in the sitemap, and had **zero crawlable
  inbound links**.

  Added a real anchor to the homepage footer crawl block in `seo_patch.py`
  (template, not a hand-edit, so regeneration keeps it), with a comment
  recording why it has to exist. Verified in the built `index.html`.

- **Whole surface regenerated** (`seo_build.py` → `seo_patch.py` →
  `seo_ogcard.py`) against current counts, so the vehicle numbers quoted in
  every camera description are current rather than three days stale. 917 camera
  pages, 25 hubs + data pages, 947 sitemap URLs, `robots.txt` and the 1200×630
  OG card rewritten.

### Checked — all clean

Measured on the **rendered** text, not the stored HTML, per the `&amp;` lesson
from the last sweep:

- **Metadata, 949 pages:** 0 missing titles, 0 missing descriptions, **0 titles
  over 60, 0 descriptions over 160, 0 duplicate titles, 0 duplicate
  descriptions.** Average title 55, average description 151. Both previous
  sweeps' fitter work holds.
- **Canonicals:** present on all 949 pages. Exactly one `noindex` — `cam.html`,
  which is deliberate (its `?id=` query strings would otherwise mint 917
  near-duplicates of the real `/cams/` pages).
- **Structured data:** 0 JSON-LD parse errors across all 949 pages. 919
  WebPage, 918 WebSite/Place/ImageObject, 917 GeoCoordinates + PostalAddress +
  BreadcrumbList, 4,738 ListItem, 25 CollectionPage, plus the single Dataset,
  GeoShape and DataDownload on `data.html`.
  - *Audit note for future runs:* a naive type count reports 917 pages with a
    missing `@type`. That is wrong — the camera pages wrap their schema in
    `@graph`, and the count has to recurse into it. Don't raise this as a bug
    again.
- **Internal links:** **0 broken internal links** across the site. Every one of
  the 917 camera pages has inbound links, median 7. The only true crawl-orphans
  were `404.html` and `cam.html` (both correct) and `research.html` (fixed
  above).
  - *Audit note:* `cams/index.html` also shows as an orphan under a naive
    check. It is not — the homepage links it as `/cams/`, and a path normalizer
    has to expand a bare trailing slash to `index.html` to see it.
- **Robots.txt:** allows everything, and explicitly welcomes GPTBot,
  PerplexityBot, ClaudeBot, Google-Extended and CCBot. Sitemap declared.

### Found, not changed — with reasons

- **`/cams/road/` still returns 404.** Unchanged and still not a defect: there
  is no corridor index, only the 17 individual corridor hubs, all live and
  linked. Nothing points at the bare directory, so it is invisible to crawlers
  rather than broken. A corridor index would be a new page, not a fix.
- **Git auto-deploy stays disabled.** Left exactly as is, per doctrine. This
  run deployed from the CLI.
- **The `.gitignore` edit in the working tree is not this routine's** — it adds
  `.env` / `.env.*` and belongs to another session. Left unstaged and
  uncommitted, as were the 93 untracked files from the harvest and vision work.
  Nothing was staged with `git add -A`.
- **The repo still needs housekeeping.** Git reports "too many unreachable
  loose objects" and a stale `.git/gc.log` blocking automatic cleanup — a side
  effect of the pulse committers' churn. Not an SEO matter and not touched, but
  it will keep nagging on every git operation until someone runs `git prune`.

### Deployed — yes, and IndexNow finally fired

**Live and verified** on `bilbodata.com` after `vercel --prod --yes
--archive=tgz`:

- `skyline.html` now serves the 54-char title, `library.html` the 54-char one —
  the 08-02 and 08-04 fixes are published at last.
- The new `Research library` anchor is in the live homepage footer, so
  `research.html` finally has a crawlable path in.

**IndexNow: 947 URLs submitted, HTTP 200**, plus `llms.txt` rewritten. This was
deliberately withheld on both previous sweeps because production was serving
stale tags and submitting would have spent the signal on old pages. That
reasoning was correct and is now discharged: the whole surface is current, so
three sweeps' worth of metadata changes plus `research.html` were announced in
one go.

**Deploy needed `--archive=tgz`.** The plain `vercel --prod --yes` failed with
`api-upload-free` — more than 5,000 file uploads in 24 hours across the
account. This is a **new, account-wide** ceiling worth writing into `DEPLOY.md`
next to the existing 100-deploys/day note: a 949-page surface plus KiriPedia's
1,849 pages trips it on any day both sites deploy. **Future sweeps should use
`vercel --prod --yes --archive=tgz` directly** rather than rediscovering this.

---

## 2026-08-06 — nightly sweep

**Deploy doctrine changed.** The "commit and stop, never run `vercel --prod`"
rule at the top of this file is **retired as of 2026-08-04 (Pedro's call)**,
because the queue of undeployed changes just grew every sweep. Every sweep now
deploys. Git auto-deploy stays off; deploys remain explicit CLI actions.

### Search Console — still blocked, and this is the fourth run reporting it

Checked directly this run: `sc-domain:bilbodata.com` returns **"Oops, you don't
have access to this property"** for the signed-in account
(`ppargabastos@gmail.com`). No service account, no stored token, nothing in the
keyring. **There are still no measurable numbers for this site — no
impressions, no clicks, no coverage counts, and none are estimated below.**

**The one-time action that unblocks it:** in Search Console, add `bilbodata.com`
as a property under `ppargabastos@gmail.com` and choose **HTML file
verification**, then drop the token filename into this repo — the file will be
committed, un-ignored in `.vercelignore` (it is an allowlist) and deployed on
the next sweep, after which every future run can read real numbers. A DNS TXT
record at the registrar works equally well and needs no code change.

### Changed — the freshness signal was lying, and that is now fixed

This is the substantive finding of the run, and it is systematic, so it was
fixed in the generator rather than per page.

**What was wrong.** Every camera page printed `Updated {TODAY}` in its footer
and every one of the 947 sitemap entries carried `lastmod={TODAY}`, both
stamped from the build clock. So a nightly regeneration told Google that the
entire 947-page surface had changed — every night, unconditionally.

**Why that is not merely cosmetic.** The counts behind those pages have not
moved since **2026-07-20** (verified: that is the newest `ts` in `counts.csv`,
and the file itself was last written 2026-07-27). Diffing this run's
regeneration against the last commit, **every single one of the 917 camera
pages differed by exactly one line — the date string.** Zero had a changed
vehicle count. The site was announcing daily freshness for data that was
seventeen days stale, which wastes crawl budget on 917 unchanged pages and
teaches Google to disregard `lastmod` for this host entirely.

**The fix, in `seo_build.py`:**

- New `_data_date()` reads the real high-water mark out of `counts.csv`. The
  footer now reads **"Counts current to 2026-07-20"** instead of "Updated
  <today>", and the rankings page eyebrow likewise. The page now states
  something true.
- New `lastmod_for()` hashes each page's bytes and only advances `lastmod` when
  the content actually changed, with state in `seo_lastmod.json` (947 entries,
  committed so it persists between sweeps). The sitemap-index `lastmod` values
  are now derived from the maximum of their children rather than from the clock.
- `_local_path()` maps a bare trailing slash to `index.html`, because
  `https://bilbodata.com/cams/` is a directory on disk — without it that one URL
  raises `IsADirectoryError` and silently re-stamps today forever. Caught by
  reconciling the state file (946) against the sitemap (947); the same
  normalisation trap the internal-link audit has to handle.

**Verified by running the whole chain three times in a row:** the second and
third runs produce a **byte-identical `sitemap-cameras.xml`**. Before this
change every run rewrote all 917 lines. This run itself is the baseline, so all
947 URLs legitimately carry `2026-08-06` — the footer text genuinely changed on
every page. From the next sweep on, only pages that really change will move.

### Checked — all clean

Measured on **rendered** text (`html.unescape`), per the `&amp;` lesson, with
JSON-LD counts recursing into `@graph`, per the note below.

- **Metadata, 949 pages:** 0 missing titles, 0 missing descriptions, **0 titles
  over 60, 0 descriptions over 160, 0 duplicate titles, 0 duplicate
  descriptions.** Average title 54, average description 150.
- **Canonicals:** present on all 949. **noindex: exactly one — `cam.html`**,
  deliberate, so its `?id=` query strings don't mint 917 near-duplicates.
- **Structured data:** **0 JSON-LD parse errors** across all 949 pages. 919
  WebPage, 918 WebSite/Place/ImageObject, 917 GeoCoordinates + PostalAddress +
  BreadcrumbList, 4,738 ListItem, 25 CollectionPage, 24 ItemList, plus the
  Dataset, AboutPage and Organization singletons.
- **Internal links: 0 broken, 0 orphans.** Every camera and hub page has
  inbound links. `404.html` is the only page with none, which is correct.
- **robots.txt:** allows everything, declares the sitemap, explicitly welcomes
  GPTBot, PerplexityBot, ClaudeBot, Google-Extended and CCBot.
- **Sitemaps:** 947 URLs, set and ordering both identical to the last commit —
  no page added, dropped or reshuffled.

### Audit notes for future runs — do not re-raise these

- **`research.html -> $2` is not a broken link.** A naive `href="..."` scrape
  picks up `href="$2"` from a JavaScript regex replacement string inside an
  inline markdown renderer (`seo_patch.py`-injected page, lines ~155–157). It is
  a capture-group reference, not a URL. Third sweep to notice it; recording it
  so it is the last.
- The `@graph`-recursion note and the `cams/index.html` orphan note from
  previous entries both still apply and were both handled correctly here.

### Found, not changed — with reasons

- **The data pipeline appears to be dead, and that is bigger than SEO.**
  `counts.csv` last changed 2026-07-27 and its newest reading is 2026-07-20.
  The self-perpetuating Actions chain that is supposed to keep committing counts
  has produced nothing since then; the last `train-gate` rotation tick was
  2026-08-02. **Not touched** — reviving GitHub Actions chains is outside an SEO
  sweep's remit and racy against the pulse committers. But every camera page is
  now honestly dated, so the staleness is visible rather than hidden. **Flagged
  for the user: the counts are the entire value proposition of these 917 pages,
  and they stopped seventeen days ago.**
- **`changefreq` is still `daily` on every URL.** Left alone deliberately. It is
  wrong today, but it becomes right again the moment the worker is revived, and
  `lastmod` — which is the field Google actually weighs — is now honest. Revisit
  only if the pipeline stays dead.
- **`/cams/road/` still returns 404.** Unchanged and still not a defect: there
  is no corridor index, only the 17 individual corridor hubs, all live and
  linked. Nothing points at the bare directory.
- **The `.gitignore` edit in the working tree is not this routine's.** It adds
  `.env` / `.env.*` and belongs to another session. A `git pull --rebase` was
  required and refused to run with it dirty, so it was stashed, the rebase ran
  ("Already up to date"), and it was restored and **verified byte-identical to a
  backup taken first**. Left unstaged and uncommitted, along with the ~90
  untracked harvest and vision files. Nothing was staged with `git add -A`.
- **Repo housekeeping still nagging:** "too many unreachable loose objects" and
  a stale `.git/gc.log`. Not an SEO matter; someone should run `git prune`.
