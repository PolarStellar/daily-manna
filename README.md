# Daily Manna

Kris's personal daily devotional reader. Reader's Digest–style articles from
the SCC Bible Reading Plan, Filipino-first, written by Claude.

**Live site (read anywhere):** https://polarstellar.github.io/daily-manna/

Reading needs no Mac, no Tailscale, and no VPN — the site is plain static files
on GitHub Pages, and the rolling week (below) keeps it stocked ahead of you.
Tailscale is only ever needed to *generate* on demand from the phone.

## Two ways to generate a day's articles

**A. The button (on your Mac).** Open the local app at **http://localhost:8790**
(the "Studio" server, below). When today isn't written yet you'll see
**"✍️ Generate today's devotions"** — tap it. It writes the 4 articles, saves,
and pushes them live. Takes **~5–9 minutes** (4 articles written in parallel by
`claude`, plus a quick news search) — it runs in the background with a progress
line, so you can leave the tab and come back. A **"↻ Regenerate today"** link
does the same for a day that already exists.

**B. Claude Code.** Say **"today's devotions"** and the `/devotions` skill does
the same thing interactively.

Either way you then read on your phone at the live site.

## The next-7-days button

The home screen carries **📅 Generate the next 7 days**. One tap fills every
empty day in the rolling window — today and the following six — and skips any
day that already has articles, so it is safe to tap whenever.

The work happens on the Mac, not in the browser. `POST /api/generate-week` walks
the missing days server-side and each day is written and pushed on its own, so
the phone can lock and the tab can close mid-run without stopping it, and an
interrupted run still leaves every finished day live. The button shows the
progress it polls back — `Day 2 of 4 (2026-09-02) — Writing the 4 articles…`.

It only appears when the generator is actually reachable (the Mac, or the Mac
over Tailscale). On the public site with the Mac asleep there is nothing it
could do, so it stays hidden.

**Restarting from the phone.** The home screen carries **↻ Update & restart the
Mac server** whenever the generator is reachable. It pulls the latest code and
re-execs `serve.py`, then waits for it to answer again before saying so. The
server compile-checks itself first and refuses to restart if the new code will
not run — otherwise a restart from the phone could leave nothing listening, with
the Mac the only way back in.

**Restart `serve.py` after updating** — the endpoint it calls is new, and a
Studio server started before this change does not have it.

## The Studio server (what powers the button)

`studio/serve.py` runs on your Mac. It serves the app at http://localhost:8790
and adds the write-side API the public site can't have:

- `POST /api/generate` → writes today's 4 articles (Claude; Gemini fallback if a
  key is set), commits, and pushes. Runs as a background job.
- `POST /api/generate-week` → fills every empty day in the rolling 7-day window,
  one at a time, pushing each as it lands. Also a background job.
- `GET /api/gen-status` → progress for the button to poll.
- `POST /api/love` → records a ♥ into `loved.json` (see Hearts).

Start it: **double-click `Start Daily Manna.command`** (keep the window open),
or run `python3 studio/serve.py`. First run may ask Terminal for permission to
read your Documents folder — click OK.

It binds `127.0.0.1` (Mac-only, no Tailscale needed). Generation uses your
claude.ai login. Model is **Sonnet** (fast, strong writer) — change `CLAUDE_MODEL`
in `serve.py` for a different one. Optional Gemini fallback: put
`{"GEMINI_API_KEY": "…"}` in `studio/.secrets` (gitignored).

## A week at a time (and the agent that does it for you)

`scripts/generate_week.py` keeps a **rolling week in the bank** — today and the
next six days — writing one day at a time and resting between days so a week's
generation never lands on the Claude rate limit in one burst. It is idempotent —
days that already have articles are skipped — so a failed or half-finished run
is just run again.

The window is anchored on *today*, not on Monday. Anchoring it to the calendar
week meant the runway shrank as the week went on: by Saturday, "Mon–Sun of this
week" is one day of articles left, so a Mac that was off over the weekend left
the phone with nothing to read. Anchored on today, there is never less than a
week ahead.

```
python3 scripts/generate_week.py                     # today + next 6 days
python3 scripts/generate_week.py --days 14           # bank a fortnight instead
python3 scripts/generate_week.py --start 2026-08-10 --days 7
python3 scripts/generate_week.py --gap 600           # rest 10 min between days
python3 scripts/generate_week.py --dry-run           # say what it would do
```

It refuses to start unless every gate is open, and says which one stopped it:

- the Studio server answers on `127.0.0.1:8790` (so: Mac awake, app running)
- no Claude session of yours is open — terminal or desktop app (`--ignore-busy`
  overrides; serve.py's own headless `claude -p` writers don't count)
