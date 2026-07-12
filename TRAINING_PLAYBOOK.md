# Bilbo — Close the make/model/color gap on NYC DOT cams

> **2026-07-12 — this playbook is now IMPLEMENTED.** The tiered strategy below
> became the fp/ pipeline (tier-gated harvest → teacher + Claude gold labels →
> per-head trainers with the shuffle-before-split and multi-class-eval fixes →
> Kaggle GPU bursts, not Colab). Entry points: `fp/README.md`,
> `handoff/REBUILD_SPEC.md`, `.github/workflows/harvest.yml` + `gate.yml`.
> This file stays as the reasoning record.

_Rewritten 2026-07-09 after the resolution census. Detection is already solved
(existing model counts cars fine). The gap = make / model / color / unique
details. Executable mechanically after the Fable window closes (Jul 11).
Everything runs free: Mac (MPS) or Google Colab free tier._

## THE census finding that changes everything (2026-07-09)
The fleet is NOT uniform 352×240. Full sweep of all 917 cams
(`cam_resolution_census.csv`, same folder):

| Tier | Res | Count | Where |
|------|-----|-------|-------|
| A | 1920×1080 (+one 3840×2160) | **25** | Highway cams: BQE, LIE, Cross Bronx, Bruckner, SIE, Prospect Expwy. Bronx 10, SI 6, Queens 5, Bklyn 4. **Zero Manhattan.** |
| B | 640×352–800×450, mostly 720×480 | **~96** | Outer boroughs, mostly highways |
| C | 352×240 / 320×240 | ~790 | Everything else incl. all of Manhattan |
| — | offline | 7 | |

**Strategy: attributes are a Tier-A/B product.** On a 1080p cam a near-lane
vehicle is 200–500 px — make/model/color genuinely readable. On Tier C the
information isn't in the pixels (industry needs ~120 px/ft for make/model;
Tier C delivers ~20–25 on a close car). No training run fixes Tier C. Gate
every attribute claim by tier + crop size + daylight.

## What each gap component honestly is
- **Color** — trainable. Coarse buckets (white/black/silver/gray/red/blue/
  green/yellow) work in DAYLIGHT even on Tier B, on Tier A easily. Night =
  physics loss (sodium/LED lighting kills chroma) → emit "unknown".
- **Make/model** — trainable for Tier A near-lane crops (≥100 px). Two-stage:
  body type always; make/model head fires only when crop earns it.
- **Unique details** — reframed as (a) attribute flags: taxi-yellow, livery
  plates/markings, box truck, lightbar, roof rack, dump/cement/school-bus;
  (b) re-ID embeddings for corridor-level short-window matching (CCTView
  precedent, see below). Citywide any-car re-ID stays dead — July finding
  stands for Tier C.

