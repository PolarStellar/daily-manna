#!/usr/bin/env python3
"""Generate a whole week of Daily Manna articles, one day at a time, unhurried.

Written to be run either by hand or from launchd. It is idempotent: days that
already have articles are skipped, so a failed or half-finished run can simply
be run again.

Usage:
    python3 scripts/generate_week.py                     # this week (Mon–Sun)
    python3 scripts/generate_week.py --start 2026-08-10  # 7 days from a date
    python3 scripts/generate_week.py --start 2026-08-10 --days 3
    python3 scripts/generate_week.py --gap 300           # seconds between days
    python3 scripts/generate_week.py --dry-run

Gates (all must pass, or it exits quietly with nothing done):
  * the Studio server answers on 127.0.0.1:8790
  * no interactive `claude` session is running, unless --ignore-busy

The gap between days exists so a week's worth of generation never sits on the
Claude rate limit in one burst. Generation itself shells out to `claude -p`
inside serve.py, so this competes with Kris's own CLI usage — hence the gate.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
LOG = ROOT / "logs" / "generate_week.log"
BASE = "http://127.0.0.1:8790"

POLL = 15          # seconds between gen-status polls
DAY_TIMEOUT = 1500  # 25 min — a day that takes longer than this has hung


def say(msg):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def get(path, timeout=10):
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=timeout) as r:
        return json.load(r)


def post(path, payload, timeout=30):
    req = urllib.request.Request(
        f"{BASE}/{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def server_up():
    try:
        get("api/ping", timeout=5)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def claude_busy():
    """True if Kris has a Claude session of his own open.

    Counts any `claude` CLI process that isn't one of serve.py's own headless
    `claude -p` writers — terminal sessions and desktop-app sessions both, since
    both spend the same rate limit. Deliberately conservative: when this is on,
    the scheduled run backs off and tries again on the next pass.
    """
    try:
        out = subprocess.run(
            ["ps", "-ax", "-o", "command="],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return False       # can't tell → don't block on it
    for line in out.splitlines():
        cmd = line.strip()
        if "/claude-code/" not in cmd and not cmd.split(" ")[0].endswith("/claude"):
            continue
        if " -p " in cmd or cmd.endswith(" -p"):
            continue       # serve.py's own headless writer
        return True
    return False


def monday_of(d):
    return d - dt.timedelta(days=d.weekday())


def week_dates(start, days):
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]


def has_articles(iso):
    return (CONTENT / f"{iso}.json").exists()


def generate_day(iso):
    """Kick off one day and wait for it. Returns (ok, detail)."""
    try:
        post("api/generate", {"date": iso})
    except (urllib.error.URLError, OSError) as e:
        return False, f"could not reach the server: {e}"

    deadline = time.time() + DAY_TIMEOUT
    last_phase = ""
    while time.time() < deadline:
        time.sleep(POLL)
        try:
            s = get("api/gen-status")
        except (urllib.error.URLError, OSError):
            continue
        if s.get("phase") and s["phase"] != last_phase:
            last_phase = s["phase"]
            say(f"    {last_phase}")
        if s.get("running"):
            continue
        res = s.get("result") or {}
        if not res:
            continue
        if res.get("ok"):
            n = len(res.get("articles") or [])
            pushed = "pushed" if res.get("published") else "not pushed"
            return True, f"{n} articles, {pushed}"
        return False, res.get("error", "generation failed")
    return False, f"timed out after {DAY_TIMEOUT // 60} min"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="first date, YYYY-MM-DD (default: this Monday)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--gap", type=int, default=300, help="seconds to rest between days")
    ap.add_argument("--ignore-busy", action="store_true",
                    help="run even with an interactive claude session open")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    start = dt.date.fromisoformat(args.start) if args.start else monday_of(dt.date.today())
    dates = week_dates(start, args.days)
    todo = [d for d in dates if not has_articles(d)]

    say(f"week starting {start} — {len(dates)} days, {len(todo)} missing")
    if not todo:
        say("nothing to do")
        return 0

    if args.dry_run:
        say("dry run — would generate: " + ", ".join(todo))
        return 0

    if not server_up():
        say(f"gate: Studio server not answering at {BASE} — stopping, nothing done")
        return 1
    if not args.ignore_busy and claude_busy():
        say("gate: an interactive claude session is open — backing off, nothing done")
        return 1

    ok, failed = [], []
    for i, iso in enumerate(todo):
        say(f"[{i + 1}/{len(todo)}] {iso}")
        good, detail = generate_day(iso)
        say(f"    {'done' if good else 'FAILED'} — {detail}")
        (ok if good else failed).append(iso)
        if i + 1 < len(todo):
            say(f"    resting {args.gap // 60} min before the next day")
            time.sleep(args.gap)

    say(f"finished — {len(ok)} generated, {len(failed)} failed"
        + (f" ({', '.join(failed)})" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
