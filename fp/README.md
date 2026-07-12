# fp/ — the fingerprint pipeline

Bilbo's second act: count everywhere, **read** on the cameras that can carry it.
Everything here is tier-gated (see `tiers.py`) and abstain-first: a confident
wrong label is the one forbidden output.

## The loop

```
harvest.py ──► crops + crops_meta.jsonl          (perpetual · tier-weighted · all 917 cams)
     │
     ├─► teacher_label.py ──► labels_auto.jsonl  (bulk: high-conf vehicle class only)
     └─► gold_judge.py    ──► labels_gold.jsonl  (Claude on the Max plan reads contact
                                                  sheets: make/model/color/company/
                                                  plate-state/bus — or abstains)
                                   │
                    company reads resolve through company_match.py
                    against ../company_catalogue.csv (the living log)
     ▼
train_heads.py  ──► models/<head>.pt + <head>_report.json   (Kaggle GPU bursts)
publish_heads.py ─► ../training/heads_status.json           (the Academy "faculty" wall)
```

## Where things run (all free, no card)

| piece | where | how |
|---|---|---|
| harvest | GitHub Actions (`.github/workflows/harvest.yml`) | bounded ~5.5 h loop, self-dispatching relay; crops ship to a **GitHub Release**, only the manifest + telemetry are committed |
| gold labels | a Claude Code session on the Mac | `gold_judge.py sheet` → Claude reads → `gold_judge.py apply` |
| head training | Kaggle (`kaggle/`) | `gate.yml` fires a kernel when enough new crops bank; weights come back to a Release |
| telemetry | committed to `main` | `harvest_status.json`, `heads_status.json`, `crops_meta.jsonl` |

Never commit frames or crops to `main` — git bloat is the one thing that
breaks the free tier. Paths are configurable via `BILBO_ROOT` / `FP_OUT` /
`--out`, so every script runs unchanged on the Mac, Actions, or Kaggle.

## The three hard rules

1. **Tier gate** — `tiers.HEAD_TIERS` decides which cameras may even be asked
   about which handle. A purple cam is never asked for a make.
2. **Abstain bar** — every head trains with crop-height + day/night as inputs
   and ships with a validation-tuned threshold that holds precision ≥ 0.95;
   below it the head emits nothing. "Can't tell" is the honest default.
3. **Honest eval** — shuffle before split, camera-disjoint where possible,
   refuse to grade on a single-class validation set. (Both halves of this rule
   were real bugs once.)
