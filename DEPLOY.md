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
- **Burst GPU training** — `.github/workflows/gate.yml` (6-hourly) fires the
  `kaggle/` kernel when ≥1500 new crops have banked, collects finished output:
  weights → `models` Release, reports → `training/heads_status.json` (that file
  drives the Academy "faculty" wall).
- **Gold labels** — a Claude Code session on the Max plan (never the paid API):
  `fp/gold_judge.py sheet` → read → `fp/gold_judge.py apply`. See `fp/README.md`.

## Secrets
| secret | used by | state |
|---|---|---|
| `WORKER_PAT` | worker.yml + harvest.yml relay | set (Pedro's classic PAT — still worth swapping for a fine-grained Actions:write + Contents:write token) |
| `KAGGLE_USERNAME` / `KAGGLE_KEY` | gate.yml | **not set yet** — kaggle.com → Settings → Create New Token, then `gh secret set KAGGLE_USERNAME` and `gh secret set KAGGLE_KEY`. Until then gate.yml no-ops politely. |
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

## Turning the fingerprint loop on (first run)
1. Push `main` (done as part of the rebuild).
2. Actions tab → **harvest** → Run workflow (generation 1). It relays itself;
   the 6-hourly cron restarts the chain if it ever dies.
3. Set the Kaggle secrets to arm **train-gate**. First burst fires once 1500
   crops bank.
4. Gold labels whenever there's a Claude window: `python3 fp/gold_judge.py
   sheet --out fp_out` on any machine with the crops handy.
