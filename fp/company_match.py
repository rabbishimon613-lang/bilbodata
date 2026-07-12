"""Company catalogue matcher — a livery read becomes a lookup.

The catalogue (company_catalogue.csv, repo root) is the living log of fleets
seen on the cameras. The gold judge reads raw text/colors off a truck; this
module resolves that read against the catalogue so the label that lands in
the training data is a canonical company, not a free-text guess.

CLI:  python3 fp/company_match.py "PENSKE"          -> match
      python3 fp/company_match.py --add "U-Haul,truck_rental,white_orange,..."
"""
import csv
import os
import re
import sys
import time

from tiers import ROOT

CATALOGUE = os.path.join(ROOT, "company_catalogue.csv")
FIELDS = ["company", "category", "base_color", "livery_notes",
          "vehicle_type", "confidence", "date_added"]


def _norm(s):
    return re.sub(r"[^a-z0-9 ]+", "", (s or "").lower()).strip()


def load(path=None):
    with open(path or CATALOGUE) as f:
        return list(csv.DictReader(f))


def match(text, base_color=None, path=None):
    """Resolve a raw livery read to a catalogue row, or None.

    Match order: exact normalized name -> name token containment ->
    (optionally) base_color agreement as a tie-breaker, never as sole evidence
    (color alone is not a company — abstain doctrine applies here too).
    """
    q = _norm(text)
    if not q:
        return None
    rows = load(path)
    for r in rows:  # exact
        if _norm(r["company"]) == q:
            return r
    hits = []
    for r in rows:  # token containment either way
        name = _norm(r["company"])
        if q in name or name in q:
            hits.append(r)
        else:
            qt, nt = set(q.split()), set(name.split())
            if qt and nt and (qt <= nt or nt <= qt):
                hits.append(r)
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1 and base_color:
        col = [h for h in hits if _norm(h["base_color"]) == _norm(base_color)]
        if len(col) == 1:
            return col[0]
    return None


def add(company, category="", base_color="", livery_notes="", vehicle_type="",
        confidence="low", path=None):
    """Append a NEW fleet to the living catalogue (deduped by name)."""
    path = path or CATALOGUE
    if match(company, path=path):
        return False
    with open(path, "a") as f:
        csv.DictWriter(f, FIELDS).writerow({
            "company": company, "category": category, "base_color": base_color,
            "livery_notes": livery_notes, "vehicle_type": vehicle_type,
            "confidence": confidence, "date_added": time.strftime("%Y-%m-%d")})
    return True


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--add":
        parts = (sys.argv[2].split(",") + [""] * 6)[:6]
        print("added" if add(*parts) else "already on file")
    elif len(sys.argv) >= 2:
        m = match(" ".join(sys.argv[1:]))
        print(m if m else "no match — candidate for a new catalogue row")
    else:
        rows = load()
        print(f"{len(rows)} fleets on file")
