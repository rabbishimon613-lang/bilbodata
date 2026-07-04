# Deploy: 100% free, no card, no paid tokens

Architecture:
- **Worker** = GitHub Actions (`.github/workflows/count.yml`), runs every 5 min.
- **Database** = this git repo (`counts.csv`, `stats.json`, `counts.json`, `preview/`).
- **Site** = Cloudflare Pages, serves the repo root, redeploys on every push.

## 1. Push to GitHub (public repo = unlimited free Actions minutes)
```bash
cd /Volumes/EOS_DIGITAL/pedcount
git init
git add -A
git commit -m "pedcount: Crown Heights aggregate traffic"
gh repo create pedcount --public --source=. --push
# (or make the repo in the GitHub UI and `git remote add origin ... && git push -u origin main`)
```

## 2. Turn the worker on
- Repo → **Actions** tab → enable workflows.
- Click **count** → **Run workflow** once to seed it, then it self-runs every 5 min.
- Data commits land automatically as `tick <timestamp>`.

## 3. Host the dashboard on Cloudflare Pages
- dash.cloudflare.com → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**.
- Pick the `pedcount` repo. Build command: *(none)*. Output dir: `/` (root).
- Deploy. Every bot push auto-redeploys. You get a `*.pages.dev` URL.

## Notes / later
- **Cadence:** GitHub cron floor is 5 min. Fine for trends; not second-by-second.
- **Repo bloat:** committing 9 preview JPGs every 5 min grows git history. If it gets
  heavy, drop `preview/` from the commit step (charts + counts are the real value) or
  squash history periodically.
- **Slim later:** export YOLO to ONNX + opencv-dnn to kill the ~2GB torch install and
  make each Action run start in seconds.
- **Vercel:** when ready, move the frontend to Vercel with API routes reading a real DB
  (Supabase/Neon) instead of flat files — better querying for big date ranges.
