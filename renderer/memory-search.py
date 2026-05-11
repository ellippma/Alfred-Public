#!/usr/bin/env python3
"""
Alfred memory search — grep across people/, projects/, companies/, history/, and last_brief.md
Usage: python3 memory-search.py "query terms" [--since YYYY-MM-DD] [--until YYYY-MM-DD]

Returns: ranked plain-text results grouped by file, with dated signal log entries.
"""
import sys
import re
import json
from pathlib import Path
from datetime import datetime, date, timedelta
import calendar as cal_mod
import argparse

# ── config ────────────────────────────────────────────────────────────────────

def _resolve_memory_dir():
    cfg = Path.home() / ".alfred-config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
            p = data.get("paths", {}).get("memory_dir")
            if p:
                return Path(p)
        except Exception:
            pass
    return Path.home() / ".claude" / "projects" / f"-Users-{Path.home().name}" / "memory"

MEMORY_DIR = _resolve_memory_dir()

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# ── date parsing ──────────────────────────────────────────────────────────────

def _parse_date_bounds(terms):
    """Extract (since, until) bounds from query terms. Returns (None, None) if no date signal."""
    today = date.today()
    joined = " ".join(terms).lower()

    if "last week" in joined:
        monday = today - timedelta(days=today.weekday() + 7)
        return monday, monday + timedelta(days=6)
    if "this week" in joined:
        monday = today - timedelta(days=today.weekday())
        return monday, today
    if "yesterday" in joined:
        d = today - timedelta(days=1)
        return d, d
    if "today" in joined:
        return today, today

    for name, month_num in MONTH_NAMES.items():
        if name in joined:
            year = today.year if month_num <= today.month else today.year - 1
            last_day = cal_mod.monthrange(year, month_num)[1]
            return date(year, month_num, 1), date(year, month_num, last_day)

    return None, None

def _entry_date(line):
    """Parse YYYY-MM-DD from a signal log date heading like '### 2026-05-08'."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    return None

# ── frontmatter parsing ───────────────────────────────────────────────────────

def _parse_frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    result = {}
    for line in text[3:end].strip().split("\n"):
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        result[key.strip()] = val.strip().strip("\"'")
    return result

# ── search logic ──────────────────────────────────────────────────────────────

def _score_and_extract(path, terms, since, until):
    """
    Search a single .md file. Returns (score, display_name, hits) or None if no match.
    hits = list of (date_str, line) tuples.
    """
    try:
        text = path.read_text()
    except Exception:
        return None

    fm = _parse_frontmatter(text)
    display_name = fm.get("name") or path.stem
    score = 0
    hits = []

    lowered_terms = [t.lower() for t in terms if t.lower() not in MONTH_NAMES and t.lower() not in ("last","this","week","yesterday","today")]
    if not lowered_terms:
        lowered_terms = [t.lower() for t in terms]

    # Frontmatter field matches (high weight — name, role, domain, watch_keywords)
    fm_text = " ".join(str(v) for v in fm.values()).lower()
    for term in lowered_terms:
        if term in fm_text:
            score += 3

    # Scan signal log for dated entries
    lines = text.split("\n")
    current_date = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            d = _entry_date(stripped)
            if d:
                current_date = d
            continue

        if not stripped.startswith("- ["):
            continue

        line_lower = stripped.lower()
        match_count = sum(1 for t in lowered_terms if t in line_lower)
        if match_count == 0:
            continue

        # Date filter
        if since and current_date and current_date < since:
            continue
        if until and current_date and current_date > until:
            continue

        score += match_count
        date_str = current_date.strftime("%Y-%m-%d") if current_date else "unknown"
        hits.append((date_str, stripped))

    # Also scan Open commitments section (undated)
    in_commitments = False
    for line in lines:
        stripped = line.strip()
        if "## Open commitments" in stripped:
            in_commitments = True
            continue
        if in_commitments and stripped.startswith("## "):
            in_commitments = False
            continue
        if in_commitments and stripped.startswith("- ["):
            line_lower = stripped.lower()
            match_count = sum(1 for t in lowered_terms if t in line_lower)
            if match_count > 0:
                score += match_count
                hits.append(("commitment", stripped))

    if score == 0:
        return None

    # Sort hits by date descending (most recent first), commitments last
    def sort_key(h):
        if h[0] == "commitment":
            return "0000-00-00"
        return h[0]

    hits.sort(key=lambda h: sort_key(h), reverse=True)
    return (score, display_name, path, hits[:8])  # cap at 8 hits per file

# ── main ──────────────────────────────────────────────────────────────────────

def search(query, since=None, until=None, max_results=10):
    terms = query.split()
    if not terms:
        return "No query provided."

    # Auto-detect date bounds from query if not explicit
    if since is None and until is None:
        since, until = _parse_date_bounds(terms)

    scopes = [
        MEMORY_DIR / "people",
        MEMORY_DIR / "projects",
        MEMORY_DIR / "companies",
        MEMORY_DIR / "history",
        MEMORY_DIR / "last_brief.md",
    ]

    results = []
    for scope in scopes:
        if not scope.exists():
            continue
        if scope.is_file():
            r = _score_and_extract(scope, terms, since, until)
            if r:
                results.append(r)
        else:
            for f in sorted(scope.glob("*.md")):
                if f.stem == "_template":
                    continue
                r = _score_and_extract(f, terms, since, until)
                if r:
                    results.append(r)

    if not results:
        date_note = ""
        if since:
            date_note = f" (searched {since} → {until or 'today'})"
        return f"No memory matches found for: {query}{date_note}"

    results.sort(key=lambda r: r[0], reverse=True)
    results = results[:max_results]

    lines = []
    if since:
        lines.append(f"[search: \"{query}\" | period: {since} → {until or 'today'}]")
    else:
        lines.append(f"[search: \"{query}\"]")
    lines.append("")

    for score, display_name, path, hits in results:
        rel = path.relative_to(MEMORY_DIR)
        lines.append(f"=== {display_name} ({rel}) ===")
        for date_str, hit in hits:
            prefix = f"[{date_str}] " if date_str != "commitment" else "[open commitment] "
            lines.append(f"  {prefix}{hit}")
        lines.append("")

    return "\n".join(lines).rstrip()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alfred memory search")
    parser.add_argument("query", nargs="+", help="Search terms")
    parser.add_argument("--since", help="Start date YYYY-MM-DD")
    parser.add_argument("--until", help="End date YYYY-MM-DD")
    args = parser.parse_args()

    query_str = " ".join(args.query)
    since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None
    until = datetime.strptime(args.until, "%Y-%m-%d").date() if args.until else None

    print(search(query_str, since=since, until=until))
