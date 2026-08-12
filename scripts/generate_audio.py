#!/usr/bin/env python3
"""Render Daily Manna articles to MP3 with ElevenLabs.

Usage:
    python3 scripts/generate_audio.py                  # latest day, all 4 articles
    python3 scripts/generate_audio.py 2026-08-08       # one day
    python3 scripts/generate_audio.py 2026-08-08 2     # one article
    python3 scripts/generate_audio.py --all            # every day missing audio

Output: audio/<date>/<rank>.mp3, plus audio/index.json (what the app checks).
Voice: set VOICE=<name> from VOICES below, or ELEVEN_VOICE_ID=<id> directly.
Key: ELEVENLABS_API_KEY in the environment or in studio/.secrets.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audition_voices import EXTRA, VOICES, api_key, to_speech_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
AUDIO = ROOT / "audio"

MODEL = os.environ.get("ELEVEN_MODEL", "eleven_v3")
# eleven_v3 takes up to ~3000 chars per request; chunk on paragraph breaks.
CHUNK = int(os.environ.get("ELEVEN_CHUNK", "2400"))
# 64 kbps is plenty for one calm voice and keeps the repo from ballooning
# (~3 MB per 7-minute article vs ~7 MB at 128). Needs Creator tier or above;
# on the free/Starter plan use mp3_22050_32.
FORMAT = os.environ.get("ELEVEN_FORMAT", "mp3_44100_64")

NAMED = {name: vid for name, vid, _ in VOICES} | {n: v for n, (v, _) in EXTRA.items()}
DEFAULT_VOICE = os.environ.get("VOICE", "matilda")   # Kris picked this by ear


def voice_id():
    vid = os.environ.get("ELEVEN_VOICE_ID")
    if vid:
        return vid, "custom"
    if DEFAULT_VOICE not in NAMED:
        sys.exit(f"Unknown VOICE={DEFAULT_VOICE}. Known: {', '.join(sorted(NAMED))}")
    return NAMED[DEFAULT_VOICE], DEFAULT_VOICE


def chunks(text):
    """Split on paragraph breaks, packing up to CHUNK chars per request."""
    out, buf = [], ""
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if buf and len(buf) + len(para) + 2 > CHUNK:
            out.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        out.append(buf)
    return out


def synth(key, vid, text, prev, nxt):
    payload = {
        "text": text,
        "model_id": MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    # Gives the model the surrounding prose so chunk seams don't reset prosody.
    # eleven_v3 rejects these outright, so only the v2 models get them.
    if not MODEL.startswith("eleven_v3"):
        if prev:
            payload["previous_text"] = prev[-400:]
        if nxt:
            payload["next_text"] = nxt[:400]
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format={FORMAT}",
        data=json.dumps(payload).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            raise SystemExit(f"ElevenLabs {e.code}: {detail}")
    return b""


def join(pieces, dest):
    """Stitch chunk MP3s into one file.

    Each chunk comes back as a self-contained MP3 with its own header, so simply
    concatenating the bytes leaves those headers stranded mid-stream — decoders
    report "Header missing" at every seam and seeking goes wrong. Remux through
    ffmpeg's concat demuxer instead (stream copy, so no quality is lost).
    """
    import shutil
    import subprocess
    import tempfile

    if len(pieces) == 1:
        dest.write_bytes(pieces[0])
        return
    if not shutil.which("ffmpeg"):
        print("      note: ffmpeg not found — seams may click")
        dest.write_bytes(b"".join(pieces))
        return

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        paths = []
        for i, piece in enumerate(pieces):
            p = tmp / f"{i:03d}.mp3"
            p.write_bytes(piece)
            paths.append(p)
        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in paths))
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-c", "copy", "-y", str(dest)],
            check=True, capture_output=True, text=True,
        )
        # Each chunk carries its own timestamps, so the muxer grumbles about
        # non-monotonic dts at every seam. The joined file decodes clean and
        # reports the right duration; only that one line is noise.
        noise = [l for l in proc.stderr.splitlines()
                 if l.strip() and "non monotonically increasing dts" not in l]
        for line in noise:
            print(f"      ffmpeg: {line}")


def render(key, vid, article, dest):
    parts = chunks(to_speech_text(article))
    pieces = []
    for i, part in enumerate(parts):
        prev = parts[i - 1] if i else ""
        nxt = parts[i + 1] if i + 1 < len(parts) else ""
        pieces.append(synth(key, vid, part, prev, nxt))
        print(f"      chunk {i + 1}/{len(parts)}", flush=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    join(pieces, dest)
    return dest.stat().st_size


def write_index():
    """audio/index.json — the app reads this to decide whether to show Listen."""
    idx = {}
    for day_dir in sorted(AUDIO.glob("20*")):
        if not day_dir.is_dir():
            continue
        ranks = sorted(int(p.stem) for p in day_dir.glob("*.mp3") if p.stem.isdigit())
        if ranks:
            idx[day_dir.name] = ranks
    (AUDIO / "index.json").write_text(json.dumps(idx, indent=1, sort_keys=True) + "\n")
    return idx


def prune(keep_days):
    """Drop narration older than keep_days. Articles stay; only audio ages out.

    Narration is the only thing in this repo that grows by megabytes a day, so
    without this the repo outgrows GitHub Pages in a couple of months.
    """
    import datetime

    cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
    freed = 0
    for day_dir in sorted(AUDIO.glob("20*")):
        if not day_dir.is_dir() or day_dir.name >= cutoff:
            continue
        for mp3 in day_dir.glob("*.mp3"):
            freed += mp3.stat().st_size
            mp3.unlink()
        day_dir.rmdir()
        print(f"pruned {day_dir.name}")
    write_index()
    print(f"Freed {freed // (1024 * 1024)} MB (kept the last {keep_days} days).")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--prune":
        prune(int(args[1]) if len(args) > 1 else 30)
        return

    days = sorted(p.stem for p in CONTENT.glob("20*.json"))
    if not days:
        sys.exit("No content files found.")

    if "--from" in args:
        i = args.index("--from")
        start = args[i + 1]
        end = args[args.index("--to") + 1] if "--to" in args else "9999"
        targets = [(d, None) for d in days if start <= d <= end]
    elif "--all" in args:
        # Every day ever written — that is months of articles and hundreds of
        # megabytes. Usually you want --from/--to for a single week.
        targets = [(d, None) for d in days]
    elif args and args[0].startswith("20"):
        targets = [(args[0], int(args[1]) if len(args) > 1 else None)]
    else:
        targets = [(days[-1], int(args[0]) if args else None)]

    key = api_key()
    vid, vname = voice_id()
    print(f"Voice: {vname} ({vid})   model: {MODEL}   format: {FORMAT}\n")

    made = 0
    for date, rank in targets:
        path = CONTENT / f"{date}.json"
        if not path.exists():
            print(f"{date}: no content file, skipped")
            continue
        day = json.loads(path.read_text())
        for a in sorted(day["articles"], key=lambda x: x["rank"]):
            if rank is not None and a["rank"] != rank:
                continue
            dest = AUDIO / date / f"{a['rank']}.mp3"
            if dest.exists() and not os.environ.get("FORCE"):
                print(f"{date} #{a['rank']}: exists, skipped (FORCE=1 to redo)")
                continue
            print(f"{date} #{a['rank']}: {a['title']}")
            size = render(key, vid, a, dest)
            made += 1
            # Rewrite the index after every article, not just at the end: a long
            # run that is interrupted should still leave the app able to play
            # everything already rendered.
            write_index()
            print(f"      -> {dest.relative_to(ROOT)}  {size // 1024} KB")

    idx = write_index()
    total = sum(len(v) for v in idx.values())
    print(f"\nRendered {made} file(s). audio/index.json now lists {total} across {len(idx)} day(s).")


if __name__ == "__main__":
    main()
