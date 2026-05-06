#!/usr/bin/env python3
"""
read-notepad.py
Reads alfred-notepad-v2 from Chrome's localStorage LevelDB and prints
a plain-text representation. Called by Alfred at brief time.

Outputs nothing (exits 0) if Chrome's DB is locked or notepad is empty.
"""
import os, sys, re, subprocess
from pathlib import Path

NP_KEY   = "alfred-notepad-v2"
NP_DONE  = "alfred-notepad-done-v2"
DB_PATH  = Path.home() / "Library/Application Support/Google/Chrome/Default/Local Storage/leveldb"

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
            # Chrome encodes keys as UTF-16LE with a 1-byte type prefix on values
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

def strip_html(html):
    """Very light HTML→text: strip tags, decode entities."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</(?:div|p|li|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") \
               .replace("&nbsp;", " ").replace("&#8203;", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def html_to_lines(html):
    """Parse notepad HTML into readable lines, preserving check/bullet structure."""
    lines = []

    # Checklist items
    for m in re.finditer(r'<div class="np-check-item"[^>]*>(.*?)</div>', html,
                         re.S | re.I):
        checked = 'checked' in m.group(1)
        text    = strip_html(m.group(1)).replace("\n", " ").strip()
        if text:
            lines.append(f"{'[x]' if checked else '[ ]'} {text}")

    # Bullet items
    for m in re.finditer(r'<div class="np-bullet-item"[^>]*>(.*?)</div>', html,
                         re.S | re.I):
        text = strip_html(m.group(1)).replace("\n", " ").strip()
        if text:
            lines.append(f"• {text}")

    # Tables
    for tbl in re.finditer(r'<table[^>]*>(.*?)</table>', html, re.S | re.I):
        for row in re.finditer(r'<tr[^>]*>(.*?)</tr>', tbl.group(1), re.S | re.I):
            cells = [strip_html(td).strip()
                     for td in re.findall(r'<td[^>]*>(.*?)</td>',
                                          row.group(1), re.S | re.I)]
            if any(cells):
                lines.append(" | ".join(cells))

    # Remaining free text (strip structured blocks first)
    free = re.sub(r'<div class="np-(check|bullet)-item"[^>]*>.*?</div>', "",
                  html, flags=re.S | re.I)
    free = re.sub(r'<table[^>]*>.*?</table>', "", free, flags=re.S | re.I)
    for line in strip_html(free).splitlines():
        line = line.strip()
        if line:
            lines.append(line)

    return lines

def main():
    plyvel = ensure_plyvel()
    if plyvel is None:
        sys.exit(0)

    try:
        db = plyvel.DB(str(DB_PATH), create_if_missing=False)
    except Exception:
        sys.exit(0)  # DB locked or missing — skip silently

    try:
        np_html  = read_key(db, NP_KEY)
        done_raw = read_key(db, NP_DONE)
    finally:
        try:
            db.close()
        except Exception:
            pass

    if not np_html:
        sys.exit(0)

    lines = html_to_lines(np_html)

    # Completed items from done key
    if done_raw:
        import json
        try:
            done_data = json.loads(done_raw)
            done_items = done_data.get("items", [])
            if done_items:
                lines.append("")
                lines.append("--- Completed this week ---")
                for it in done_items:
                    lines.append(f"[done] {it.get('text','')}")
        except Exception:
            pass

    print("\n".join(lines))

if __name__ == "__main__":
    main()
