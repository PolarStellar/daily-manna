# Daily Manna

Kris's personal daily devotional reader. Reader's Digest–style articles from
the SCC Bible Reading Plan, Filipino-first, written by Claude.

**Live site (read anywhere):** https://polarstellar.github.io/daily-manna/

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

## The Studio server (what powers the button)

`studio/serve.py` runs on your Mac. It serves the app at http://localhost:8790
and adds the write-side API the public site can't have:

- `POST /api/generate` → writes today's 4 articles (Claude; Gemini fallback if a
  key is set), commits, and pushes. Runs as a background job.
- `GET /api/gen-status` → progress for the button to poll.
- `POST /api/love` → records a ♥ into `loved.json` (see Hearts).

Start it: **double-click `Start Daily Manna.command`** (keep the window open),
or run `python3 studio/serve.py`. First run may ask Terminal for permission to
read your Documents folder — click OK.

It binds `127.0.0.1` (Mac-only, no Tailscale needed). Generation uses your
claude.ai login. Model is **Sonnet** (fast, strong writer) — change `CLAUDE_MODEL`
in `serve.py` for a different one. Optional Gemini fallback: put
`{"GEMINI_API_KEY": "…"}` in `studio/.secrets` (gitignored).

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

## Files

| File | What it is |
|---|---|
| `index.html` | The whole reader app (no build step) |
| `plan.json` | All 365 days of the SCC reading plan |
| `content/YYYY-MM-DD.json` | One generated day (4 articles) |
| `content/index.json` | List of generated days (drives Past Days) |
| `loved.json` | Your hearted articles (teaches generation) |
| `studio/serve.py` | Local generator + control server |
| `studio/ARTICLE_PROMPT.md` | The single-article writing spec |

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