- no generation is already in flight

**The agent.** `scripts/install_weekly_agent.sh` installs a launchd job that
runs the above hourly from 7am to 9pm. Because it gates and skips, almost every
pass does nothing and exits in well under a second — it only does real work when
the week is short *and* you're not using Claude. That also means a Mac that was
off on Monday, or a day that failed, gets picked up on the next pass instead of
waiting a week.

```
./scripts/install_weekly_agent.sh install daily      # or: install monday
./scripts/install_weekly_agent.sh status
./scripts/install_weekly_agent.sh uninstall
```

Progress and back-offs are logged to `logs/generate_week.log` (gitignored).

## Listening (narrated articles)

**Every generated day is narrated automatically.** Writing a day now renders its
4 articles to MP3 before publishing, so a day goes live with its audio in the
same commit instead of showing up silent and growing a Listen player later.
`audio/` is staged by `git_publish`, so the narration reaches the phone too.

Narration is deliberately non-fatal: if it fails, or no ElevenLabs key is
configured, the day still publishes with its articles and simply has no Listen
player. Articles that already have an MP3 are never re-rendered.

Any article with a narrated MP3 gets a small **Listen** player under the dek:
play/pause, a scrubbable progress bar, and a speed toggle (1× / 1.25× / 1.5× /
0.85×). It remembers where you stopped, only one article plays at a time,
collapsing an article stops it, and hearing one to the end marks it read. If a
day has no audio, no player appears — nothing else changes.

Audio lives in `audio/<date>/<rank>.mp3`, and `audio/index.json` is what the app
checks. Both are committed so the phone can play them from the live site.

**Pick a voice first.** Renders the same real article through three calm female
voices so you can compare:

```
python3 scripts/audition_voices.py            # latest day, article 1 → audio/auditions/
VOICES=rachel,sarah python3 scripts/audition_voices.py    # try the swap-ins
```

To narrate by hand — a backfill, or a day whose audio failed (default voice
`matilda`, model `eleven_v3`):

```
python3 scripts/generate_audio.py             # latest day, all 4 articles
VOICE=lily python3 scripts/generate_audio.py 2026-08-08
python3 scripts/generate_audio.py --from 2026-08-15 --to 2026-09-03   # a range
python3 scripts/generate_audio.py --all       # every day ever written — hundreds of MB
```

`--all` means *every* day in `content/`, which is months of articles; prefer
`--from`/`--to`. The index is rewritten after every single file, so an
interrupted run still leaves everything already rendered playable.

Existing files are skipped; `FORCE=1` re-renders. `audio/auditions/` is
gitignored, the real `audio/<date>/` is not.

Needs an ElevenLabs key — `{"ELEVENLABS_API_KEY": "…"}` in `studio/.secrets`
(gitignored), or `ELEVENLABS_API_KEY` in the environment. If you already have
one in the MCS podcast pipeline's `.env`, copy it across without retyping it:

```
python3 scripts/import_eleven_key.py
```

**Audio needs the Studio server, not just the files.** `serve.py` serves MP3s
with byte-range support (`206 Partial Content`); Safari will not start playback
without it and no browser can seek without it. A server started before that
existed will show a Listen player that does nothing — restart it.

**Narration lives in its own repo**, [daily-manna-audio][dma], served over its
own Pages site at `https://polarstellar.github.io/daily-manna-audio/<date>/<rank>.mp3`.
`audio/index.json` stays in this tree — about a kilobyte, and it is what tells
the reader which articles have narration — rebuilt *from* the audio repo, so
that repo is the single source of truth.

[dma]: https://github.com/PolarStellar/daily-manna-audio

This fixes the real problem: in-tree, every MP3 ever rendered stayed in git
history forever, so the clone grew ~360 MB a month no matter what was pruned,
and Pages refuses to serve a site over 1 GB. The audio repo's history is
disposable — nothing in it cannot be re-rendered — so it can be recreated if it
ever gets heavy.

**GitHub Releases was tried first and cannot work.** Release downloads are served
`Content-Type: application/octet-stream` with `Content-Disposition: attachment`,
hardcoded into the signed URL and not overridable even when the asset is stored
as `audio/mpeg`. Safari refuses to play audio on those, so it failed on the phone
while Chrome — which sniffs the bytes — played it and hid the fault. Pages sends
`audio/mp3` and honours byte ranges, which the player needs to start and to seek.
`--verify` now checks the Content-Type for exactly this reason.

The audio repo must be checked out beside this one (or set
`DAILY_MANNA_AUDIO_REPO`):

```
git clone https://github.com/PolarStellar/daily-manna-audio.git ../daily-manna-audio
```

