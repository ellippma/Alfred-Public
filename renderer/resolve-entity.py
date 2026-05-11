#!/usr/bin/env python3
"""
Alfred entity resolver — maps a raw name/alias to a canonical person node.
Usage: python3 resolve-entity.py "Dave"  → JSON result
       python3 resolve-entity.py "J. Smith" --score-title "VP of Sales"  → score + node suggestion

Exit codes: 0 = found in memory, 1 = not found (caller should do Slack lookup), 2 = error
"""
import sys
import re
import json
from pathlib import Path

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

# Title keywords → priority tier
TITLE_PRIORITY = [
    (["ceo", "cro", "cmo", "cfo", "cto", "coo", "cpo", "chief"], "always-respond"),
    (["svp", "evp", "senior vice president", "executive vice president"], "always-respond"),
    (["vp", "vice president"], "always-respond"),
    (["sr. director", "senior director", "sr director"], "director-plus"),
    (["director"], "director-plus"),
    (["sr. manager", "senior manager", "sr manager", "manager"], "team"),
]

# ── frontmatter parser ────────────────────────────────────────────────────────

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
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            result[key] = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
        else:
            result[key] = val.strip("\"'")
    return result

# ── alias index ───────────────────────────────────────────────────────────────

def _build_alias_index():
    """Returns dict: lowercase_alias → {slug, name, role, priority, email}"""
    index = {}
    people_dir = MEMORY_DIR / "people"
    if not people_dir.exists():
        return index

    for f in people_dir.glob("*.md"):
        if f.stem == "_template":
            continue
        try:
            fm = _parse_frontmatter(f.read_text())
        except Exception:
            continue

        canonical_name = fm.get("name", f.stem)
        entry = {
            "slug": f.stem,
            "name": canonical_name,
            "role": fm.get("role", ""),
            "priority": fm.get("priority", ""),
            "email": fm.get("email", ""),
            "source": "memory",
        }

        # Index canonical name and each part
        for token in [canonical_name] + canonical_name.split():
            index[token.lower()] = entry

        # Index explicit aliases
        for alias in fm.get("aliases", []):
            index[alias.lower().strip()] = entry

    return index

# ── title scorer ──────────────────────────────────────────────────────────────

def score_title(title):
    """Returns priority tier string or None if below threshold."""
    t = title.lower()
    for keywords, priority in TITLE_PRIORITY:
        if any(k in t for k in keywords):
            return priority
    return None

# ── name normalizer ───────────────────────────────────────────────────────────

def _normalize(name):
    """Remove punctuation, lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[.,]", "", name)).strip().lower()

# ── resolver ──────────────────────────────────────────────────────────────────

def resolve(name, index=None):
    """
    Resolve a name to a person node entry.
    Returns dict with found=True/False.
    """
    if index is None:
        index = _build_alias_index()

    norm = _normalize(name)

    # Exact alias match
    if norm in index:
        result = dict(index[norm])
        result["found"] = True
        result["matched_as"] = name
        return result

    # Try last name only (e.g. "Carlson" → dc)
    parts = norm.split()
    if len(parts) > 1:
        for part in parts:
            if part in index:
                result = dict(index[part])
                result["found"] = True
                result["matched_as"] = name
                return result

    # Initials match (e.g. "J.S." or "J. S.")
    initials = "".join(p[0] for p in parts if p)
    if len(initials) >= 2 and initials in index:
        result = dict(index[initials])
        result["found"] = True
        result["matched_as"] = name
        return result

    return {"found": False, "input": name}


def suggest_node(name, slack_title, slack_email=""):
    """
    Given a name + Slack title, suggest a new person node spec.
    Returns dict with priority tier and whether to create a node.
    """
    priority = score_title(slack_title)
    if priority is None:
        return {"create": False, "reason": f"Title '{slack_title}' below Director threshold"}

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return {
        "create": True,
        "slug": slug,
        "name": name,
        "role": slack_title,
        "priority": priority,
        "email": slack_email,
        "tone": "",
        "aliases": [],
        "source": "slack-bootstrap",
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Alfred entity resolver")
    parser.add_argument("name", nargs="+", help="Name or alias to resolve")
    parser.add_argument("--score-title", dest="slack_title", help="Slack title to score for new node suggestion")
    parser.add_argument("--email", default="", help="Slack email for new node suggestion")
    args = parser.parse_args()

    name_str = " ".join(args.name)
    index = _build_alias_index()
    result = resolve(name_str, index)

    if not result["found"] and args.slack_title:
        suggestion = suggest_node(name_str, args.slack_title, args.email)
        result["suggestion"] = suggestion

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["found"] else 1)
