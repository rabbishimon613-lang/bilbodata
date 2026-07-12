#!/usr/bin/env python3
"""Head trainers — one small model per skill, Kaggle-portable.

  python3 fp/train_heads.py --head vclass --out fp_out --epochs 12

Heads: company | color | vclass | plate_state | make_model
(the deep-embedding layer is a later, separate track — nothing here fakes it)

Doctrine baked in:
  * tier gate      — a head only ever sees crops from tiers that can carry its
                     claim (fp.tiers.HEAD_TIERS); color is day-gated on top.
  * abstain gate   — crop height + day/night ride along as input features, and
                     after training a per-class confidence threshold is chosen
                     on validation to hold precision >= --precision (default
                     0.95). Below threshold the head emits NOTHING.
  * honest eval    — rows are SHUFFLED before splitting (seeded), the split is
                     camera-disjoint where possible, and training refuses to
                     run if validation holds fewer than 2 classes (the exact
                     pair of bugs that sank the first make/model trainer).
  * device auto    — cuda > mps > cpu.
"""
import argparse
import hashlib
import json
import os
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tiers import HEAD_TIERS  # noqa: E402

LABEL_KEY = {"company": "company", "color": "color", "vclass": "vclass",
             "plate_state": "plate_state", "make_model": "make"}
MIN_PER_CLASS = 8


def device_auto():
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_rows(out, head):
    key = LABEL_KEY[head]
    tiers = HEAD_TIERS[head]
    rows = []
    for name in ("labels_gold.jsonl", "labels_auto.jsonl"):
        p = os.path.join(out, name)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("abstain") or r.get("not_vehicle") or key not in r:
                    continue
                if r.get("tier") not in tiers:
                    continue
                if head == "color" and not r.get("lit", True):
                    continue  # night chroma is physics loss — never train on it
                if head == "make_model" and r.get("model"):
                    r = dict(r, make=f"{r['make']} {r['model']}")
                if not os.path.exists(os.path.join(out, r["file"])):
                    continue
                rows.append({"file": r["file"], "y": str(r[key]).lower().strip(),
                             "cam": r.get("cam", r["file"].split("/")[1] if "/" in r["file"] else "?"),
                             "h": r.get("h", 0), "lit": bool(r.get("lit", True))})
    # drop classes too thin to grade honestly
    counts = Counter(r["y"] for r in rows)
    return [r for r in rows if counts[r["y"]] >= MIN_PER_CLASS]


