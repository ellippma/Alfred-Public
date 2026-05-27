#!/usr/bin/env python3
"""
alfred-build.py
Reads alfred-data.json → fills alfred-template.html → writes alfred-brief-YYYY-MM-DD.html
Usage: python3 alfred-build.py  (run from your briefs directory, or set ALFRED_BRIEFS_DIR)
"""

import json, os, sys
from pathlib import Path
from datetime import datetime

def _resolve_briefs_dir():
    # 1. Env var override
    if "ALFRED_BRIEFS_DIR" in os.environ:
        return Path(os.environ["ALFRED_BRIEFS_DIR"])
    # 2. ~/.alfred-config.json written by setup wizard
    cfg = Path.home() / ".alfred-config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
            p = data.get("paths", {}).get("briefs_dir")
            if p:
                return Path(p)
        except Exception:
            pass
    # 3. Default — same directory as this script
    return Path(__file__).parent


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

BRIEFS_DIR   = _resolve_briefs_dir()
TEMPLATE     = BRIEFS_DIR / "alfred-template.html"
DATA_FILE    = BRIEFS_DIR / "alfred-data.json"

# ── style maps ───────────────────────────────────────────────────────────────

PILL_CLASS = {
    "red": "pill-red", "yellow": "pill-yellow",
    "green": "pill-green", "blue": "pill-blue", "gray": "pill-gray",
}
STATUS_MAP = {
    "done":        ("pill-green",  "DONE"),
    "shipped":     ("pill-green",  "SHIPPED"),
    "in_progress": ("pill-blue",   "IN PROGRESS"),
    "overdue":     ("pill-red",    "OVERDUE"),
    "at_risk":     ("pill-yellow", "AT-RISK"),
    "stalled":     ("pill-red",    "STALLED"),
    "blocked":     ("pill-yellow", "BLOCKED"),
    "no_signal":   ("pill-yellow", "NO SIGNAL"),
}
SOURCE_ICONS = {"ok": "✅", "warn": "⚠️", "error": "❌"}
SOURCE_NAMES = {
    "calendar": "📅 Calendar", "slack": "💬 Slack",
    "drive": "📁 Drive", "gmail": "📧 Gmail", "granola": "🎙️ Granola",
}
SIGNAL_ICONS = {"win": "🟢", "strategy": "🔵", "gap": "🟡"}
MILESTONE_STATUS_MAP = {
    "on_track":  ("milestone-on-track",  "ON TRACK"),
    "at_risk":   ("milestone-at-risk",   "AT RISK"),
    "stalled":   ("milestone-stalled",   "STALLED"),
    "complete":  ("milestone-complete",  "COMPLETE"),
    "cancelled": ("milestone-cancelled", "CANCELLED"),
    "active":    ("milestone-on-track",  "ACTIVE"),
}

# ── helpers ───────────────────────────────────────────────────────────────────

def esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def pill(text, cls):
    return f'<span class="pill {cls}">{esc(text)}</span>'

# ── section renderers ─────────────────────────────────────────────────────────

def r_data_status(sources):
    parts = []
    for key, name in SOURCE_NAMES.items():
        icon = SOURCE_ICONS.get(sources.get(key, "ok"), "✅")
        note = sources.get(f"{key}_note", "")
        label = f"{name} {icon}" + (f" {note}" if note else "")
        parts.append(f"<span>{label}</span>")
    return "\n    ".join(parts)

def r_fires(fires, resolved):
    html = ""
    for f in resolved:
        html += f'<div class="resolved-card"><strong>✅ RESOLVED — {esc(f.get("title",""))}</strong> — {esc(f.get("note",""))}</div>\n'
    for f in fires:
        link = f' <a href="{f["slack_url"]}" target="_blank">Open thread →</a>' if f.get("slack_url") else ""
        html += (
            f'<div class="fire-card">'
            f'<div class="fire-title">{esc(f.get("title",""))}</div>'
            f'<div class="fire-body">{esc(f.get("body",""))}{link}</div>'
            f'<div class="first-move"><strong>First move:</strong> {esc(f.get("first_move",""))}</div>'
            f'</div>\n'
        )
    return html or "<p style='color:#6e6e73;font-size:13px'>No fires. Good morning.</p>"

