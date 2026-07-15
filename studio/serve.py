#!/usr/bin/env python3
"""Daily Manna Studio — local control server (runs on Kris's Mac).

Serves the Daily Manna reader AND the write-side API the static GitHub Pages
copy can't have: generate today's articles with the Claude CLI (Gemini fallback
when a key is present), and record "loved" articles that teach future runs.

    python3 studio/serve.py     ->  http://localhost:8790

Bound to 127.0.0.1 (Mac-only, no Tailscale required). To reach it from the
phone later, bind 0.0.0.0 and expose the port with `tailscale serve` — no code
change beyond the HOST constant.
"""
import os
import re
import json
import html
import shutil
import datetime
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                     # the daily-manna/ dir
CONTENT = os.path.join(ROOT, "content")
LOVED_FILE = os.path.join(ROOT, "loved.json")
ARTICLE_PROMPT_FILE = os.path.join(HERE, "ARTICLE_PROMPT.md")
PLAN_FILE = os.path.join(ROOT, "plan.json")
SECRETS_FILE = os.path.join(HERE, ".secrets")     # gitignored; optional GEMINI_API_KEY

HOST, PORT = "127.0.0.1", 8790
CLAUDE_MODEL = "sonnet"          # excellent writer, ~5x cheaper than Opus; change if desired
GEMINI_MODEL = "gemini-2.5-pro"

# Origins allowed to call the write API cross-origin (the public reader, and the
# local app). Anything else is refused — the server stays reachable only from
# the Mac (localhost) and the private tailnet.
ALLOWED_ORIGINS = {
    "https://polarstellar.github.io",
    "http://localhost:8790", "http://127.0.0.1:8790",
}

# One writer per reading, run in parallel. rank 1 = the day's lead.
SLOTS = [
    {"rank": 1, "reading": "nt", "label": "New Testament", "texture": "a vivid narrative drama"},
    {"rank": 2, "reading": "ot", "label": "Old Testament", "texture": "relational, human wisdom"},
    {"rank": 3, "reading": "psalm", "label": "Psalm", "texture": "quiet, pastoral, intimate"},
    {"rank": 4, "reading": "prov", "label": "Proverbs", "texture": "practical and gospel-centered"},
]

# Illustration lenses — the day's 4 articles each get a DIFFERENT one so the
# batch never leans on the same well (esp. not Philippine current events).
# Rotated by day-of-year so the mix shifts daily. Kris: roam widely, lean positive.
LENSES = [
    "a moment from world history (any country, any era) — a person, discovery, or turning point",
    "something from nature — an animal, insect, plant, or the human body — that does something surprising most people don't know",
    "a business story, case study, or how a person/organization solved a hard problem",
    "a recent, POSITIVE news story or an uplifting public moment (e.g. an inspiring speech), from anywhere",
    "a discovery or how-it-works from science or medicine",
    "a story from another culture or country that a Filipino would still feel",
    "a slice of everyday Filipino life, or a hopeful local story",
    "a figure from history whose courage, kindness, or wisdom mirrors the passage",
]
ILLUS_LEDGER = os.path.join(ROOT, "used_illustrations.json")


def lenses_for(iso):
    """Pick 4 distinct lenses for the day, offset by day-of-year for variety."""
    doy = datetime.date.fromisoformat(iso).timetuple().tm_yday
    return [LENSES[(doy + i) % len(LENSES)] for i in range(4)]


def load_used_illustrations(limit=60):
    try:
        data = json.load(open(ILLUS_LEDGER))
        return [e["label"] for e in data.get("used", [])][-limit:]
    except Exception:
        return []


def record_illustrations(iso, articles):
    used = []
    try:
        used = json.load(open(ILLUS_LEDGER)).get("used", [])
    except Exception:
        pass
    for a in articles:
        lab = (a.get("illustration") or "").strip()
        if lab:
            used.append({"date": iso, "label": lab})
    tmp = ILLUS_LEDGER + ".tmp"
    json.dump({"used": used[-400:]}, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, ILLUS_LEDGER)

