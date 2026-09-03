#!/usr/bin/env python3
"""Host Daily Manna narration in GitHub Releases instead of the git tree.

Why this exists: MP3s are the only thing here that grows by megabytes a day, and
committing them meant every one ever rendered stayed in history forever — the
clone grew ~360 MB a month whatever the 30-day prune deleted, and GitHub Pages
refuses to serve a site over 1 GB. Release assets are stored outside the repo,
cost nothing, are served with byte-range support (which Safari needs), and can
be deleted for real.

Layout: one release per month, tag `audio-YYYY-MM`, assets named
`YYYY-MM-DD-<rank>.mp3`. Both are derivable from a date, so the reader builds a
URL without needing a lookup table.

    python3 scripts/audio_release.py --upload                 # every local day
    python3 scripts/audio_release.py --upload 2026-09-03       # one day
    python3 scripts/audio_release.py --index                   # rebuild index.json from GitHub
    python3 scripts/audio_release.py --prune 30                # drop assets older than 30 days
    python3 scripts/audio_release.py --verify                  # check every indexed file plays

`audio/index.json` stays in git — it is about a kilobyte and it is what tells
the reader which articles have narration. It is rebuilt FROM GitHub, so the
release is the single source of truth and a half-finished upload self-corrects.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio"
INDEX = AUDIO / "index.json"
REPO = "PolarStellar/daily-manna"
BASE = f"https://github.com/{REPO}/releases/download"
ASSET_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d+)\.mp3$")


def gh(*args, check=True, timeout=600):
    p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}… failed: {p.stderr.strip()[:400]}")
    return p


def tag_for(iso):
    return "audio-" + iso[:7]


def asset_for(iso, rank):
    return f"{iso}-{rank}.mp3"


def url_for(iso, rank):
    return f"{BASE}/{tag_for(iso)}/{asset_for(iso, rank)}"


def ensure_release(tag):
    """Create the month's release if it isn't there yet."""
    if gh("release", "view", tag, "--repo", REPO, check=False).returncode == 0:
        return
    gh("release", "create", tag,
       "--repo", REPO,
       "--title", f"Narration {tag.replace('audio-', '')}",
       "--notes", "Narrated Daily Manna articles for this month. "
                  "Hosted here rather than in the git tree so the repo stays small; "
                  "the reader streams them directly.")
    print(f"  created release {tag}")


def local_days():
    return sorted(d.name for d in AUDIO.glob("20*") if d.is_dir()
                  and any(d.glob("*.mp3")))


def remote_assets():
    """{date: [ranks]} of what is actually uploaded, read back from GitHub."""
    out = {}
    rel = gh("release", "list", "--repo", REPO, "--limit", "200",
             "--json", "tagName").stdout
    tags = [r["tagName"] for r in json.loads(rel or "[]")
            if r["tagName"].startswith("audio-")]
    for tag in tags:
        data = gh("release", "view", tag, "--repo", REPO, "--json", "assets").stdout
        for a in json.loads(data or "{}").get("assets", []):
            m = ASSET_RE.match(a["name"])
            if m:
                out.setdefault(m.group(1), []).append(int(m.group(2)))
    return {d: sorted(set(r)) for d, r in sorted(out.items())}


def write_index(idx):
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(idx, indent=1, sort_keys=True) + "\n")
    total = sum(len(v) for v in idx.values())
    print(f"audio/index.json -> {total} file(s) across {len(idx)} day(s)")


def upload(days, delete_local=False):
    """Upload each day's MP3s, then optionally drop the local copies."""
    uploaded = 0
    for iso in days:
        day_dir = AUDIO / iso
        mp3s = sorted(day_dir.glob("*.mp3"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
        if not mp3s:
            continue
        tag = tag_for(iso)
        ensure_release(tag)
        for mp3 in mp3s:
            if not mp3.stem.isdigit():
                continue
            name = asset_for(iso, mp3.stem)
            # Stage a correctly-named copy: the asset name — which is what the
            # download URL uses — is always the basename of the uploaded file.
            # gh's `file#text` syntax sets only a cosmetic display *label*, not
            # the name, so it cannot be used to avoid this copy. Verified.
            staged = day_dir / name
            created = False
            if staged != mp3:
                staged.write_bytes(mp3.read_bytes())
                created = True
            try:
                gh("release", "upload", tag, str(staged),
                   "--repo", REPO, "--clobber")
                uploaded += 1
                print(f"  uploaded {name}")
            finally:
                if created:
                    staged.unlink(missing_ok=True)
    print(f"\nUploaded {uploaded} file(s).")

    idx = remote_assets()
    write_index(idx)

    if delete_local and uploaded:
        freed = 0
        for iso in days:
            # Only remove what GitHub confirms it has.
            have = set(idx.get(iso, []))
            day_dir = AUDIO / iso
            for mp3 in list(day_dir.glob("*.mp3")):
                if mp3.stem.isdigit() and int(mp3.stem) in have:
                    freed += mp3.stat().st_size
                    mp3.unlink()
            if day_dir.is_dir() and not any(day_dir.iterdir()):
                day_dir.rmdir()
        print(f"Removed {freed // (1024 * 1024)} MB of local copies "
              f"(kept anything GitHub had not confirmed).")
    return uploaded


def prune(keep_days):
    """Delete release assets older than keep_days, for real."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    idx = remote_assets()
    dropped = []
    for iso in sorted(idx):
        if iso >= cutoff:
            continue
        tag = tag_for(iso)
        for rank in idx[iso]:
            name = asset_for(iso, rank)
            r = gh("release", "delete-asset", tag, name, "--repo", REPO, "--yes",
                   check=False)
            if r.returncode == 0:
                print(f"  deleted {name}")
            else:
                print(f"  could not delete {name}: {r.stderr.strip()[:120]}")
        dropped.append(iso)
    # An emptied month's release is just clutter.
    for tag in {tag_for(d) for d in dropped}:
        data = gh("release", "view", tag, "--repo", REPO, "--json", "assets",
                  check=False)
        if data.returncode == 0 and not json.loads(data.stdout or "{}").get("assets"):
            gh("release", "delete", tag, "--repo", REPO, "--yes", check=False)
            print(f"  removed empty release {tag}")
    write_index(remote_assets())
    print(f"\nPruned {len(dropped)} day(s) older than {cutoff}.")
    return dropped


def verify(limit=None):
    """Confirm indexed files really stream, with the range support Safari needs."""
    idx = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    checks, bad = 0, []
    for iso in sorted(idx):
        for rank in idx[iso]:
            if limit and checks >= limit:
                break
            u = url_for(iso, rank)
            req = urllib.request.Request(u, headers={"Range": "bytes=0-2047"})
            try:
                with urllib.request.urlopen(req, timeout=45) as r:
                    code, ctype = r.status, r.headers.get("Content-Type", "")
                    body = r.read()
                ok = code == 206 and len(body) == 2048 and body[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3")
                if not ok:
                    bad.append((iso, rank, f"status={code} bytes={len(body)} type={ctype}"))
            except Exception as e:
                bad.append((iso, rank, str(e)[:80]))
            checks += 1
    print(f"checked {checks} file(s); problems: {bad or 'none'}")
    return not bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", nargs="?", const="ALL", metavar="DATE")
    ap.add_argument("--delete-local", action="store_true",
                    help="after a confirmed upload, remove the local MP3s")
    ap.add_argument("--index", action="store_true", help="rebuild index.json from GitHub")
    ap.add_argument("--prune", type=int, metavar="DAYS")
    ap.add_argument("--verify", nargs="?", const=0, type=int, metavar="N")
    a = ap.parse_args()

    if a.upload:
        days = local_days() if a.upload == "ALL" else [a.upload]
        if not days:
            print("no local audio to upload")
            return 0
        print(f"uploading {len(days)} day(s): {days[0]} .. {days[-1]}")
        upload(days, delete_local=a.delete_local)
    elif a.index:
        write_index(remote_assets())
    elif a.prune is not None:
        prune(a.prune)
    elif a.verify is not None:
        return 0 if verify(a.verify or None) else 1
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