def r_prep_card(prep, eid):
    """Render the hidden prep card row for a calendar event."""
    lm = prep.get("last_meeting") or {}
    if lm:
        lm_html = (
            f'<div class="prep-meeting-meta">{esc(lm.get("date",""))} · {esc(lm.get("title",""))}</div>'
            f'<div class="prep-meeting-summary">{esc(lm.get("summary",""))}</div>'
        )
    else:
        lm_html = '<div class="prep-empty">No prior meeting on record</div>'

    items = prep.get("open_items") or []
    if items:
        items_html = ""
        for item in items:
            tag     = item.get("tag", "you")
            who     = item.get("who") or ("YOU" if tag == "you" else "THEM")
            tag_cls = "tag-you" if tag == "you" else "tag-them"
            items_html += (
                f'<div class="prep-item">'
                f'<span class="prep-item-tag {tag_cls}">{esc(who.upper())}</span>'
                f'{esc(item.get("text",""))}'
                f'</div>'
            )
    else:
        items_html = '<div class="prep-empty">No tracked open items</div>'

    signals = prep.get("signals") or []
    if signals:
        sigs_html = "".join(
            f'<div class="prep-signal">'
            f'<div class="prep-signal-who">{esc(s.get("who",""))}</div>'
            f'<div class="prep-signal-text">{esc(s.get("text",""))}</div>'
            f'</div>'
            for s in signals[:3]
        )
    else:
        sigs_html = '<div class="prep-empty">No recent signals</div>'

    return (
        f'<tr class="prep-row"><td colspan="3">'
        f'<div class="prep-card" id="prep-{eid}">'
        f'<div class="prep-inner">'
        f'<div class="prep-col"><div class="prep-col-label"><span>📅</span> LAST MEETING</div>{lm_html}</div>'
        f'<div class="prep-col"><div class="prep-col-label"><span>📌</span> OPEN ITEMS</div>{items_html}</div>'
        f'<div class="prep-col"><div class="prep-col-label"><span>💬</span> RECENT SIGNALS</div>{sigs_html}</div>'
        f'</div></div>'
        f'</td></tr>\n'
    )


def r_calendar_rows(events):
    html = ""
    for idx, e in enumerate(events):
        eid      = f"cal{idx}"
        done     = e.get("done", False)
        conflict = e.get("conflict", False)
        priority = e.get("priority", False)
        prep     = e.get("prep")
        row_cls  = ' class="done-row"' if done else ""
        name_cls = ' class="meeting-name"' if done else ""
        col_cls  = ' class="conflict"' if conflict else ""
        time_str = esc(e.get("time","")) + (" ⚠️" if conflict else "")
        title    = f"<strong>{esc(e.get('title',''))}</strong>" if priority else esc(e.get("title",""))
        note_cls = " green" if done else ""
        note_html = f'<div class="note{note_cls}">{esc(e["note"])}</div>' if e.get("note") else ""
        prep_btn  = (
            f'<button class="prep-toggle" data-eid="{eid}" onclick="togglePrep(\'{eid}\')">📋 PREP ▾</button>'
        ) if prep else ""
        html += (
            f"<tr{row_cls}>"
            f"<td class='time'>{time_str}</td>"
            f"<td{col_cls}><span{name_cls}>{title}</span></td>"
            f"<td>{note_html}{prep_btn}</td>"
            f"</tr>\n"
        )
        if prep:
            html += r_prep_card(prep, eid)
    return html

def r_calendar_notices(notices):
    return "\n".join(f"<span>{esc(n)}</span>" for n in notices)

def r_list_items(items):
    html = ""
    for item in items:
        prefix = ""
        if item.get("pill") and item.get("pill_color"):
            prefix = pill(item["pill"], PILL_CLASS.get(item["pill_color"], "pill-gray")) + " "
        html += f"<li>{prefix}{esc(item.get('text',''))}</li>\n"
    return html

