#!/usr/bin/env python3
"""Multi-account Kaggle token rotator for the train-gate.

KAGGLE_API_TOKEN env var is either:
  * a single KGAT_... token (single-account mode), OR
  * a comma- or newline-separated bundle (multi-account rotation).

Picks the account with the oldest `last_used` in kaggle/rotation.json,
installs its token at ~/.kaggle/access_token, derives the account's public
username via `kaggle kernels init`, emits shell vars via $GITHUB_OUTPUT, and
persists the new rotation state so it can be committed back.

Notebook slug is per-account (bilbo-fp-a, -b, ...) — different slug per
account reduces the "byte-identical kernel" signal.

Exits 0 with `armed=false` if no tokens are present.
"""
import json
import os
import pathlib
import subprocess
import sys
import time


ROT_PATH = "kaggle/rotation.json"
KAGGLE_DIR = pathlib.Path.home() / ".kaggle"
SLUGS = "abcdefghij"  # one letter per rotating account, alphabetically


def emit(**kv):
    """Emit shell vars for a later `gate.yml` step to consume."""
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        for k, v in kv.items():
            print(f"{k}={v}")
        return
    with open(out, "a") as f:
        for k, v in kv.items():
            f.write(f"{k}={v}\n")


def parse_tokens(raw):
    """Bundle format: commas or newlines separate tokens; whitespace ignored."""
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
    return [p for p in parts if p.startswith("KGAT_")]


def load_state():
    try:
        return json.load(open(ROT_PATH))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"accounts": []}


def save_state(state):
    os.makedirs(os.path.dirname(ROT_PATH), exist_ok=True)
    with open(ROT_PATH, "w") as f:
        json.dump(state, f, indent=1)


def install_token(token):
    """Write the KGAT token where the kaggle CLI expects it, AND clear the
    KAGGLE_API_TOKEN env so the CLI reads the file (not the multi-token bundle
    we were invoked with — that string isn't valid auth on its own)."""
    KAGGLE_DIR.mkdir(exist_ok=True)
    p = KAGGLE_DIR / "access_token"
    p.write_text(token)
    p.chmod(0o600)
    os.environ.pop("KAGGLE_API_TOKEN", None)
    os.environ.pop("KAGGLE_KEY", None)
    os.environ.pop("KAGGLE_USERNAME", None)


def derive_username():
    """Ask the kaggle CLI who this token belongs to.

    `kaggle kernels init -p <dir>` writes a kernel-metadata.json with an `id`
    field of "<username>/INSERT_KERNEL_SLUG_HERE". We parse that.
    """
    tmp = pathlib.Path("/tmp/kaggle-probe")
    tmp.mkdir(exist_ok=True)
    for f in tmp.glob("*"):
        f.unlink()
    r = subprocess.run(["kaggle", "kernels", "init", "-p", str(tmp)],
                       capture_output=True, text=True, timeout=60)
    meta = tmp / "kernel-metadata.json"
    if not meta.exists():
        raise RuntimeError(
            f"kaggle kernels init failed: {r.stderr.strip() or r.stdout.strip()}")
    m = json.load(open(meta))
    user = m.get("id", "").split("/")[0]
    if not user:
        raise RuntimeError(f"could not parse username from {m}")
    return user


def pick(tokens, state):
    """Pick the account with the oldest last_used (or index 0 on first run)."""
    accts = {a["idx"]: a for a in state.get("accounts", [])}
    def key(i):
        return accts.get(i, {}).get("last_used", 0)
    return min(range(len(tokens)), key=key)


def main():
    raw = os.environ.get("KAGGLE_API_TOKEN", "")
    tokens = parse_tokens(raw)
    if not tokens:
        emit(armed="false")
        print("[rotate] no KAGGLE_API_TOKEN — gate disarmed", file=sys.stderr)
        return
    state = load_state()
    idx = pick(tokens, state)
    token = tokens[idx]
    install_token(token)
    try:
        user = derive_username()
    except Exception as e:
        print(f"[rotate] token #{idx} rejected: {e}", file=sys.stderr)
        # burn this token's rotation slot for a bit so we don't reselect it
        # immediately; another account can still fire.
        accts = {a["idx"]: a for a in state.get("accounts", [])}
        accts[idx] = {"idx": idx, "last_used": int(time.time()),
                      "username": None, "error": str(e)[:200]}
        state["accounts"] = sorted(accts.values(), key=lambda a: a["idx"])
        save_state(state)
        emit(armed="false")
        return
    slug = SLUGS[idx] if idx < len(SLUGS) else f"n{idx}"
    kernel_slug = f"bilbo-fp-{slug}"
    accts = {a["idx"]: a for a in state.get("accounts", [])}
    accts[idx] = {"idx": idx, "username": user, "kernel_slug": kernel_slug,
                  "last_used": int(time.time())}
    state["accounts"] = sorted(accts.values(), key=lambda a: a["idx"])
    state["accounts_configured"] = len(tokens)
    save_state(state)
    emit(armed="true", kuser=user, kslug=kernel_slug, kidx=str(idx))
    print(f"[rotate] token #{idx} -> {user}/{kernel_slug}", file=sys.stderr)


if __name__ == "__main__":
    main()
