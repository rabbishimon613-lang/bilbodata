# BILBO DATA — FULL REBUILD SPEC (2026-07-12)

**You are executing this autonomously. Give few, small outputs. Do the whole job end to
end, then commit and push. Don't stop to ask for approval between steps — this doc is the
approval.** Repo: `/Volumes/EOS_DIGITAL/bilbodata`, remote `origin`
(github.com/rabbishimon613-lang/bilbodata).

Also read, as source of truth, the memory files (they may be newer than this doc):
`~/.claude/projects/-Volumes-EOS-DIGITAL/memory/` →
`project_bilbo_fingerprint_doctrine.md`, `project_bilbo_company_catalogue.md`,
`project_bilbodata.md`, `project_bilbodata_recognition.md`, and the feedback files
(`feedback_small_answers`, `feedback_no_nerd_talk`, `feedback_autonomous_build_mode`,
`feedback_claude_only`).

---

## MISSION
Bring Bilbo up to date with everything learned this session and re-work all aspects toward
one goal: **a fingerprinting platform that scales toward every camera in NYC (917), honestly
tiered by what each camera can actually deliver.** Bilbo is no longer "just a counter" — it
is a **vehicle-fingerprinting** system with a human search layer.

## THE CORE MODEL (what we proved this session)
Two layers:
1. **Machine fingerprint** — a deep embedding per vehicle (system-level matching), not
   human-readable.
2. **Human search handles** — make, model, color, vehicle class, company/livery, individual
   features, plate-state, bus route/fleet#. So a person can query ("white Toyota, ladder
   rack" / "PENSKE truck" / "route S78").

**THE ONE HARD RULE — high abstain bar.** Only assert a handle when genuinely sure. "Can't
tell" is the honest default; a confident wrong label is unacceptable. Gate every claim by
camera tier × crop pixels × day/night. Calibrate each head so below-threshold emits nothing.
(Proven necessary: color read off brake-lights = the classic lazy error; night kills chroma;
badges aren't in the pixels on low tiers.)

## CAMERA TIERS (verified on real footage — build the whole product around this)
Census: 917 cams. `cam_resolution_census.csv` has width per cam.
- **🔵 BLUES — 25 cams, ≥1920px** (highways: BQE, Cross Bronx, LIE, SIE, Bruckner; one 4K).
  Full fingerprint: class · color · make · **model** · **company** · individual features
  (loads/damage/racks) · **plate STATE** (~40–50%, by color/design) · bus route+fleet#.
  Full plate/faces/tracking = NEVER (45-sec stills, not video). Proven: Volvo V60, Lexus ES,
  Toyota Camry/Highlander, Ford Super Duty, Lincoln Nautilus, Nissan Murano, Subaru, Chevy
  Silverado all ID'd; companies read (Walgreens/Duane Reade, ShopRite, Penske, Piece of Cake,
  Enterprise, Mo Ice, Medline, XTRA, DSNY, MTA).
- **🟠 ORANGES — ~96 cams, 640–1919px.** Color · type · size · direction · buses · **company
  by COLOR-BLOCK/silhouette** (pink mover ID'd at 42px). NO make/model, NO fine logo text, NO
  plate. Near-lane orange cams occasionally get make.
- **🟣 PURPLES — ~790 cams, <640px** (all Manhattan). Count · type · size · direction ·
  daytime color · standardized high-contrast fleets (taxi yellow, big color blocks) when
  present. No make/model/company-text/plate. The honest floor.

**Never emit a handle the tier can't support.** The site must show this gating visibly and
honestly (a blue cam shows rich labels; a purple cam shows "type + color, make: can't tell").

## LABELING
- Bulk auto-labels: cheap teacher models (YOLO for detection/type; keep only high-confidence).
- **Gold + hard cases: Claude, on Pedro's Max plan (NOT the paid API — no key, no separate
  bill).** Claude reads the crop and names make/model/color/company or abstains. Runs in
  batches (~200–500 crops/run), not the whole firehose. Self-labeling vehicles (a FedEx truck
  = its own label) are the cheapest gold.

## COMPANY CATALOGUE
Living file `company_catalogue.csv` (fleet → category → base_color → livery_notes →
vehicle_type → confidence). A livery read becomes a lookup. Current entries: Walgreens/Duane
Reade, ShopRite, Penske, Piece of Cake Moving, XTRA Lease, Medline, Mo Ice, DSNY, MTA Bus,
Enterprise, a private yellow carter, Kyungil (Korean HVAC), and one unknown red circle-D
service rig. Wire this into the product: a company handle resolves against this table.

## INFRASTRUCTURE (100% free, no credit card, off the Mac)
- **Perpetual harvest → scheduled GitHub Actions** (public repo = unlimited CPU minutes;
  ~5.5h bounded loop, relay self-dispatch). Harvest weighted by tier (blues every sweep;
  oranges frequent; purples light), oversample rain/dusk/night, md5 stale-frame guard.
  Store frames/crops in **GitHub Releases or an orphan data branch — NEVER on `main`** (git
  bloat is the one thing that breaks free). Only small telemetry JSON + `crops_meta` on `main`.