def r_priority_threads(threads):
    html = ""
    for t in threads:
        drafted  = '<div class="drafted">✏️ Draft ready in Slack</div>' if t.get("drafted") else ""
        link_btn = f'<a href="{t["slack_url"]}" target="_blank">Open in Slack →</a>' if t.get("slack_url") else ""
        html += (
            f'<div class="thread-item">'
            f'<div class="thread-body"><strong>{esc(t.get("title",""))}</strong> — {esc(t.get("body",""))}{drafted}</div>'
            f'<div class="thread-link">{link_btn}</div>'
            f'</div>\n'
        )
    return html

def r_team_commitments(people):
    html = ""
    for person in people:
        items_html = ""
        for item in person.get("items", []):
            cls, label = STATUS_MAP.get(item.get("status",""), ("pill-gray", item.get("status","").upper()))
            note = f' — {esc(item.get("note",""))}' if item.get("note") else ""
            items_html += f'<div class="team-item">{pill(label, cls)} {esc(item.get("text",""))}{note}</div>\n'
        html += (
            f'<div class="team-person">'
            f'<div class="person-name">{esc(person.get("person",""))}</div>'
            f'{items_html}</div>\n'
        )
    return html

def r_drive_mentions(mentions):
    html = ""
    for m in mentions:
        html += (
            f'<div class="drive-item">'
            f'<div class="doc-title"><a href="{m.get("url","#")}" target="_blank">{esc(m.get("title",""))}</a></div>'
            f'<div class="doc-meta">Owner: {esc(m.get("owner",""))} · {esc(m.get("note",""))}</div>'
            f'</div>\n'
        )
    return html

def r_yesterday_recap(recap):
    if not recap:
        return None, None, None  # hidden
    date_display = esc(recap.get("date_display", ""))
    groups = [
        ("Meetings",             recap.get("meetings_done",       [])),
        ("Key decisions",        recap.get("decisions",           [])),
        ("Commitments given",    recap.get("commits_given",       [])),
        ("Commitments received", recap.get("commits_received",    [])),
        ("Highlights",           recap.get("highlights",          [])),
    ]
    html = ""
    for label, items in groups:
        if not items:
            continue
        lis = "\n".join(f"<li>{esc(item)}</li>" for item in items)
        html += (
            f'<div class="yesterday-group">'
            f'<span class="yesterday-label">{label}</span>'
            f'<ul class="yesterday-list">{lis}</ul>'
            f'</div>\n'
        )
    if not html:
        return None, None, None  # nothing to show — hide section
    return date_display, html, ""  # third value = YESTERDAY_HIDDEN (empty = visible)


def r_delta(delta):
    if not delta:
        return "", 'style="display:none"'
    items = []
    for item in delta.get("new_fires", []):
        items.append(f'<li><span class="delta-tag delta-fire">🔥 NEW FIRE</span> {esc(item)}</li>')
    for item in delta.get("resolved", []):
        items.append(f'<li><span class="delta-tag delta-resolved">✅ RESOLVED</span> {esc(item)}</li>')
    for item in delta.get("status_changes", []):
        items.append(f'<li><span class="delta-tag delta-status">🔄 STATUS</span> {esc(item)}</li>')
    for item in delta.get("new_slipped", []):
        items.append(f'<li><span class="delta-tag delta-slip">⚠️ NOW SLIPPED</span> {esc(item)}</li>')
    for item in delta.get("other", []):
        if isinstance(item, dict):
            text = esc(item.get("text", ""))
            url  = item.get("url", "")
            link = (f' <a href="{esc(url)}" target="_blank" '
                    f'style="font-weight:700;color:var(--blue)">↗</a>') if url else ""
            items.append(f'<li><span class="delta-tag delta-other">📌 NOTE</span> {text}{link}</li>')
        else:
            items.append(f'<li><span class="delta-tag delta-other">📌 NOTE</span> {esc(item)}</li>')
    if not items:
        return "", 'style="display:none"'
    return "<ul>" + "\n".join(items) + "</ul>", ""


