#!/usr/bin/env python3
"""Audition ElevenLabs female voices on a real Daily Manna article.

Usage:
    python3 scripts/audition_voices.py                 # latest day, article 1
    python3 scripts/audition_voices.py 2026-08-08 2    # specific day + article

Reads ELEVENLABS_API_KEY from the environment or from studio/.secrets
(JSON, gitignored). Writes MP3s to audio/auditions/.
"""

import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
OUT = ROOT / "audio" / "auditions"

MODEL = os.environ.get("ELEVEN_MODEL", "eleven_v3")
FALLBACK_MODEL = "eleven_multilingual_v2"

# Premade ElevenLabs voices, picked for calm + emotionally warm narration.
VOICES = [
    ("charlotte", "XB0fDUnXU5powFXDhCwa", "soft, intimate, most emotional of the three"),
    ("matilda", "XrExE9yKIg1WjnnlVkGX", "warm American narrator, steady and kind"),
    ("lily", "pFZP5JQG7iQjIQuC4Bku", "calm British narration, unhurried"),
]

# Swap-ins if none of the above land. Run with VOICES=rachel,sarah to try them.
EXTRA = {
    "rachel": ("21m00Tcm4TlvDq8ikWAM", "classic calm narrator"),
    "sarah": ("EXAVITQu4vr4xnSDxMaL", "soft, young, news-read"),
    "jessica": ("cgSgspJ2msm6clMCkdW9", "expressive, more animated"),
    "alice": ("Xb7hH8MSUJpSbSDYk0k2", "clear British, confident"),
}


def api_key():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key.strip()
    secrets = ROOT / "studio" / ".secrets"
    if secrets.exists():
        try:
            key = json.loads(secrets.read_text()).get("ELEVENLABS_API_KEY")
        except json.JSONDecodeError:
            sys.exit(f"{secrets} is not valid JSON.")
        if key:
            return key.strip()
    sys.exit(
        "No ElevenLabs API key. Put it in studio/.secrets as\n"
        '  {"ELEVENLABS_API_KEY": "sk_..."}\n'
        "or export ELEVENLABS_API_KEY."
    )


def to_speech_text(article):
    """HTML body -> clean prose the reader can speak."""
    body = article["body"]
    body = re.sub(r"</p>\s*<p>", "\n\n", body)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = html.unescape(body)
    body = re.sub(r"[ \t]+", " ", body).strip()
    return f"{article['title']}.\n\n{article['dek']}\n\n{body}"


def clip(text, limit=900):
    """Trim to a sentence boundary so the audition doesn't end mid-thought."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > 300 else cut


def synth(key, voice_id, text, model):
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        "?output_format=mp3_44100_128",
        data=json.dumps(
            {
                "text": text,
                "model_id": model,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
        ).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def main():
    args = [a for a in sys.argv[1:]]
    days = sorted(p.stem for p in CONTENT.glob("20*.json"))
    if not days:
        sys.exit("No content files found.")
    date = args[0] if args and args[0].startswith("20") else days[-1]
    rank = int(args[1]) if len(args) > 1 else (int(args[0]) if args and not args[0].startswith("20") else 1)

    day = json.loads((CONTENT / f"{date}.json").read_text())
    article = next(a for a in day["articles"] if a["rank"] == rank)

    text = clip(to_speech_text(article))
    print(f"Article: {date} #{rank} — {article['title']}")
    print(f"Sample: {len(text)} chars (~{len(text) // 15}s of audio)\n")

    voices = VOICES
    want = os.environ.get("VOICES")
    if want:
        voices = [(n, *EXTRA[n]) for n in want.split(",") if n in EXTRA]

    key = api_key()
    OUT.mkdir(parents=True, exist_ok=True)
    model = MODEL
    for name, voice_id, note in voices:
        path = OUT / f"{date}-{rank}-{name}.mp3"
        try:
            audio = synth(key, voice_id, text, model)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if model != FALLBACK_MODEL and ("model" in detail or e.code in (400, 403)):
                print(f"  {MODEL} rejected ({e.code}); retrying on {FALLBACK_MODEL}")
                print(f"    detail: {detail}")
                model = FALLBACK_MODEL
                audio = synth(key, voice_id, text, model)
            else:
                print(f"  {name}: FAILED {e.code} — {detail}")
                continue
        path.write_bytes(audio)
        print(f"  {name:10s} {len(audio) // 1024:5d} KB  {note}\n             {path}")

    print(f"\nModel used: {model}")


if __name__ == "__main__":
    main()
