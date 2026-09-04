#!/usr/bin/env python3
"""Publish Daily Manna narration to the daily-manna-audio repo.

Audio is not kept in this repo: MP3s are the only thing that grows by megabytes
a day, and in-tree every one ever rendered stayed in git history forever, while
GitHub Pages refuses to serve a site over 1 GB. They live in their own repo,
served over its own Pages site, so this repo stays small and the audio repo's
history is disposable — nothing in it cannot be re-rendered.

GitHub Releases was tried first and cannot work. Release downloads are served
`Content-Type: application/octet-stream` with `Content-Disposition: attachment`,
hardcoded into the signed URL and not overridable even when the asset is stored
as audio/mpeg. Safari refuses to play audio on those, so it failed on the phone
while Chrome — which sniffs the bytes — played it and hid the fault. Pages sends
audio/mp3 and honours byte ranges, which the player needs to start and to seek.

    python3 scripts/audio_publish.py --publish            # move local audio over, push
    python3 scripts/audio_publish.py --publish 2026-09-04 # just that day
    python3 scripts/audio_publish.py --index              # rebuild index.json
    python3 scripts/audio_publish.py --prune 30           # drop days older than 30
    python3 scripts/audio_publish.py --verify             # check every indexed file streams
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio"                       # staging: where the renderer writes
INDEX = AUDIO / "index.json"
# Sibling checkout by default; override with DAILY_MANNA_AUDIO_REPO.
REPO_DIR = Path(os.environ.get("DAILY_MANNA_AUDIO_REPO",
                               str(ROOT.parent / "daily-manna-audio")))
BASE = "https://polarstellar.github.io/daily-manna-audio"


def git(*args, check=True, cwd=None, timeout=900):
    p = subprocess.run(["git", "-C", str(cwd or REPO_DIR), *args],
                       capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {p.stderr.strip()[:300]}")
    return p


def repo_ready():
    if not (REPO_DIR / ".git").is_dir():
        raise RuntimeError(
            f"the audio repo is not checked out at {REPO_DIR}. Clone it:\n"
            f"  git clone https://github.com/PolarStellar/daily-manna-audio.git "
            f"'{REPO_DIR}'")
    return True


def published_days():
    """{date: [ranks]} of what the audio repo actually holds."""
    out = {}
    if not REPO_DIR.is_dir():
        return out
    for d in sorted(REPO_DIR.glob("20*")):
        if not d.is_dir():
            continue
        ranks = sorted(int(p.stem) for p in d.glob("*.mp3") if p.stem.isdigit())
        if ranks:
            out[d.name] = ranks
    return out


def write_index(idx=None):
    idx = published_days() if idx is None else idx
    AUDIO.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(idx, indent=1, sort_keys=True) + "\n")
    total = sum(len(v) for v in idx.values())
    print(f"audio/index.json -> {total} file(s) across {len(idx)} day(s)")
    return idx


def publish(days=None, push=True):
    """Move freshly rendered days into the audio repo and push."""
    repo_ready()
    git("pull", "--ff-only", check=False)          # stay current; a failure is not fatal
    staged = days or sorted(d.name for d in AUDIO.glob("20*") if d.is_dir())
    moved = 0
    for iso in staged:
        src = AUDIO / iso
        if not src.is_dir():
            continue
        dest = REPO_DIR / iso
        dest.mkdir(parents=True, exist_ok=True)
        for mp3 in sorted(src.glob("*.mp3")):
            if not mp3.stem.isdigit():
                continue
            shutil.move(str(mp3), str(dest / mp3.name))
            moved += 1
        if not any(src.iterdir()):
            src.rmdir()
    if not moved:
        print("nothing new to publish")
        return 0

    git("add", "-A", ".")
    msg = f"Narration for {staged[0]}" + (f" – {staged[-1]}" if len(staged) > 1 else "")
    c = git("-c", "user.name=Kris Salta", "-c", "user.email=johns@mercola.com",
            "commit", "-m", msg, check=False)
    if c.returncode != 0 and "nothing to commit" not in (c.stdout + c.stderr):
        raise RuntimeError(f"commit failed: {(c.stdout + c.stderr)[:300]}")
    if push:
        git("push")
    print(f"published {moved} file(s) to {REPO_DIR.name}")
    write_index()
    return moved


def prune(keep_days, push=True):
    """Delete days older than keep_days from the audio repo."""
    repo_ready()
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    dropped = []
    for d in sorted(REPO_DIR.glob("20*")):
        if not d.is_dir() or d.name >= cutoff:
            continue
        shutil.rmtree(d)
        dropped.append(d.name)
    if not dropped:
        return []
    git("add", "-A", ".")
    git("-c", "user.name=Kris Salta", "-c", "user.email=johns@mercola.com",
        "commit", "-m", f"Age out narration before {cutoff}", check=False)
    if push:
        git("push", check=False)
    print(f"pruned {len(dropped)} day(s) before {cutoff}: " + ", ".join(dropped))
    write_index()
    return dropped


def verify(limit=None):
    """Confirm indexed files stream with an audio type and byte ranges.

    The Content-Type check is the point: Releases returned the right bytes with
    the wrong type, and that is precisely what Safari refuses to play.
    """
    idx = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    checks, bad = 0, []
    for iso in sorted(idx):
        for rank in idx[iso]:
            if limit and checks >= limit:
                break
            u = f"{BASE}/{iso}/{rank}.mp3"
            req = urllib.request.Request(u, headers={"Range": "bytes=0-2047"})
            try:
                with urllib.request.urlopen(req, timeout=45) as r:
                    code = r.status
                    ctype = (r.headers.get("Content-Type") or "").lower()
                    disp = (r.headers.get("Content-Disposition") or "").lower()
                    body = r.read()
                problems = []
                if code != 206:
                    problems.append(f"status {code}")
                if not ctype.startswith("audio/"):
                    problems.append(f"type {ctype!r} (Safari will not play this)")
                if "attachment" in disp:
                    problems.append("served as an attachment")
                if body[:3] not in (b"ID3", b"\xff\xfb", b"\xff\xf3"):
                    problems.append("not an mp3 frame")
                if problems:
                    bad.append((iso, rank, "; ".join(problems)))
            except Exception as e:
                bad.append((iso, rank, str(e)[:80]))
            checks += 1
    print(f"checked {checks} file(s); problems: {bad or 'none'}")
    return not bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", nargs="?", const="ALL", metavar="DATE")
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--prune", type=int, metavar="DAYS")
    ap.add_argument("--verify", nargs="?", const=0, type=int, metavar="N")
    a = ap.parse_args()
    if a.publish:
        publish(None if a.publish == "ALL" else [a.publish])
    elif a.index:
        write_index()
    elif a.prune is not None:
        prune(a.prune)
    elif a.verify is not None:
        return 0 if verify(a.verify or None) else 1
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
