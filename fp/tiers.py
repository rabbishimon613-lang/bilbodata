"""Camera tiers — the honest ladder, shared by every fp/ tool.

Tier is a property of the CAMERA (from the public resolution census); what a
head may claim is a property of tier x crop size x day/night. Both gates live
here so the whole pipeline agrees on them.

  blue    >=1920px   full fingerprint (make/model/company/plate-state/bus)
  orange  640-1919   color / type / size / company-by-color-block
  purple  <640       count / type / size / daytime color

Paths are configurable: BILBO_ROOT env var, else the repo this file sits in.
"""
import csv
import os

ROOT = os.environ.get("BILBO_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENSUS = os.path.join(ROOT, "cam_resolution_census.csv")

BLUE_MIN_W = 1920
ORANGE_MIN_W = 640

# how often each tier is swept: 1 = every sweep, N = every Nth sweep
SWEEP_EVERY = {"blue": 1, "orange": 2, "purple": 6}

# minimum crop height (px) for a saved close-up, per tier
CROP_MIN_H = {"blue": 96, "orange": 56, "purple": 48}

# what each head may ever be asked about, per tier (the hard gate — a head
# never even sees, let alone labels, a crop its tier can't support)
HEAD_TIERS = {
    "company":     {"blue", "orange"},
    "color":       {"blue", "orange", "purple"},   # day-gated at label time
    "vclass":      {"blue", "orange", "purple"},
    "plate_state": {"blue"},
    "make_model":  {"blue"},
    "bus":         {"blue", "orange"},
    "embed":       {"blue"},
}


def tier_of(width):
    w = int(width or 0)
    if w >= BLUE_MIN_W:
        return "blue"
    if w >= ORANGE_MIN_W:
        return "orange"
    return "purple"


def load_census(path=None):
    """[{id, name, area, w, h, tier}] for every camera in the census."""
    cams = []
    with open(path or CENSUS) as f:
        for r in csv.DictReader(f):
            try:
                w = int(r["width"])
            except (ValueError, KeyError):
                continue
            if w <= 0:
                continue
            cams.append({"id": r["id"], "name": r["name"], "area": r.get("area", ""),
                         "w": w, "h": int(r.get("height") or 0), "tier": tier_of(w)})
    return cams


def due_this_sweep(cams, sweep_n, night_boost=False):
    """Tier-weighted schedule: blues every sweep, oranges often, purples light.

    night_boost widens the net at dusk/night/rain — those conditions are rare
    in the library, so when they're happening we sample MORE, not less.
    """
    out = []
    for i, c in enumerate(cams):
        every = SWEEP_EVERY[c["tier"]]
        if night_boost and every > 1:
            every = max(1, every // 2)
        # stagger purples by index so each sweep sees a rotating slice
        if (sweep_n + i) % every == 0:
            out.append(c)
    return out


def head_allowed(head, tier):
    return tier in HEAD_TIERS.get(head, set())
