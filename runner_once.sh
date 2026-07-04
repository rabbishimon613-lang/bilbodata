#!/bin/bash
# One Bilbo pulse: fetch a fresh minute from every camera, tag every vehicle,
# roll up all analytics, archive finished days forever, and push.
# Driven by launchd every few minutes (com.bilbodata.runner) so the site keeps
# pulsing on this machine regardless of GitHub Actions' ~hourly cron throttle.
# Stop it any time:  launchctl unload ~/Library/LaunchAgents/com.bilbodata.runner.plist
set -o pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
REPO="/Volumes/EOS_DIGITAL/bilbodata"
cd "$REPO" || exit 0
[ -d .git ] || exit 0                       # drive not mounted -> skip quietly

LOCK="$REPO/.runner.lock"
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  exit 0                                     # previous pulse still running
fi
echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT

git config user.name  "bilbo-runner"  2>/dev/null
git config user.email "runner@bilbodata.local" 2>/dev/null
git pull --rebase --autostash origin main >/dev/null 2>&1 || true

python3 counter.py --minute >>"$REPO/runner.log" 2>&1     # detect + track + tag one minute
python3 storage.py compact   >>"$REPO/runner.log" 2>&1 || true   # archive finished days (never today)
python3 pipeline.py          >>"$REPO/runner.log" 2>&1 || true   # metric/fleet/speed/trails over ALL history

git add counts.csv vehicles.csv trips.csv counts.json stats.json \
        calibration.json fleet.json speed.json trajectories.json \
        data data_vehicles data_trips 2>/dev/null
# thumbnails are heavy in git history -> refresh them only on the hour and half-hour
case "$(date +%M)" in 00|05|30|35) git add preview 2>/dev/null ;; esac

git commit -m "pulse $(date -u +%FT%TZ)" >/dev/null 2>&1 || exit 0
git pull --rebase --autostash origin main >/dev/null 2>&1 || true
git push >/dev/null 2>&1 || true