STATIC_TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json",
                ".webmanifest": "application/manifest+json", ".png": "image/png",
                ".svg": "image/svg+xml", ".css": "text/css", ".js": "text/javascript"}


# ----------------------------- data helpers -----------------------------
def today_iso():
    return datetime.date.today().isoformat()


def pretty(iso):
    y, m, d = map(int, iso.split("-"))
    return datetime.date(y, m, d).strftime("%A, %B %-d, %Y")


def load_plan():
    with open(PLAN_FILE) as f:
        return json.load(f)


def load_loved():
    try:
        return json.load(open(LOVED_FILE)).get("loved", [])
    except Exception:
        return []


def save_loved(keys):
    keys = sorted(set(keys))
    tmp = LOVED_FILE + ".tmp"
    json.dump({"loved": keys}, open(tmp, "w"), indent=1)
    os.replace(tmp, LOVED_FILE)
    return keys


def _secret(name):
    try:
        v = json.load(open(SECRETS_FILE)).get(name)
        if v:
            return v
    except Exception:
        pass
    return os.environ.get(name)


def _plain(htmltext, limit=600):
    t = re.sub(r"<[^>]+>", " ", htmltext or "")
    t = html.unescape(re.sub(r"\s+", " ", t)).strip()
    return t[:limit] + ("…" if len(t) > limit else "")


def loved_block():
    """Turn Kris's loved articles into a 'here's the taste to match' block."""
    keys = load_loved()
    if not keys:
        return ("## Kris hasn't hearted any articles yet\nWrite in the strong "
                "default voice above.")
    examples, seen = [], 0
    for key in keys[::-1]:                    # most-recent first
        if seen >= 6:
            break
        try:
            date, rank = key.split("#")
            data = json.load(open(os.path.join(CONTENT, date + ".json")))
            art = next(a for a in data["articles"] if int(a["rank"]) == int(rank))
        except Exception:
            continue
        seen += 1
        examples.append(
            f"- **{art['title']}** ({art['passage']}). Hook: {art['dek']}\n"
            f"  Key line: “{art.get('quote', '')}”\n"
            f"  Opening: {_plain(art['body'], 500)}")
    if not examples:
        return "## (Loved articles could not be loaded — use the default voice.)"
    return ("## Articles Kris LOVED — write today toward this taste\n"
            "Study what these share: their angle of surprise, emotional beat, "
            "structure, subject matter, and voice. Today's articles should feel "
            "like they belong on the same shelf — without copying their topics.\n\n"
            + "\n".join(examples))


