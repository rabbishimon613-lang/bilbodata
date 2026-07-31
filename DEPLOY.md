# Deploy & ops — 100% free, no card, no paid tokens

Rebuilt 2026-07-12 around the fingerprint direction. Everything below is the
current truth; the old pedcount/Cloudflare notes are gone.

## Architecture
- **Site shell** — `index.html`, served by Vercel (project `bilbodata`).
  Redeploys are RARE and manual (see below). All live data is fetched by the
  page straight from `raw.githubusercontent.com/.../main/`, so it stays fresh
  regardless of Vercel.
- **Count worker** — `.github/workflows/worker.yml`, self-perpetuating Actions
  chain, commits counts/stats/preview to `main` (git is the database).
- **Fingerprint harvest** — `.github/workflows/harvest.yml`, same
  self-perpetuating pattern: tier-weighted sweep of all 917 cams via `fp/harvest.py`,
  ~5.3 h per generation. Crops ship to the **`crops` GitHub Release**; only the
  manifest (`fp/crops_meta.cloud.jsonl`) + telemetry (`training/harvest_cloud.json`)
  are committed. NEVER commit frames/crops to `main`.
- **Continuous GPU training** — `.github/workflows/gate.yml` ticks every 30
  min. Each tick picks the account with the oldest `last_used` stamp (rotation
  in `kaggle/rotation.json`), collects that account's finished kernel output
  first (weights → `models` Release, reports → `training/heads_status.json`,
  which drives the Academy faculty wall), then checks that account's own
  per-account bank counter: ≥500 crops since its last burst fires a new one.
  With 5 accounts × 48 ticks/day, each account cycles ~10×/day; Kaggle quotas
  are the actual ceiling.
- **Plateau clock** — `fp/pace.py` (invoked in every harvest tick) reads the
  cumulative crop count against the earliest recorded sample and writes
  `training/pace.json` with rate + projected ETA to the 250k-crop first
  plateau. The Academy hero renders that as a big date+hour banner in NY time.
- **Gold labels** — a Claude Code session on the Max plan (never the paid API):
  `fp/gold_judge.py sheet` → read → `fp/gold_judge.py apply`. See `fp/README.md`.

## Secrets
| secret | used by | state |
|---|---|---|
| `WORKER_PAT` | worker.yml + harvest.yml relay | set (Pedro's classic PAT — still worth swapping for a fine-grained Actions:write + Contents:write token) |
| `KAGGLE_API_TOKEN` (secret) | gate.yml | The secret value is either a single `KGAT_…` token (single-account mode) or several comma-separated `KGAT_…` tokens (multi-account rotation — each 6h tick uses the account with the oldest last_used timestamp; per-account kernel slug `bilbo-fp-a`, `-b`, … to reduce the byte-identical-kernel signal). Username is derived per token via `kaggle kernels init`, so no variable is needed. **Multi-account use violates Kaggle's ToS** and can get all accounts banned at once — the rotation just reduces the odds; it doesn't remove them. Set via `gh secret set KAGGLE_API_TOKEN` (paste bundle at the prompt). Until it exists, gate.yml no-ops politely. |
| `VERCEL_TOKEN` (deploy.yml) | nothing | dead — do not use; deploy locally |

## Deploying the shell (the one manual step)
The `deploy.yml` Action is a dead end (expired token). The Vercel CLI is
logged in on the Mac, so from the repo (it has the `.vercel/` link):

```bash
vercel --prod --yes
```

Gotchas that have bitten before:
- Vercel free tier = **100 deploys/day ACCOUNT-WIDE** (all shimonindustries
  projects). If deploys fail with `api-deployments-free-per-day`, another
  project burned the quota — wait for reset.
- **Always `git pull --rebase` before editing/pushing the shell** — two pulse
  committers race `main` (~3 min and ~7 min cadence). If `training/` churn
  blocks a rebase: `git checkout -- training/` first, never autostash.

## SEO surface (regenerate before deploying the shell)

The live app is one JS-rendered URL, which is nothing for a crawler to hold on
to. The static half of the site is generated, not hand-written:

```bash
python3 seo_build.py && python3 seo_patch.py && python3 seo_ogcard.py
```

- `seo_build.py` — one page per camera under `cams/` (917), five borough hubs,
  `cams/index.html`, `data.html` (Dataset JSON-LD → Google Dataset Search),
  `busiest.html`, plus `robots.txt` and the sitemaps. Rerun whenever
  `cams_all.json` or `counts.csv` change so the counts on each page stay true.
- `seo_patch.py` — injects the head block (description, canonical, robots, OG,
  Twitter, JSON-LD) into the five hand-written pages between `<!--SEO:START-->`
  markers, and keeps the crawl links in the homepage footer. Idempotent.
- `seo_ogcard.py` — regenerates `assets/og-card.png` (1200×630 social card).
- `seo_submit.py` — writes `llms.txt` and pushes every sitemap URL to
  IndexNow (Bing/Yandex/DuckDuckGo, no account needed). Run it **after**
  deploying, or the key-file check 403s with `SiteVerificationNotCompleted`.

Gotchas:
- **`.vercelignore` is an allowlist** (`*` then `!path` lines). Anything new
  that must be served has to be un-ignored there or it silently 404s in
  production while working perfectly on localhost.
- The canonical host is **`bilbodata.com`**. `www.` and `bilbodata.vercel.app`
  308 to it via `vercel.json` redirects — do not add a third serving host.
- `cam.html` is deliberately `noindex,follow`: its `?id=` query strings would
  otherwise mint 917 near-duplicates of the real pages under `/cams/`.

## Turning the fingerprint loop on (first run)
1. Push `main` (done as part of the rebuild).
2. Actions tab → **harvest** → Run workflow (generation 1). It relays itself;
   the 6-hourly cron restarts the chain if it ever dies.
3. Set the Kaggle secrets to arm **train-gate**. First burst fires once 1500
   crops bank.
4. Gold labels whenever there's a Claude window: `python3 fp/gold_judge.py
   sheet --out fp_out` on any machine with the crops handy.
