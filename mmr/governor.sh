#!/bin/bash
# Mac-mini governor for the Bilbo training rig.
#
# The training workers (harvest, make/model pretrain, the YOLO loop and the
# short-lived children it spawns each generation) are the point — we WANT them
# grinding. But on an 8GB M1 they were eating all four performance cores and
# making the rest of the machine unusable.
#
# This keeps them useful but polite: every cycle it re-pins every Bilbo worker
# (and any fresh child) to background QoS. On Apple Silicon that parks them on
# the 4 efficiency cores and leaves all 4 performance cores free for whatever
# Pedro is doing in the foreground. Training keeps running, just off the fast
# cores. It also floors their nice value as a second lever.
#
# Never kills anything (per policy: only money/data-integrity kills, never
# hardware/heat). Pure scheduling.
ROOT="/Volumes/EOS_DIGITAL/bilbodata"
LOG="$ROOT/mmr/governor.log"
# scripts whose python processes are ours to tame
PAT='hd_harvest|vmmr_pretrain|handoff/loop.py|live_view.py|publish_training|live_eval.py|ultralytics|yolo'

echo "[gov] start $(date '+%F %T')  (pins Bilbo workers to E-cores, frees the 4 P-cores)" >> "$LOG"
while true; do
  n=0
  for pid in $(pgrep -f "$PAT"); do
    # skip the governor itself / grep noise
    taskpolicy -b -p "$pid" 2>/dev/null && renice 20 -p "$pid" >/dev/null 2>&1 && n=$((n+1))
  done
  # heartbeat every ~5 min so the log doesn't balloon
  if [ $(( $(date +%s) % 300 )) -lt 20 ]; then
    la=$(sysctl -n vm.loadavg | awk '{print $2}')
    echo "[gov] $(date '+%F %T')  pinned=$n  load1=$la" >> "$LOG"
  fi
  sleep 15
done
