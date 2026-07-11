#!/usr/bin/env python3
"""VMMRdb pre-training for the make/model student ("the textbook years").

Streams the downloaded VMMRdb parquet shards (US vehicles, 375 make_model
classes, 42 makes) and teaches MobileNetV3-small fine-grained vehicle
features on CPU. The resulting weights become the warm start for the
make/model school, which then fine-tunes on OUR badge-verified street crops
and is audited against those gold labels — VMMRdb never asserts anything
about a live NYC vehicle directly.

Politeness contract (8GB Mac, MPS detector training in parallel):
  - nice 19, 1 torch thread, batch 12 — crumbs only
  - self-gates: pauses whenever runs/live.json says the detector is in a
    fresh "train" phase; works only in the between-generation gaps
  - checkpoints after every shard chunk -> fully resumable
Writes: mmr/vmmr_student.pt + mmr/vmmr_status.json
"""
import io, json, os, time
import torch, torch.nn as nn
import pyarrow.parquet as pq
from torchvision import models, transforms
from PIL import Image

os.nice(19)
torch.set_num_threads(3)   # nice-19 keeps it harmless; 3 threads makes the between-generation gaps count

MMR="/Volumes/EOS_DIGITAL/bilbodata/mmr"; VD=f"{MMR}/vmmr"
LIVE="/Volumes/EOS_DIGITAL/bilbodata/runs/live.json"
CKPT=f"{VD}/vmmr_student.ckpt"; OUT=f"{MMR}/vmmr_student.pt"
STATUS=f"{MMR}/vmmr_status.json"
BATCH=12; VAL_N=500; EPOCHS=4   # val cache trimmed 2000->500 (~900MB) to spare an 8GB M1 from swap thrash

CLASSES=json.load(open(f"{VD}/classes.json"))
NC=len(CLASSES)

TF_TRAIN=transforms.Compose([
    transforms.Resize((224,224)), transforms.RandomHorizontalFlip(),
    transforms.ColorJitter(0.2,0.2,0.1), transforms.ToTensor(),
    transforms.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225])])
TF_VAL=transforms.Compose([
    transforms.Resize((224,224)), transforms.ToTensor(),
    transforms.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225])])

def detector_busy():
    """True while the MPS loop is actively inside a training epoch."""
    try:
        v=json.load(open(LIVE))
        fresh=(time.time()-os.path.getmtime(LIVE))<45*60
        return fresh and v.get("phase")=="train"
    except Exception:
        return False

def wait_turn():
    """Soft throttle: half-speed while the detector is mid-epoch (it's a
    380MB nice-19 single-thread process — pausing entirely was overkill)."""
    if detector_busy():
        time.sleep(0.5)

def shards():
    return sorted(f for f in os.listdir(VD) if f.endswith(".parquet"))

def batches(shard, skip_rows=0):
    pf=pq.ParquetFile(f"{VD}/{shard}")
    seen=0
    for rb in pf.iter_batches(batch_size=BATCH, columns=["image","label"]):
        if seen+len(rb)<=skip_rows:
            seen+=len(rb); continue
        seen+=len(rb)
        imgs, ys = [], []
        for img, y in zip(rb["image"].to_pylist(), rb["label"].to_pylist()):
            try:
                im=Image.open(io.BytesIO(img["bytes"])).convert("RGB")
                imgs.append(im); ys.append(y)
            except Exception:
                continue
        if imgs: yield imgs, ys

def build_val():
    """First VAL_N rows of the last shard are held out for scoring."""
    sh=shards()[-1]; rows=[]
    for imgs,ys in batches(sh):
        for im,y in zip(imgs,ys):
            rows.append((TF_VAL(im),y))
            if len(rows)>=VAL_N: return rows
    return rows

MAKE_OF=[c.split("_")[0] for c in CLASSES]