def r_milestones(milestones):
    if not milestones:
        return ""
    html = ""
    for m in milestones:
        cls, label = MILESTONE_STATUS_MAP.get(m.get("status", "active"), ("milestone-on-track", "ACTIVE"))
        target = f' <span class="milestone-date">→ {esc(m["target_date"])}</span>' if m.get("target_date") else ""
        summary = f'<div class="milestone-summary">{esc(m["summary"])}</div>' if m.get("summary") else ""
        signals_html = ""
        for s in m.get("signals", []):
            icon = SIGNAL_ICONS.get(s.get("type"), "⚪")
            link = f' <a href="{s["url"]}" target="_blank">View →</a>' if s.get("url") else ""
            src_badge = f'<span class="signal-src">{esc(s.get("source",""))}</span>' if s.get("source") else ""
            signals_html += (
                f'<div class="milestone-signal">'
                f'<span class="signal-icon-sm">{icon}</span>'
                f'{src_badge} {esc(s.get("text",""))}{link}'
                f'</div>\n'
            )
        html += (
            f'<div class="milestone-card">'
            f'<div class="milestone-hdr">'
            f'<span class="milestone-name">{esc(m.get("name",""))}</span>'
            f'<span class="milestone-badge {cls}">{label}</span>'
            f'{target}'
            f'</div>'
            f'{summary}'
            f'{"<div class=milestone-signals>" + signals_html + "</div>" if signals_html else ""}'
            f'</div>\n'
        )
    return html


def _check_update():
    """Returns (update_available: bool, latest_version: str, repo_dir: Path)."""
    try:
        cfg_path = Path.home() / ".alfred-config.json"
        installed = "0.0.0"
        repo_dir = Path.home() / "alfred-repo"
        if cfg_path.exists():
            d = json.loads(cfg_path.read_text())
            installed = d.get("version", "0.0.0")
            configured = d.get("paths", {}).get("repo_dir")
            if configured:
                repo_dir = Path(configured)
        repo_ver_path = repo_dir / "VERSION"
        if repo_ver_path.exists():
            latest = repo_ver_path.read_text().strip()
        else:
            latest = installed
        return latest != installed, latest, repo_dir
    except Exception:
        return False, "", Path.home() / "alfred-repo"


def _strftime(dt, fmt):
    """Cross-platform strftime — replaces %-d (macOS-only) with the unpadded day number."""
    return dt.strftime(fmt.replace("%-d", str(dt.day)))


def r_entities():
    """Read person + project + company nodes from memory/ and return JSON for ENTITIES_JSON slot."""
    memory_dir = _resolve_memory_dir()
    people, projects, companies = [], [], []

    def parse_fm(text):
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

    for subdir, dest, kind in [
        (memory_dir / "people",    people,    "person"),
        (memory_dir / "projects",  projects,  "project"),
        (memory_dir / "companies", companies, "company"),
    ]:
        if not subdir.exists():
            continue
        for f in sorted(subdir.glob("*.md")):
            try:
                fm = parse_fm(f.read_text())
                if kind == "person":
                    dest.append({
                        "slug": f.stem,
                        "name": fm.get("name", f.stem),
                        "role": fm.get("role", ""),
                        "priority": fm.get("priority", ""),
                        "tone": fm.get("tone", ""),
                    })
                elif kind == "project":
                    for field in ("watch_people", "watch_keywords", "watch_channels"):
                        v = fm.get(field, [])
                        if isinstance(v, str):
                            fm[field] = [x.strip() for x in v.split(",") if x.strip()]
                    dest.append({
                        "slug": f.stem,
                        "name": fm.get("name", f.stem),
                        "status": fm.get("status", "on_track"),
                        "target_date": fm.get("target_date", ""),
                        "watch_people": fm.get("watch_people", []),
                        "watch_keywords": fm.get("watch_keywords", []),
                        "watch_channels": fm.get("watch_channels", []),
                    })
                elif kind == "company":
                    if f.stem == "_template":
                        continue
                    for field in ("watch_keywords", "watch_channels", "key_contacts", "open_projects"):
                        v = fm.get(field, [])
                        if isinstance(v, str):
                            fm[field] = [x.strip() for x in v.split(",") if x.strip()]
                    dest.append({
                        "slug": f.stem,
                        "name": fm.get("name", f.stem),
                        "type": fm.get("type", "customer"),
                        "tier": fm.get("tier", ""),
                        "domain": fm.get("domain", ""),
                        "watch_keywords": fm.get("watch_keywords", []),
                        "watch_channels": fm.get("watch_channels", []),
                    })
            except Exception:
                pass

    people_lookup = {p["slug"]: p["name"] for p in people}
    return json.dumps({
        "people": people, "projects": projects, "companies": companies, "people_lookup": people_lookup
    }).replace("</", "<\\/")