```
python3 scripts/audio_publish.py --publish             # move rendered days over, push
python3 scripts/audio_publish.py --publish 2026-09-04  # one day
python3 scripts/audio_publish.py --index               # rebuild index.json
python3 scripts/audio_publish.py --prune 30            # drop days older than 30
python3 scripts/audio_publish.py --verify              # type + ranges on every file
```

**The one cost: audio no longer plays offline.** The service worker ignores
cross-origin requests, so narration needs a connection. Articles remain readable
offline exactly as before.

**Old narration ages out automatically.** Every generation deletes days from the audio repo
older than 30 days (`KEEP_AUDIO_DAYS` in `serve.py`) — on Sep 3 that drops Aug 3
and older. Articles are never touched, only the MP3s, and any day can be
re-narrated later with `generate_audio.py --from … --to …` followed by
`audio_publish.py --publish`.

Because the files live in another repo, deleting them keeps this one small —
unlike the in-tree version, where history kept every byte forever.

**Watch the repo size.** At the default `mp3_44100_64` a 7-minute article is
~3 MB, so a full day is ~12 MB and a month is ~350 MB. If that gets heavy,
set `ELEVEN_FORMAT=mp3_22050_32` (about half), narrate only article 1 each day,
or delete old `audio/<date>/` folders and re-run `generate_audio.py` to rewrite
`audio/index.json`.

## Hearts (teaching the writer your taste)

Tap **♥ Love this** at the end of any article. Loved articles are saved to your
device *and* (on the Mac app) to `loved.json`, which is committed so your hearts
show on every device. Each future generation feeds your most-recent loved
articles into the prompt as "write toward this taste" — so the more you heart,
the more the articles bend toward what you love. (This is prompt-level taste
matching, not model training.) Hearts tapped only on the phone stay your
personal collection until they reach the Mac.

## Reading features

- Home: today's readings + "Read the 4" / "Just the Best One".
- Articles you finish are collapsed on your next visit (tap a title to reopen).
- **Past Days** lists every day you've generated.
- Add to Home Screen (Safari → Share) for an app icon; File → Add to Dock on Mac.

## Public, but not findable

The site is public so it opens on any phone with no VPN, but it is kept out of
search: `index.html` carries a `noindex` meta tag and `robots.txt` blocks the
data directories outright plus every AI-training crawler.

The page itself is deliberately left crawlable. A crawler has to be allowed to
fetch it in order to read the `noindex` tag and drop the site — blocking the
page in `robots.txt` would hide that tag and let a discovered URL linger as a
bare, title-less search result.

This is unlisted, not private: **anyone with the link can read it.** Nothing
here is secret, so that is the intended trade. Real privacy would mean a login
gate (Cloudflare Access) and giving up the current URL.

## Files

| File | What it is |
|---|---|
| `index.html` | The whole reader app (no build step) |
| `robots.txt` | Keeps the public site out of search engines |
| `scripts/audio_publish.py` | Publishes/prunes narration in the audio repo |
| `audio/index.json` | Which articles have narration (the MP3s are not in git) |
| `plan.json` | All 365 days of the SCC reading plan |
| `content/YYYY-MM-DD.json` | One generated day (4 articles) |
| `content/index.json` | List of generated days (drives Past Days) |
| `loved.json` | Your hearted articles (teaches generation) |
| `studio/serve.py` | Local generator + control server |
| `studio/ARTICLE_PROMPT.md` | The single-article writing spec |

## Generating from your phone (Tailscale)

The Generate button works on your phone too, over your private Tailscale network:
1. On the **Mac**: Studio server running (the launcher) **and** Tailscale on.
2. On the **phone**: Tailscale on. Open the live site — the app finds your Mac at
   `https://kriss-macbook-pro.taila0e65f.ts.net:8790` and the Generate button
   appears. Hearts you tap on the phone now reach the Mac too (they teach the writer).

The Mac side is already set up: `tailscale serve --bg --https=8790 localhost:8790`
proxies the tailnet to the local server (turn off with
`tailscale serve --https=8790 off`). If your Mac is off or Tailscale is down, the
phone simply falls back to read-only — reading always works.

## Keeping it running

Double-click **`Start Daily Manna.command`** and leave the window open — that's
the whole server. (A background launchd agent can't be used here: macOS privacy
blocks background agents from reading `~/Documents`, where this project lives.
The double-click launcher runs in your session, which has that access.)

## Troubleshooting

- **No Generate button** — the Studio server isn't running / you're on the
  public site. Start `serve.py` and open http://localhost:8790.
- **Generation says it failed** — check the phase message; re-tap. It retries
  Claude twice per article, then Gemini (if configured).
- **Push failed** — articles are saved locally in `content/`; `git push` later.
