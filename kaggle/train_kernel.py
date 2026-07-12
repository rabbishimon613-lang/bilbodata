#!/usr/bin/env python3
"""Kaggle burst trainer — pulled and pushed headlessly by gate.yml.

Rebuilds the fp_out layout from the public repo (labels from main, crop
tarballs from the `crops` release), then trains every head that has enough
labels. Weights + reports land in /kaggle/working, which gate.yml collects on
its next pass. GPU is auto-detected by fp/train_heads.py.
"""
import json
import os
import subprocess
import sys
import urllib.request

REPO = "rabbishimon613-lang/bilbodata"
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
API = f"https://api.github.com/repos/{REPO}"
OUT = "/kaggle/working/fp_out"
HEADS = ["vclass", "color", "company", "plate_state", "make_model"]


def get(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": "bilbo-kaggle"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if dest:
        with open(dest, "wb") as f:
            f.write(data)
    return data


def main():
    os.makedirs(OUT, exist_ok=True)
    # code
    os.makedirs("fp", exist_ok=True)
    for f in ["tiers.py", "train_heads.py", "company_match.py"]:
        get(f"{RAW}/fp/{f}", f"fp/{f}")
    get(f"{RAW}/cam_resolution_census.csv", "cam_resolution_census.csv")
    try:
        get(f"{RAW}/company_catalogue.csv", "company_catalogue.csv")
    except Exception:
        pass
    os.environ["BILBO_ROOT"] = os.getcwd()
    # labels (cloud harvest + any hand-carried gold committed to main)
    for name in ["labels_auto.cloud.jsonl", "labels_gold.jsonl", "crops_meta.cloud.jsonl"]:
        try:
            get(f"{RAW}/fp/{name}", os.path.join(OUT, name.replace(".cloud", "")))
        except Exception:
            print(f"[kernel] no {name} on main yet")
    # crops from the rolling release
    rel = json.loads(get(f"{API}/releases/tags/crops"))
    assets = rel.get("assets", [])
    print(f"[kernel] {len(assets)} crop tarballs on the release")
    for a in assets:
        tgz = f"/tmp/{a['name']}"
        get(a["browser_download_url"], tgz)
        subprocess.run(["tar", "xzf", tgz, "-C", OUT], check=False)
        os.remove(tgz)
    # train every head that has fuel; report either way
    for head in HEADS:
        print(f"\n========== {head} ==========")
        r = subprocess.run([sys.executable, "fp/train_heads.py", "--head", head,
                            "--out", OUT, "--models", "/kaggle/working",
                            "--epochs", "12"])
        print(f"[kernel] {head} exit {r.returncode}")
    print("[kernel] done — outputs in /kaggle/working")


if __name__ == "__main__":
    main()