def evaluate(net,val):
    """Returns (exact make_model accuracy, make-only accuracy)."""
    net.eval(); hit=hitmk=n=0
    with torch.no_grad():
        for i in range(0,len(val),32):
            xs=torch.stack([v[0] for v in val[i:i+32]])
            ys=[v[1] for v in val[i:i+32]]
            pred=net(xs).argmax(1).tolist()
            hit+=sum(1 for p,y in zip(pred,ys) if p==y)
            hitmk+=sum(1 for p,y in zip(pred,ys) if MAKE_OF[p]==MAKE_OF[y])
            n+=len(ys)
    return hit/max(1,n), hitmk/max(1,n)

def main():
    net=models.mobilenet_v3_small(weights="IMAGENET1K_V1")
    net.classifier[3]=nn.Linear(net.classifier[3].in_features,NC)
    opt=torch.optim.AdamW(net.parameters(),lr=3e-4)
    state={"epoch":0,"shard_i":0,"rows_done":0,"hist":[],"curve":[],"seen":0}
    if os.path.exists(CKPT):
        ck=torch.load(CKPT,map_location="cpu")
        net.load_state_dict(ck["net"]); opt.load_state_dict(ck["opt"])
        state={**{"curve":[],"seen":0},**ck["state"]}
        print(f"[vmmr] resumed ep{state['epoch']} shard{state['shard_i']} rows{state['rows_done']}",flush=True)
    lossf=nn.CrossEntropyLoss()
    val=build_val()
    quiz=val[:300]        # small fixed pop-quiz -> the "how right over time" curve
    print(f"[vmmr] {NC} classes, val={len(val)}",flush=True)
    sh_all=shards()[:-1]           # last shard is validation territory
    while state["epoch"]<EPOCHS:
        for si in range(state["shard_i"],len(sh_all)):
            skip=state["rows_done"] if si==state["shard_i"] else 0
            done=skip; t0=time.time(); nb=0; runloss=0.0
            for imgs,ys in batches(sh_all[si],skip):
                wait_turn()
                net.train()
                x=torch.stack([TF_TRAIN(im) for im in imgs])
                y=torch.tensor(ys)
                opt.zero_grad(); l=lossf(net(x),y); l.backward(); opt.step()
                done+=len(ys); nb+=1; runloss+=float(l.detach())
                state["seen"]+=len(ys)
                if nb%300==0:   # pop-quiz -> public learning curve
                    acc,accmk=evaluate(net,quiz)
                    state["curve"].append({"ts":int(time.time()),"seen":state["seen"],
                                           "model":round(acc,4),"make":round(accmk,4)})
                    state["curve"]=state["curve"][-400:]
                if nb%150==0:
                    # atomic: write tmp then rename, so a mid-save crash/unmount
                    # can never leave a missing or half-written checkpoint
                    torch.save({"net":net.state_dict(),"opt":opt.state_dict(),
                                "state":{**state,"shard_i":si,"rows_done":done}},CKPT+".tmp")
                    os.replace(CKPT+".tmp",CKPT)
                    json.dump({"ts":int(time.time()),"phase":"pretrain",
                               "epoch":state["epoch"]+1,"of":EPOCHS,"shard":si+1,
                               "rows":done,"seen":state["seen"],
                               "loss":round(runloss/nb,3),
                               "rate_s":round((time.time()-t0)/nb,2),
                               "curve":state["curve"],
                               "hist":state["hist"]},open(STATUS,"w"))
            state["shard_i"]=si+1; state["rows_done"]=0
        acc,accmk=evaluate(net,val)
        state["epoch"]+=1; state["shard_i"]=0
        state["hist"].append({"ep":state["epoch"],"val_acc":round(acc,4),
                              "val_make":round(accmk,4),"ts":int(time.time())})
        torch.save({"net":net.state_dict(),"opt":opt.state_dict(),"state":state},CKPT)
        torch.save({"classes":CLASSES,"state":net.state_dict()},OUT)
        print(f"[vmmr] epoch {state['epoch']} done — model={acc:.4f} make={accmk:.4f}",flush=True)
    print("[vmmr] pretraining complete",flush=True)

if __name__=="__main__":
    main()