def split_rows(rows, seed=17, val_frac=0.2):
    """Shuffle FIRST, then prefer a camera-disjoint split; fall back to a
    stratified random split if the disjoint one leaves val single-class."""
    rnd = random.Random(seed)
    rows = rows[:]
    rnd.shuffle(rows)  # the fix: never split sorted data
    cams = sorted({r["cam"] for r in rows},
                  key=lambda c: hashlib.md5(c.encode()).hexdigest())
    n_val_cams = max(1, int(len(cams) * val_frac))
    val_cams = set(cams[:n_val_cams])
    val = [r for r in rows if r["cam"] in val_cams]
    tr = [r for r in rows if r["cam"] not in val_cams]
    if len({r["y"] for r in val}) >= 2 and len({r["y"] for r in tr}) >= 2:
        return tr, val, "camera-disjoint"
    by_cls = defaultdict(list)
    for r in rows:
        by_cls[r["y"]].append(r)
    tr, val = [], []
    for _, rs in sorted(by_cls.items()):
        k = max(1, int(len(rs) * val_frac))
        val += rs[:k]
        tr += rs[k:]
    return tr, val, "stratified-random"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--head", required=True, choices=sorted(LABEL_KEY))
    ap.add_argument("--out", default=os.environ.get("FP_OUT", "fp_out"))
    ap.add_argument("--models", default=None, help="where weights land (default <out>/models)")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--precision", type=float, default=0.95,
                    help="abstain threshold is tuned to hold this on val")
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    import numpy as np
    import torch
    import torch.nn as nn
    from PIL import Image
    from torchvision import models, transforms

    torch.manual_seed(args.seed)
    rows = load_rows(args.out, args.head)
    classes = sorted({r["y"] for r in rows})
    if len(classes) < 2:
        print(f"[fp.train:{args.head}] only {len(classes)} class(es) with "
              f">={MIN_PER_CLASS} labels — not enough to train honestly yet")
        return
    tr, val, how = split_rows(rows, seed=args.seed)
    assert len({r['y'] for r in val}) >= 2, "single-class eval — refusing to grade"
    print(f"[fp.train:{args.head}] {len(tr)} train / {len(val)} val "
          f"({how}) · {len(classes)} classes: {classes}")

    dev = device_auto()
    cls_i = {c: i for i, c in enumerate(classes)}
    tf_train = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ColorJitter(0.15, 0.15, 0.1 if args.head != "color" else 0.0),
        transforms.ToTensor()])
    tf_val = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor()])

    class DS(torch.utils.data.Dataset):
        def __init__(self, rs, tf):
            self.rs, self.tf = rs, tf

        def __len__(self):
            return len(self.rs)

        def __getitem__(self, i):
            r = self.rs[i]
            img = Image.open(os.path.join(args.out, r["file"])).convert("RGB")
            # abstain features: how big the crop was, and whether it was day
            feats = torch.tensor([min(r["h"], 600) / 600.0, 1.0 if r["lit"] else 0.0])
            return self.tf(img), feats, cls_i[r["y"]]

    net_bb = models.mobilenet_v3_small(weights="DEFAULT")
    feat_dim = net_bb.classifier[0].in_features
    net_bb.classifier = nn.Identity()

    class Head(nn.Module):
        def __init__(self):
            super().__init__()
            self.bb = net_bb
            self.fc = nn.Sequential(nn.Linear(feat_dim + 2, 256), nn.Hardswish(),
                                    nn.Dropout(0.2), nn.Linear(256, len(classes)))

        def forward(self, x, f):
            return self.fc(torch.cat([self.bb(x), f], dim=1))

    net = Head().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr)
    lossf = nn.CrossEntropyLoss()
    dl_tr = torch.utils.data.DataLoader(DS(tr, tf_train), batch_size=args.batch,
                                        shuffle=True, num_workers=2)
    dl_va = torch.utils.data.DataLoader(DS(val, tf_val), batch_size=args.batch,
                                        num_workers=2)

    def evaluate():
        net.eval()
        probs, ys = [], []
        with torch.no_grad():
            for x, f, y in dl_va:
                p = torch.softmax(net(x.to(dev), f.to(dev)), dim=1).cpu()
                probs.append(p)
                ys.append(y)
        return torch.cat(probs), torch.cat(ys)

    best_acc, best_state = 0.0, None
    for ep in range(1, args.epochs + 1):
        net.train()
        tot = 0.0
        for x, f, y in dl_tr:
            opt.zero_grad()
            loss = lossf(net(x.to(dev), f.to(dev)), y.to(dev))
            loss.backward()
            opt.step()
            tot += float(loss)
        probs, ys = evaluate()
        acc = float((probs.argmax(1) == ys).float().mean())
        print(f"  ep {ep:02d}  loss {tot/max(1,len(dl_tr)):.3f}  val acc {acc:.3f}")
        if acc > best_acc:
            best_acc = acc
            best_state = {k: v.cpu() for k, v in net.state_dict().items()}
    net.load_state_dict(best_state)

    # calibrate the abstain threshold: smallest global threshold that keeps
    # precision >= target on val; coverage is whatever honesty leaves us
    probs, ys = evaluate()
    conf, pred = probs.max(1)
    thr = None
    for t in [i / 100 for i in range(30, 100)]:
        m = conf >= t
        if m.sum() == 0:
            break
        prec = float((pred[m] == ys[m]).float().mean())
        if prec >= args.precision:
            thr = t
            break
    cover = float((conf >= thr).float().mean()) if thr is not None else 0.0

    mdir = args.models or os.path.join(args.out, "models")
    os.makedirs(mdir, exist_ok=True)
    torch.save({"state": net.state_dict(), "classes": classes},
               os.path.join(mdir, f"{args.head}.pt"))
    report = {"head": args.head, "classes": classes, "n_train": len(tr),
              "n_val": len(val), "split": how, "val_acc": round(best_acc, 4),
              "abstain_thr": thr, "precision_target": args.precision,
              "coverage_at_thr": round(cover, 4), "device": dev,
              "ts": int(__import__("time").time())}
    json.dump(report, open(os.path.join(mdir, f"{args.head}_report.json"), "w"), indent=1)
    print(f"[fp.train:{args.head}] best val acc {best_acc:.3f} · "
          f"abstain thr {thr} holds precision>={args.precision} "
          f"at {cover:.0%} coverage" if thr is not None else
          f"[fp.train:{args.head}] best val acc {best_acc:.3f} · no threshold "
          f"reaches precision {args.precision} — head stays silent in public")


if __name__ == "__main__":
    main()
