#!/usr/bin/env python3
"""Keep a rolling week of Daily Manna articles in the bank, one day at a time.

Written to be run either by hand or from launchd. It is idempotent: days that
already have articles are skipped, so a failed or half-finished run can simply
be run again.

It tops up a *rolling* window — today and the next six days — rather than the
current calendar week. The calendar week was the old behaviour and it emptied
out: by Saturday, "Mon–Sun of this week" is one day of runway, so a Mac that
was off over the weekend left the phone with nothing to read. A window anchored
on today never has less than a week ahead of it.

Usage:
    python3 scripts/generate_week.py                     # today + next 6 days
    python3 scripts/generate_week.py --days 14           # bank a fortnight
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
BASE = "http://127.0.0.1:8790"

# --remote exists because of macOS TCC: a launchd job does not inherit the
# Documents-folder permission that Terminal has, so the scheduled copy of this
# script lives outside ~/Documents and must never touch the repo directly. In
# that mode the day list comes from the Studio server over HTTP and the log goes
# somewhere launchd can always write.
REMOTE = "--remote" in sys.argv
LOG = (Path.home() / "Library/Logs/daily-manna-week.log" if REMOTE
       else ROOT / "logs" / "generate_week.log")

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


def window_dates(start, days):
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(days)]


def existing_days():
    """The days that already have articles, as a set of ISO strings."""
    if REMOTE:
        try:
            return set(get("content/index.json").get("days") or [])
        except (urllib.error.URLError, OSError, ValueError) as e:
            say(f"could not read the day index from the server: {e}")
            return None
    return {p.stem for p in CONTENT.glob("20*.json")}


def job_running():
    try:
        return bool(get("api/gen-status").get("running"))
    except (urllib.error.URLError, OSError, ValueError):
        return False


def generate_day(iso):
    """Kick off one day and wait for it. Returns (ok, detail)."""
    try:
        started = post("api/generate", {"date": iso})
    except (urllib.error.URLError, OSError) as e:
        return False, f"could not reach the server: {e}"
    # serve.py runs one job at a time; if a different day was already in flight
    # our poll below would read that day's result as ours.
    if started.get("date") and started["date"] != iso:
        return False, f"server is busy with {started['date']}"

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
    ap.add_argument("--start", help="first date, YYYY-MM-DD (default: today)")
    ap.add_argument("--days", type=int, default=7,
                    help="size of the rolling window to keep filled (default: 7)")
    ap.add_argument("--gap", type=int, default=300, help="seconds to rest between days")
    ap.add_argument("--ignore-busy", action="store_true",
                    help="run even with an interactive claude session open")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--remote", action="store_true",
                    help="never touch the repo directly; ask the Studio server instead")
    args = ap.parse_args()

    # Anchored on today, not on Monday: the point is a full week of runway at
    # every moment, not a week that shrinks to nothing by Sunday night.
    start = dt.date.fromisoformat(args.start) if args.start else dt.date.today()
    dates = window_dates(start, args.days)

    # In --remote mode the server is the only way to see anything, so check it
    # before asking it which days exist.
    if not server_up():
        say(f"gate: Studio server not answering at {BASE} — stopping, nothing done")
        return 1

    have = existing_days()
    if have is None:
        return 1
    todo = [d for d in dates if d not in have]

    say(f"rolling window {start} → {dates[-1]} — {len(dates)} days, {len(todo)} missing")
    if not todo:
        say("nothing to do")
        return 0

    if args.dry_run:
        say("dry run — would generate: " + ", ".join(todo))
        return 0
    if not args.ignore_busy and claude_busy():
        say("gate: a Claude session is open — backing off, nothing done")
        return 1
    if job_running():
        say("gate: the Studio server is already generating a day — backing off")
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