def r_kanban_json(kanban):
    """Serialize kanban data for the template's kb-data script tag."""
    if not kanban:
        kanban = {}
    return json.dumps(kanban).replace("</", "<\\/")


def r_candidates():
    """Read pending-candidates.json from memory dir → (html, hidden_attr, json_str).

    Returns hidden if no candidates file exists or it has no proposals.
    """
    memory_dir = _resolve_memory_dir()
    candidates_file = memory_dir / "pending-candidates.json"

    if not candidates_file.exists():
        return "", 'style="display:none"', "[]"

    try:
        raw = json.loads(candidates_file.read_text())
        proposals = raw.get("proposals", [])
    except Exception:
        return "", 'style="display:none"', "[]"

    if not proposals:
        return "", 'style="display:none"', "[]"

    CONF_CLASS = {"high": "conf-high", "medium": "conf-med", "low": "conf-low"}
    CONF_LABEL = {"high": "HIGH", "medium": "MED", "low": "LOW"}
    TYPE_ICONS = {
        "new_person":   "👤",
        "new_project":  "🗂",
        "new_company":  "🏢",
        "pattern":      "🧠",
        "insight":      "💡",
        "stale":        "🗄",
        "tone_update":  "🎚",
    }

    count = len(proposals)
    html = (
        f'<div class="cand-header">'
        f'<span>{count} proposal{"s" if count != 1 else ""} from Alfred</span>'
        f'<button class="cand-approve-all" onclick="approveAll()">Approve All →</button>'
        f'</div>\n'
    )

    for p in proposals:
        pid      = esc(p.get("id", ""))
        icon     = TYPE_ICONS.get(p.get("type", ""), "📋")
        title    = esc(p.get("title", ""))
        subtitle = esc(p.get("subtitle", ""))
        conf     = p.get("confidence", "medium")
        conf_cls = CONF_CLASS.get(conf, "conf-med")
        conf_lbl = CONF_LABEL.get(conf, "MED")

        team_cb = (
            f'<label class="cand-team-label">'
            f'<input type="checkbox" id="cand-team-{pid}" style="width:14px;height:14px;accent-color:#0A0A0A;cursor:pointer">'
            f' Direct report / team member</label>'
        ) if p.get("type") == "new_person" else ""

        # Priority dropdown — only for new_person proposals so Ethan can set
        # importance (always-respond / director-plus / team / partner) before approving.
        # Alfred's suggested priority is pre-selected; user can override inline.
        PRIORITY_OPTIONS = [
            ("always-respond", "🔴 Always respond — C-suite / exec"),
            ("director-plus",  "🟡 Director+ — VP / Dir priority"),
            ("team",           "🟢 Team — direct report"),
            ("partner",        "⚪ Partner — peer / collaborator"),
        ]
        current_priority = p.get("data", {}).get("priority", "director-plus")
        if p.get("type") == "new_person":
            opts = "".join(
                f'<option value="{val}"{" selected" if val == current_priority else ""}>{label}</option>'
                for val, label in PRIORITY_OPTIONS
            )
            priority_dd = (
                f'<div style="display:flex;align-items:center;gap:8px;margin-top:6px">'
                f'<span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:#555;white-space:nowrap">Priority</span>'
                f'<select id="cand-priority-{pid}" style="font-family:\'Comic Neue\',cursive;font-size:12px;font-weight:700;border:2px solid #0A0A0A;padding:3px 6px;background:#fff;cursor:pointer">'
                f'{opts}'
                f'</select></div>'
            )
        else:
            priority_dd = ""

        current_type = esc(p.get("data", {}).get("type", "prospect"))
        co_type_dd = (
            f'<div style="display:flex;align-items:center;gap:8px;margin-top:6px">'
            f'<span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:#555;white-space:nowrap">Company type</span>'
            f'<select id="cand-cotype-{pid}" style="font-family:\'Comic Neue\',cursive;font-size:12px;font-weight:700;border:2px solid #0A0A0A;padding:3px 6px;background:#fff;cursor:pointer">'
            f'<option value="customer"{" selected" if current_type=="customer" else ""}>customer</option>'
            f'<option value="prospect"{" selected" if current_type=="prospect" else ""}>prospect</option>'
            f'<option value="partner"{" selected" if current_type=="partner" else ""}>partner</option>'
            f'<option value="vendor"{" selected" if current_type=="vendor" else ""}>vendor</option>'
            f'<option value="internal-team"{" selected" if current_type=="internal-team" else ""}>internal-team</option>'
            f'</select></div>'
        ) if p.get("type") == "new_company" else ""

        html += (
            f'<div class="cand-card" id="cand-{pid}" data-id="{pid}">'
            f'<div class="cand-left">'
            f'<span class="cand-icon">{icon}</span>'
            f'<div class="cand-text">'
            f'<div class="cand-title">{title}</div>'
            f'<div class="cand-subtitle">{subtitle}</div>'
            f'{team_cb}{priority_dd}{co_type_dd}'
            f'</div></div>'
            f'<div class="cand-right">'
            f'<span class="conf-badge {conf_cls}" title="Alfred\'s confidence this proposal should exist">CONF: {conf_lbl}</span>'
            f'<button class="cand-btn cand-approve" onclick="approveCandidate(\'{pid}\')">Approve ✓</button>'
            f'<button class="cand-btn cand-dismiss" onclick="dismissCandidate(\'{pid}\')">Dismiss ✕</button>'
            f'</div></div>\n'
        )

    html += (
        '<div class="cand-save-row" id="cand-save-row" style="display:none">'
        '<button class="cand-save-btn" onclick="saveCandidates()">SEND TO ALFRED ↓</button>'
        '<span class="cand-status" id="cand-status"></span>'
        '</div>'
    )

    json_str = json.dumps(proposals).replace("</", "<\\/")
    return html, "", json_str


