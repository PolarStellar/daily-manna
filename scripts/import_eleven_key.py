#!/usr/bin/env python3
"""Copy the ElevenLabs key from the MCS Podcast Pipeline's .env into
studio/.secrets, so Daily Manna can narrate without the key being retyped.

Run it yourself:  python3 scripts/import_eleven_key.py

It never prints the key — only a masked confirmation. Both files are
gitignored, so the key stays off GitHub.
"""
import json
import os
import sys

SRC = os.path.expanduser("~/Documents/MCS/Podcast Pipeline/.env")
HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(os.path.dirname(HERE), "studio", ".secrets")
NAME = "ELEVENLABS_API_KEY"


def read_env_value(path, name):
    if not os.path.exists(path):
        sys.exit(f"Not found: {path}")
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    sys.exit(f"{name} is not set in {path}")


def main():
    key = read_env_value(SRC, NAME)
    if not key or key.upper().startswith("PASTE"):
        sys.exit(f"{NAME} in {SRC} looks empty or is still a placeholder.")

    secrets = {}
    if os.path.exists(DEST):
        try:
            secrets = json.load(open(DEST))
        except ValueError:
            secrets = {}          # a placeholder/corrupt file is fine to replace
    secrets[NAME] = key
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    with open(DEST, "w") as fh:
        json.dump(secrets, fh, indent=2)
        fh.write("\n")
    os.chmod(DEST, 0o600)         # owner-only, like any credential file

    masked = f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "(short)"
    print(f"Copied {NAME} ({masked}, {len(key)} chars)")
    print(f"  from {SRC}")
    print(f"  into {DEST}  (chmod 600)")
    print("\nNow tell Claude 'go' and the narration run will start.")


if __name__ == "__main__":
    main()
