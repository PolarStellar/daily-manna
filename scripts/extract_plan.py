"""One-time extraction of the SCC Bible Reading Plan PDF into plan.json.

pypdf visitor_text emits one fragment per character with (x, y). We rebuild
text lines from chars, split each line into cell-runs at large x gaps
(column gutters), cluster run x-starts into the 5 table columns, and assign
wrapped lines to the nearest day row by y — because layout-mode text puts
some cell wraps above the day-number line and some below.

Output: plan.json mapping "MM-DD" -> {psalm, ot, nt, prov}.
"""
import json
import re
import sys
from collections import defaultdict
from pypdf import PdfReader

PDF = "/Users/johnkristoffersalta/Library/Mobile Documents/com~apple~CloudDocs/Documents/KRIS/SCC Bible Reading Plan (Full Bible In A Year).pdf"

MONTHS = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}
DAYS_IN_MONTH = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
FIELDS = ("psalm", "ot", "nt", "prov")
GUTTER = 20  # x gap that separates table columns (word gaps are < 12)


def get_runs(page):
    """Return list of (y, x_start, text) cell-runs."""
    chars = []

    def visit(text, cm, tm, font_dict, font_size):
        if text:
            chars.append((round(tm[5], 1), tm[4], text))

    page.extract_text(visitor_text=visit)

    lines = defaultdict(list)
    for y, x, t in chars:
        lines[y].append((x, t))

    runs = []
    for y, items in lines.items():
        items.sort()
        cur_x, cur_text, last_x = None, "", None
        for x, t in items:
            if cur_x is None:
                cur_x, cur_text = x, t
            elif x - last_x > GUTTER:
                if cur_text.strip():
                    runs.append((y, cur_x, cur_text.strip()))
                cur_x, cur_text = x, t
            else:
                cur_text += t
            last_x = x
        if cur_text.strip():
            runs.append((y, cur_x, cur_text.strip()))
    return runs


def parse_page(page):
    runs = get_runs(page)
    month = None
    for _, _, t in runs:
        if t.strip() in MONTHS:
            month = MONTHS[t.strip()]
    assert month, "month not found"

    # data runs only: drop title/header rows (identified by their text)
    drop = {"Day", "Psalm", "Old Testament", "New Testament", "Proverbs",
            "SCC Bible Reading Plan (Full Bible In A Year)",
            "SOLIDGROUND CHRISTIAN CHURCH", "BIBLE READING PLAN FOR ONE YEAR"}
    data = [r for r in runs if r[2] not in drop and r[2].strip() not in MONTHS]

    # cluster x-starts into 5 columns: sort unique starts, split at gaps > 25
    xs = sorted({round(x) for _, x, _ in data})
    cols, cur = [], [xs[0]]
    for a, b in zip(xs, xs[1:]):
        if b - a > 25:
            cols.append(cur)
            cur = []
        cur.append(b)
    cols.append(cur)
    assert len(cols) == 5, f"month {month}: got {len(cols)} column clusters: {cols}"
    edges = [(cols[i][-1] + cols[i + 1][0]) / 2 for i in range(4)]

    def col_of(x):
        for i, e in enumerate(edges):
            if x < e:
                return i
        return 4

    # day rows: digit-only run in column 0
    day_rows = sorted((y, int(t)) for y, x, t in data if col_of(x) == 0 and t.isdigit())
    days_seq = [d for _, d in day_rows]
    assert days_seq == sorted(days_seq), f"month {month}: days out of order"
    ys = [y for y, _ in day_rows]
    spacings = [b - a for a, b in zip(ys, ys[1:])]
    max_off = min(spacings) * 0.6

    def row_of(y):
        best, bd = None, 1e9
        for i, ry in enumerate(ys):
            d = abs(ry - y)
            if d < bd:
                best, bd = i, d
        return best if bd <= max_off else None

    cells = {d: {f: [] for f in FIELDS} for _, d in day_rows}
    orphans = []
    for y, x, t in data:
        c = col_of(x)
        if c == 0:
            continue
        r = row_of(y)
        if r is None:
            orphans.append((y, x, t))
            continue
        cells[day_rows[r][1]][FIELDS[c - 1]].append((y, x, t, "on"))

    # Resolve orphans (wrapped cell lines beyond the nearest-row threshold).
    # y grows downward here. An orphan is either the HEAD of the cell one
    # text-line below it, or the TAIL of the cell one line above. Decide by
    # text grammar: a cell starting mid-reference (digits) needs a head; a
    # cell ending in a dangling book name needs a tail.
    line_h = 45  # one wrapped text line is ~37 units on these pages
    for y, x, t in sorted(orphans):
        c = col_of(x)
        head_day = next((d for ry, d in day_rows if y < ry <= y + line_h), None)
        tail_day = next((d for ry, d in day_rows if y - line_h <= ry < y), None)
        target = None
        if head_day is not None:
            existing = sorted(cells[head_day][FIELDS[c - 1]])
            first = existing[0][2] if existing else ""
            # head if the cell below starts mid-reference, or the orphan
            # itself ends dangling (separator or bare book name)
            if re.match(r"^\d", first) or re.search(r"[;,]\s*$|[A-Za-z]$", t.strip()):
                target, pos = head_day, "head"
        if target is None and tail_day is not None:
            existing = sorted(cells[tail_day][FIELDS[c - 1]])
            last = existing[-1][2] if existing else ""
            if re.search(r"[;,]\s*$|[A-Za-z]$", last.strip()):
                target, pos = tail_day, "tail"
        assert target is not None, f"month {month}: unresolvable orphan {(y, x, t)}"
        cells[target][FIELDS[c - 1]].append((y, x, t, pos))

    rows = {}
    for day, fields in cells.items():
        rows[day] = {}
        for k, parts in fields.items():
            parts.sort()  # y ascending = top-to-bottom on these pages, then x
            joined = " ".join(p[2] for p in parts)
            rows[day][k] = re.sub(r"\s+", " ", joined).strip()
    return month, rows


def main():
    r = PdfReader(PDF)
    plan = {}
    for page in r.pages:
        month, rows = parse_page(page)
        expected = DAYS_IN_MONTH[month]
        extra = [d for d in sorted(rows) if d > expected]
        if extra:
            print(f"note month {month}: dropping extra rows {extra} (PDF spillover)", file=sys.stderr)
        missing = [d for d in range(1, expected + 1) if d not in rows]
        if missing:
            print(f"WARN month {month}: missing days {missing}", file=sys.stderr)
        for day, v in rows.items():
            if day <= expected:
                plan[f"{month:02d}-{day:02d}"] = v

    empties = [(k, f) for k, v in plan.items() for f, val in v.items() if not val]
    if empties:
        print(f"WARN empty cells: {empties[:20]}", file=sys.stderr)
    print(f"{len(plan)} days extracted", file=sys.stderr)
    with open("plan.json", "w") as f:
        json.dump(plan, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
