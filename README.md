# Daily Manna

Kris's personal daily devotional reader. Each morning, Claude writes 4
Reader's Digest-style articles from that day's SCC Bible Reading Plan
passages and publishes them here.

**Live site:** https://polarstellar.github.io/daily-manna/

## Daily use

1. Open Claude Code in the Slides Maker folder and say **"today's devotions"**.
2. Wait ~2–3 minutes. Claude reads today's plan, searches fresh news for
   illustrations, writes the 4 articles, and pushes them live.
3. Open the site on your phone (add it to your home screen once:
   Safari → Share → **Add to Home Screen**).

If you open the site before generating, it shows today's passages and a
reminder — nothing breaks.

## What's in here

| File | What it is |
|---|---|
| `index.html` | The whole reader app (no build step, no framework) |
| `plan.json` | All 365 days of the SCC reading plan, extracted from the PDF |
| `content/YYYY-MM-DD.json` | One file per day: that day's 4 articles |
| `scripts/extract_plan.py` | One-time PDF → plan.json extractor (already run) |
| `manifest.json`, `icon.png` | Phone home-screen app support |

## Troubleshooting

- **Site shows yesterday's date/articles** — pull-to-refresh; the app loads
  by your phone's local date.
- **"Today's articles aren't ready yet"** — generation hasn't run today; say
  "today's devotions" in Claude Code.
- **Push failed** — articles are saved locally in `content/`; run
  `git push` from this folder when back online.
- **Regenerate a day** — tell Claude "regenerate today's devotions" (or name
  the date).

Hosting is free (GitHub Pages, public repo). No accounts, no database, no
server to maintain.
