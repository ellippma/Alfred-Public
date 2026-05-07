#!/usr/bin/env python3
"""
read-notepad.py
Reads alfred-notepad-v3 from Chrome's localStorage LevelDB and prints
a plain-text representation. Called by Alfred at brief time.

Data structure (JSON):
  {
    "checklist": [{"text": "...", "done": false}, ...],
    "stickies":  ["sticky text", ...],
    "completed": {"week": "YYYY-Www", "items": ["done text", ...]}
  }

Outputs nothing (exits 0) if Chrome's DB is locked, notepad is empty,
or plyvel cannot be installed.
"""
import json, os, sys, subprocess
from pathlib import Path

NP_KEY  = "alfred-notepad-v3"
DB_PATH = Path.home() / "Library/Application Support/Google/Chrome/Default/Local Storage/leveldb"


def ensure_plyvel():
    try:
        import plyvel
        return plyvel
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "plyvel", "-q"],
                       capture_output=True)
        try:
            import plyvel
            return plyvel
        except Exception:
            return None


def read_key(db, target_key):
    """Scan all keys for one containing target_key; return decoded value or None."""
    for raw_key, raw_val in db:
        try:
            key_str = raw_key.decode("utf-16-le", errors="ignore")
        except Exception:
            key_str = raw_key.decode("latin-1", errors="ignore")
        if target_key in key_str:
            if raw_val and len(raw_val) > 1:
                for enc in ("utf-8", "utf-16-le", "latin-1"):
                    try:
                        return raw_val[1:].decode(enc)
                    except Exception:
                        continue
    return None


def main():
    plyvel = ensure_plyvel()
    if plyvel is None:
        sys.exit(0)

    try:
        db = plyvel.DB(str(DB_PATH), create_if_missing=False)
    except Exception:
        sys.exit(0)  # DB locked or missing — skip silently

    try:
        raw = read_key(db, NP_KEY)
    finally:
        try:
            db.close()
        except Exception:
            pass

    if not raw:
        sys.exit(0)

    try:
        data = json.loads(raw)
    except Exception:
        sys.exit(0)

    lines = []

    # Unchecked checklist items — these are the open work items Alfred cares about
    checklist = data.get("checklist", [])
    for item in checklist:
        text = (item.get("text") or "").strip()
        if text:
            lines.append(f"[ ] {text}")

    # Completed items this week — informational
    completed = data.get("completed", {})
    done_items = completed.get("items", [])
    for text in done_items:
        text = (text or "").strip()
        if text:
            lines.append(f"[x] {text}")

    # Sticky notes — free-form context
    stickies = data.get("stickies", [])
    sticky_lines = [s.strip() for s in stickies if isinstance(s, str) and s.strip()]
    if sticky_lines:
        if lines:
            lines.append("")
        lines.append("--- Sticky notes ---")
        lines.extend(sticky_lines)

    if lines:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