## Phase 0 — FAST condition-diverse library from the archive (DONE, repeatable)
The paid archive (newyorkcity.trafficcamarchive.com) sells 1-hour videos but
exposes **12 free preview frames per hour-video at 640×480, no watermark**
(just the camera's own timestamp). That beats live Tier-C (352×240) and, unlike
live capture, lets us pick PAST dates with KNOWN weather — instant day/night ×
sun/rain/overcast variety with no waiting. Not full 1080p (archive normalizes
to 640×480), so this feeds detection + Tier-C color robustness, NOT Tier-A
make/model (that still needs live hi-res cams + VMMRdb).

How it works (all scripted, no crypto-cracking — uses the site's own code):
1. `tca_cameras.csv` — archive camera list (id, GPS, name), pulled from the
   browse map's in-memory `markers` array. 491 NYC-area cams; 21 diverse ones saved.
2. Pick weather dates from Open-Meteo history (free, no key): archive-api.open-meteo.com
   → daily precipitation/weathercode for NYC. Sunny 2026-06-20, overcast 2026-07-08,
   heavy-rain 2026-07-06 (51mm) are the batch-1 picks.
3. In a browser tab on any `browseVideo.html` page, the page function
   `getVideoInfo(cameraId, yearNum, monthIndex0based, day, cb)` returns the fully
   DECODED hour list (uid, hour, width, height, available). Loop it over all
   cam×date to build the manifest → `tca_manifest.csv` (cam,date,hour,uid).
   (Exfil trick: inject manifest into a <pre>, read with get_page_text — the
   https→http localhost POST is blocked by mixed-content, don't bother.)
4. `tca_harvest.py` reads the manifest. Per video: GET preparePreviewImages
   (server generates the 12 frames, ~2s — REQUIRED, else getPreviewImage returns
   a 307×307 "failed to generate" placeholder), then GET getPreviewImage
   index 0..11. md5-dedup, drop placeholders. Sorts into
   `training_library/<slug>_<cam>/<date>_<weather>/<HH>_<day|night>/`.
Batch 1 = 12 cams × 3 weather × 6 hours ≈ 2,000 distinct 640×480 frames.
To grow: add cameras to tca_cameras.csv, add dates, rebuild manifest, re-run.

## Existing data you can download TODAY
- **CCTView (samdbrice/cctview, GitHub)** — code + DenseNet201 VeRi re-ID
  model + ~10 GB of real DOT frames per FDR camera (May 2020). Free training
  data + working re-ID reference for the corridor use case.
- Public attribute datasets (already in REFERENCES_vision.md): VMMRdb (291k
  street-quality make/model photos — closest to DOT), Stanford Cars, VeRi.
- NYC Mesh's streetwatch archive went PRIVATE (2020 misuse concerns) — can ask
  via their Slack, don't count on it. trafficcamarchive.com = paid, skip.
- OpenVINO barrier-0042 (type+color, surveillance-trained) — use as teacher,
  not as final answer.

## Phase 1 — Harvest, weighted by tier (start ASAP; 1–2 weeks passive)
Worker is stopped (Jul 9 rebuild) — write a NEW harvester, frames only:
- **Tier A cams: every sweep, highest priority.** These are the training
  goldmine AND the demo cams. Tier B: frequent. Tier C: light sampling (only
  needed for the color-bucket model's low-res robustness).
- Day/dusk/night × weekday/weekend; oversample rain.
- Stale-frame filter: hash bytes, skip repeats per cam (known DOT bug).
- Store `harvest/<tier>/<cam_id>/<utc_ts>.jpg`. Tier A at 1080p is ~200–400 KB
  per frame — budget a few GB, still trivial.
- Target: 20–30k Tier A frames, 10k Tier B, 5k Tier C.

## Phase 2 — Auto-crop + auto-label (teacher models, one Colab day)
Detection is solved → use the existing detector to CROP vehicles from
harvested frames. That's the crop farm. Then label crops with teachers:
- **Type**: big YOLO / existing detector classes.
- **Color**: barrier-0042 + a big vision model consensus on DAY crops; keep
  only agreements as labels. Night crops → labeled "unknown" on purpose so the
  student learns to say unknown.
- **Make/model** (Tier A large crops only): pretrain student on VMMRdb, then
  pseudo-label DOT crops with the pretrained model at high confidence.
- Write a crops manifest CSV: crop path, cam_id, tier, px height, day/night,
  labels + confidences.

## Phase 3 — Hand-correct a slice (~1 afternoon)
500–1,000 crops in Label Studio / CVAT / Roboflow free tier. Prioritize:
teacher disagreements, Tier A night, boundary sizes (80–120 px). Add the
attribute flags (taxi, livery, lightbar, roof rack…) in this pass — they're
checkbox-fast per crop.

## Phase 4 — Split by CAMERA, never by frame
Hold out whole cameras per tier (e.g. 5 of the 25 Tier A cams). Near-duplicate
frames leak otherwise and the score lies.

## Phase 5 — Train the attribute model (overnight Mac / 1–2 h free Colab)
Not a detector — a multi-head classifier on crops:
- Backbone: small (ResNet18 / efficient-net class), input 128–224 px.
- Heads: body type (always on) · color 8 buckets + unknown (day-gated) ·
  attribute flags (multi-label) · make/model (VMMRdb-pretrained, fires only
  crop ≥100 px + day + Tier A/B).
- Add crop-size + day/night as input features so the model itself learns
  when to abstain. Calibrate: below threshold, output nothing. Silence > wrong.
- Optional corridor re-ID: fine-tune CCTView's VeRi embedding on Tier A crops;
  evaluate only same-highway, ≤10 min windows.

## Phase 6 — Evaluate honestly
Held-out cameras, sliced by: tier × day/night × crop-size bucket. Expected
honest scorecard: Tier A day make/model usable; Tier B color+type solid;
Tier C = type only (unchanged). If Tier A day make/model is weak → more
Tier A harvest, not more knobs.

## Phase 7 — Deploy as tiered pipeline
Existing detector everywhere → attribute model on crops → output gated by
tier/size/light. BrainView shows richer labels on highway cams, honest coarse
labels elsewhere. Keep stale-frame filter in prod.

## Cost: $0. ultralytics/torch, sahi, Label Studio/CVAT, Colab free tier.

## Order vs Fable window (closes Jul 11)
1. NOW: census done ✓ (cam_resolution_census.csv). Playbook done ✓.
2. NEXT (any session): tier-weighted harvester built + running.
3. Weeks 1–2: passive harvest; meanwhile download CCTView data + VMMRdb.
4. Then Phases 2–6 are mechanical, from this doc.