# ----------------------------- model calls -----------------------------
def _run_claude(prompt, allow_web, timeout=300):
    """One headless claude call. Uses Kris's claude.ai login (strips any inherited
    session API key that would override it). Returns the model's final text."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    # Strip project settings/MCP/skills: a clean writer, not this repo's agent.
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", CLAUDE_MODEL,
           "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands"]
    if allow_web:
        cmd += ["--allowedTools", "WebSearch"]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    if p.returncode != 0:
        raise RuntimeError(f"claude exited {p.returncode}: {p.stderr[-300:]}")
    env_out = json.loads(p.stdout)
    if env_out.get("is_error"):
        raise RuntimeError(f"claude error: {env_out.get('result', '')[:300]}")
    return env_out.get("result", "")


def _run_gemini(prompt):
    key = _secret("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no GEMINI_API_KEY configured")
    import urllib.request
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={key}")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _extract_obj(text):
    if not text:
        raise ValueError("empty output")
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    blob = m.group(1) if m else None
    if blob is None:
        i, j = text.find("{"), text.rfind("}")
        if i == -1 or j <= i:
            raise ValueError("no JSON object found")
        blob = text[i:j + 1]
    return json.loads(blob)


# ----------------------------- generation -----------------------------
def fetch_news(iso):
    """One quick, time-boxed call for Philippine-first news to season the writers.
    Fully optional — on any hiccup we return '' and articles use timeless
    illustrations (which the voice guide treats as an equal choice)."""
    prompt = (
        "Do 1-2 web searches for genuinely recent (last 48 hours) news, PHILIPPINE "
        "first (local headlines, Manila, Filipino life, weather, good-news), plus one "
        "notable world story only if striking. Return ONLY a JSON array of up to 5 "
        'items: [{"headline":"…","gist":"one sentence"}]. No other text.')
    try:
        text = _run_claude(prompt, allow_web=True, timeout=150)
        i, j = text.find("["), text.rfind("]")
        items = json.loads(text[i:j + 1]) if i != -1 and j > i else []
        lines = [f"- {it.get('headline','').strip()} — {it.get('gist','').strip()}"
                 for it in items if it.get("headline")]
        return "\n".join(lines[:5])
    except Exception:
        return ""


def build_article_prompt(iso, slot, reading_ref, news_block, lens, avoid):
    avoid_block = ("\n".join("- " + a for a in avoid) if avoid
                   else "(nothing yet — you have a clean slate.)")
    tmpl = open(ARTICLE_PROMPT_FILE).read()
    return (tmpl.replace("{{DATE}}", iso).replace("{{PRETTY_DATE}}", pretty(iso))
            .replace("{{READING_LABEL}}", slot["label"])
            .replace("{{READING_REF}}", reading_ref)
            .replace("{{RANK}}", str(slot["rank"]))
            .replace("{{TEXTURE}}", slot["texture"])
            .replace("{{LENS}}", lens)
            .replace("{{AVOID}}", avoid_block)
            .replace("{{NEWS}}", news_block or "(no fresh news fetched — draw from the lens above instead.)")
            .replace("{{LOVED_BLOCK}}", loved_block()))


def _validate_article(a, rank):
    if not isinstance(a, dict):
        raise ValueError("not an object")
    for k in ("title", "dek", "passage", "minutes", "quote", "body"):
        if not a.get(k):
            raise ValueError(f"missing field: {k}")
    a["rank"] = rank
    a["minutes"] = int(a["minutes"])
    a["illustration"] = (a.get("illustration") or "").strip()
    return a


def gen_one_article(iso, slot, reading_ref, news_block, lens, avoid):
    """Write one article: Claude, retry once, then Gemini fallback."""
    prompt = build_article_prompt(iso, slot, reading_ref, news_block, lens, avoid)
    errors = []
    attempts = [(_run_claude, {"allow_web": False}), (_run_claude, {"allow_web": False}),
                (_run_gemini, {})]
    for engine, kw in attempts:
        try:
            text = engine(prompt, **kw)
            return _validate_article(_extract_obj(text), slot["rank"])
        except Exception as e:
            errors.append(f"{engine.__name__}: {e}")
    raise RuntimeError(f"article rank {slot['rank']} failed — " + " | ".join(errors[-3:]))


def _generate_core(iso, force, push, phase):
    out = os.path.join(CONTENT, iso + ".json")
    if os.path.exists(out) and not force:
        return {"ok": True, "date": iso, "already": True,
                "articles": json.load(open(out))["articles"]}
    readings = load_plan().get(iso[5:])
    if not readings:
        return {"ok": False, "error": f"no reading plan entry for {iso}"}

    phase("Looking for today's news…")
    news_block = fetch_news(iso)
    lenses = lenses_for(iso)                 # 4 distinct illustration domains for the day
    avoid = load_used_illustrations()        # never reuse a past illustration
    phase("Writing the 4 articles…")
    articles, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:    # 4 writers in parallel
        futs = [pool.submit(gen_one_article, iso, s, readings[s["reading"]], news_block, lenses[i], avoid)
                for i, s in enumerate(SLOTS)]
        for fut in futs:
            try:
                articles.append(fut.result())
            except Exception as e:
                errors.append(str(e))
    if len(articles) < 4:
        return {"ok": False, "error": "; ".join(errors) or "generation incomplete"}

    articles.sort(key=lambda a: a["rank"])
    obj = {"date": iso, "readings": readings, "articles": articles}
    os.makedirs(CONTENT, exist_ok=True)
    tmp = out + ".tmp"
    json.dump(obj, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    record_illustrations(iso, articles)      # remember what we used so it's never reused
    rebuild_index()
    published = False
    if push:
        phase("Publishing…")
        published = git_publish(iso)
    return {"ok": True, "date": iso, "articles": articles, "published": published}


# Background job: generation takes minutes, so it must never block the HTTP
# request (that caused client timeouts + broken pipes). The app polls status.
_job = {"running": False, "done": False, "phase": "", "result": None, "date": None}
_job_lock = threading.Lock()


def start_generation(iso=None, force=False, push=True):
    iso = iso or today_iso()
    with _job_lock:
        if _job["running"]:
            return {"ok": True, "running": True, "date": _job["date"]}
        _job.update(running=True, done=False, phase="Starting…", result=None, date=iso)

    def worker():
        def phase(p):
            with _job_lock:
                _job["phase"] = p
        try:
            res = _generate_core(iso, force, push, phase)
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        with _job_lock:
            _job.update(running=False, done=True, phase="", result=res)

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "running": True, "date": iso}


def gen_status():
    with _job_lock:
        return {"running": _job["running"], "done": _job["done"],
                "phase": _job["phase"], "date": _job["date"], "result": _job["result"]}


def rebuild_index():
    import glob
    days = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(CONTENT, "*.json"))
                  if os.path.basename(f) != "index.json")
    json.dump({"days": days}, open(os.path.join(CONTENT, "index.json"), "w"), indent=1)


def git_publish(iso):
    def git(*args):
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
    try:
        git("add", "content/", "loved.json", "used_illustrations.json")
        c = git("-c", "user.name=Kris Salta", "-c", "user.email=johns@mercola.com",
                "commit", "-m", f"Daily Manna: articles for {iso}")
        if c.returncode != 0 and "nothing to commit" not in (c.stdout + c.stderr):
            return False
        return git("push").returncode == 0
    except Exception:
        return False


# ----------------------------- HTTP -----------------------------
class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client hung up (e.g. long request abandoned) — harmless

    def do_OPTIONS(self):
        try:
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            return json.loads(self.rfile.read(n) or "{}")
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/ping":
            return self._send(200, json.dumps({"ok": True, "canGenerate": True,
                                               "gemini": bool(_secret("GEMINI_API_KEY"))}))
        if path == "/api/loved":
            return self._send(200, json.dumps({"loved": load_loved()}))
        if path == "/api/gen-status":
            return self._send(200, json.dumps(gen_status()))
        # static files from ROOT
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(ROOT, rel))
        if not full.startswith(ROOT) or not os.path.isfile(full):
            return self._send(404, "not found", "text/plain")
        ctype = STATIC_TYPES.get(os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/generate":
            body = self._json_body()
            res = start_generation(body.get("date"), bool(body.get("force")),
                                   push=body.get("push", True))
            return self._send(200, json.dumps(res))
        if path == "/api/love":
            body = self._json_body()
            key, loved = body.get("key"), bool(body.get("loved"))
            keys = set(load_loved())
            keys.add(key) if loved else keys.discard(key)
            saved = save_loved(keys)
            git_publish(today_iso())            # sync loved.json down to all devices
            return self._send(200, json.dumps({"ok": True, "loved": saved}))
        self._send(404, "not found", "text/plain")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if not shutil.which("claude"):
        print("WARNING: 'claude' CLI not found on PATH — generation will fail.")
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        print(f"Daily Manna Studio already running on {PORT}? ({e})")
        raise SystemExit(0)
    print(f"Daily Manna Studio -> http://localhost:{PORT}  (model: {CLAUDE_MODEL})")
    srv.serve_forever()