# ── main ──────────────────────────────────────────────────────────────────────

def r_summary_bar(fires, rollout_days):
    """Compute sticky-bar slot values."""
    count = len(fires)
    if count == 0:
        fire_label = "✅ No fires"
        top_fire   = "Clean morning."
        state      = "state-clear"
    elif count == 1:
        fire_label = "🔥 1 fire"
        top_fire   = fires[0].get("title","")
        state      = "state-fire"
    else:
        fire_label = f"🔥 {count} fires"
        top_fire   = fires[0].get("title","")
        state      = "state-fire"
    return fire_label, top_fire, str(rollout_days), state


def build():
    try:
        with open(TEMPLATE) as f:
            tmpl = f.read()
    except FileNotFoundError:
        sys.exit(f"alfred-build: template not found: {TEMPLATE}\n"
                 f"  Make sure alfred-template.html is in your briefs directory ({BRIEFS_DIR}).\n"
                 f"  Re-run setup if it is missing: python3 ~/alfred-repo/setup/alfred-setup-ui.py")

    try:
        with open(DATA_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        sys.exit(f"alfred-build: data file not found: {DATA_FILE}\n"
                 f"  alfred-data.json is written by Claude during the brief run.\n"
                 f"  Run alfred-build.py only after Claude has finished gathering data.")
    except json.JSONDecodeError as e:
        sys.exit(f"alfred-build: alfred-data.json is not valid JSON: {e}\n"
                 f"  The data file may be incomplete — check that Claude finished writing it.")

    date_str     = data.get("date", datetime.today().strftime("%Y-%m-%d"))
    dt           = datetime.strptime(date_str, "%Y-%m-%d")
    date_display = _strftime(dt, "%A, %B %-d, %Y")
    date_short   = _strftime(dt, "%a %b %-d")

    fires = data.get("fires", [])
    summary_fire, summary_top_fire, summary_days, bar_state = r_summary_bar(
        fires, data.get("rollout_days") or "—"
    )
    yesterday_date, yesterday_recap, yesterday_hidden = r_yesterday_recap(data.get("yesterday_recap"))
    if yesterday_date is None:
        yesterday_date = "—"
        yesterday_recap = ""
        yesterday_hidden = 'style="display:none"'

    delta_html, delta_hidden = r_delta(data.get("delta"))

    milestones = data.get("milestones", [])
    milestones_html = r_milestones(milestones)
    milestones_hidden = "" if milestones_html else 'style="display:none"'
    milestones_json = json.dumps(milestones).replace("</", "<\\/")

    update_avail, latest_ver, repo_dir = _check_update()
    # Alfred may also pass update info via alfred-data.json (from SKILL.md version check)
    if data.get("update_available"):
        update_avail = True
        latest_ver = data.get("latest_version", latest_ver)
    update_hidden = "" if update_avail else 'style="display:none"'

    candidates_html, candidates_hidden, candidates_json = r_candidates()

    slots = {
        "DATE_DISPLAY":        date_display,
        "DATE_SHORT":          date_short,
        "SUMMARY_BAR_STATE":   bar_state,
        "SUMMARY_FIRE":        esc(summary_fire),
        "SUMMARY_TOP_FIRE":    esc(summary_top_fire),
        "SUMMARY_DAYS":        summary_days,
        "YESTERDAY_HIDDEN":    yesterday_hidden,
        "YESTERDAY_DATE":      yesterday_date,
        "YESTERDAY_RECAP":     yesterday_recap,
        "DATA_STATUS":         r_data_status(data.get("data_sources", {})),
        "FIRES":               r_fires(fires, data.get("resolved_fires",[])),
        "COACH_NOTE":          esc(data.get("coach_note","")),
        "TODAY_ROWS":          r_calendar_rows(data.get("calendar_events",[])),
        "TODAY_NOTICES":       r_calendar_notices(data.get("calendar_notices",[])),
        "PRIORITY_THREADS":    r_priority_threads(data.get("priority_threads",[])),
        "TEAM_COMMITMENTS":    r_team_commitments(data.get("team_commitments",[])),
        "DRIVE_MENTIONS":      r_drive_mentions(data.get("drive_mentions",[])),
        "KANBAN_JSON":          r_kanban_json({**(data.get("kanban") or {}), "auto_seed": {"due": data.get("due_this_week", []), "slipped": data.get("slipped", [])}}),
        "GENERATED_AT":        datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "DELTA_HTML":          delta_html,
        "DELTA_HIDDEN":        delta_hidden,
        "BAT_LOGO_PATH":       f"file://{BRIEFS_DIR}/batman-logo.png",
        "MILESTONES_SECTION":  milestones_html,
        "MILESTONES_HIDDEN":   milestones_hidden,
        "MILESTONES_JSON":     milestones_json,
        "ENTITIES_JSON":       r_entities(),
        "UPDATE_HIDDEN":       update_hidden,
        "LATEST_VERSION":      esc(latest_ver),
        "UPDATE_CMD":          f"cd {repo_dir} && git pull && python3 {repo_dir}/setup/alfred-update.py",
        "CANDIDATES_HTML":     candidates_html,
        "CANDIDATES_HIDDEN":   candidates_hidden,
        "CANDIDATES_JSON":     candidates_json,
    }

    for key, val in slots.items():
        tmpl = tmpl.replace(f"{{{{{key}}}}}", val)

    out = BRIEFS_DIR / f"alfred-brief-{date_str}.html"
    with open(out, "w") as f:
        f.write(tmpl)
    print(str(out))

if __name__ == "__main__":
    build()