- **Burst GPU training → Kaggle** (headless, API-triggerable; ~30 GPU-h/week). Not Colab
  (no headless trigger). A cron `gate.yml` fires a Kaggle run when enough new crops bank.
- Models plateau — don't run perpetual GPU; harvest is the only perpetual thing.
- Claude-only: never call any external fleet/worker. Sub-agents OK.

## MODELS / HEADS (detector is solved+plateaued; build the rest as independent heads)
Order cheap→speculative: **markings/company → color (day-gated) → body/vehicle-class →
plate-state → make/model (blues only) → deep embedding**. Bus sub-head: route_line,
destination, fleet_number, ad_campaign, operator. Each head: crop-height + day/night as
inputs so it learns to abstain; calibrate to hold precision high, accept low recall.
Vehicle-class is the honest middle rung (fills where make/model can't). Fix the known
make/model bugs when porting the trainer: **shuffle before split**, **multi-class eval set**
(the old one-class eval + sorted VMMR data was the killer), device=GPU.

## THE REBUILD — WORK PACKAGES (do all)
1. **Site / product (`index.html` + assets).** Update copy + structure to the fingerprint
   direction and the tier system. Keep the **exact existing aesthetic** (see UI rules). Tabs
   today: Live · BrainView · Academy · About. Add/rework so the product tells the true story:
   count everywhere → fingerprint on the blues. Surface: per-camera tier badge; the handles
   with honest "can't tell"; a company/fleet view backed by `company_catalogue.csv`; a search
   framing (make/model/color/company). Update About to reflect fingerprinting (keep canon:
   Foucault régime-of-truth + LOTR naming; NEVER name the "silent consultant" gag).
2. **Academy dashboard.** Rework to show the real loop (harvest → label → train heads → grade
   → repeat), the tier map, the company log filling, the gold-judge (Claude) feed, the
   abstain gauge, per-head staircases. Cinematic and *alive* but in Bilbo's austere style —
   **not vibecoded** (see UI rules).
3. **Pipeline (Python).** Rework harvester to tier-weighted, all-city-aware (reads the full
   census, not just growth cams). Crop farm + teacher auto-label + Claude gold-judge hook +
   `crops_meta` manifest. Head trainers as independent, Kaggle-portable scripts with the bug
   fixes. Company-catalogue matcher. Keep absolute paths configurable.
4. **Cloud infra.** GitHub Actions harvest workflow + Kaggle burst notebook + gate trigger +
   telemetry push-back so the Academy tab updates. Weights/frames in Releases, not `main`.
5. **Docs/memory.** Update in-repo docs (TRAINING_PLAYBOOK / DATA / handoff) to match. Keep
   `company_catalogue.csv` as the living log.

## UI RULES (do not violate — "don't make it look vibecoded")
Match `index.html`'s existing system EXACTLY. Tokens already defined in its `:root`:
`--bg:#000; --panel:#0c0d0f; --line:#1b1c1f; --ink:#f3f4f5; --dim:#8b909a; --mut:#585d66;
--live:#4ad991; --accent:#5b8def; --warn:#e0a44a; --red:#e2645f;` fonts `--mono:"IBM Plex
Mono"`, `--sans:"Inter"` weight 300. Aesthetic = austere black Palantir: thin hairline rules,
1px-gap grids, tabular-nums mono numerals, uppercase mono eyebrows with letter-spacing, 2–5px
radii, restraint. **No neon glow, no CRT scanlines, no blinking "REC", no toy conic gauges,
no gradient heroes, no emoji section markers.** Drama comes from density, precise alignment,
and subtle motion — not effects. When in doubt, quieter.

## CONSTRAINTS
- Free only, **no credit card**, no paid API. Claude-only (no external fleet).
- Keep the site's look. Plain-English in any user-facing copy; no nerd jargon in the UI.
- Autonomous end-to-end (no per-step approval). Don't break the running training worker or
  the academy-pulse auto-commit if they're live — additive changes; branch if unsure.

## DONE = 
A coherent rebuilt codebase + site + Academy + pipeline + cloud workflows reflecting the tier
system and fingerprint direction, UI aesthetic intact, **committed and pushed to `origin`**
(branch + PR if not on main; the academy pulse commits to `main` frequently, so rebase/pull
before pushing). "Done" is the *system* rebuilt and pushed — not every model trained to
completion (footage/training accrue over time via the cloud infra). After push, redeploy the
static shell if changed: Vercel CLI is logged in on the Mac — `vercel --prod --yes` from the
repo (the deploy.yml VERCEL_TOKEN secret is dead; deploy locally). Give a short final summary
of what shipped.
