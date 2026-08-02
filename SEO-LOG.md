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
