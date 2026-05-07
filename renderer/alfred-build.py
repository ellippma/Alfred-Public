#!/usr/bin/env python3
"""
alfred-build.py
Reads alfred-data.json → fills alfred-template.html → writes alfred-brief-YYYY-MM-DD.html
Usage: python3 ~/Documents/COS\ Briefs/alfred-build.py
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
        html += f'<div class="resolved-card"><strong>✅ RESOLVED — {esc(f["title"])}</strong> — {esc(f["note"])}</div>\n'
    for f in fires:
        link = f' <a href="{f["slack_url"]}" target="_blank">Open thread →</a>' if f.get("slack_url") else ""
        html += (
            f'<div class="fire-card">'
            f'<div class="fire-title">{esc(f["title"])}</div>'
            f'<div class="fire-body">{esc(f["body"])}{link}</div>'
            f'<div class="first-move"><strong>First move:</strong> {esc(f["first_move"])}</div>'
            f'</div>\n'
        )
    return html or "<p style='color:#6e6e73;font-size:13px'>No fires. Good morning.</p>"

def r_calendar_rows(events):
    html = ""
    for e in events:
        done     = e.get("done", False)
        conflict = e.get("conflict", False)
        priority = e.get("priority", False)
        row_cls  = ' class="done-row"' if done else ""
        name_cls = ' class="meeting-name"' if done else ""
        col_cls  = ' class="conflict"' if conflict else ""
        time_str = esc(e["time"]) + (" ⚠️" if conflict else "")
        title    = f"<strong>{esc(e['title'])}</strong>" if priority else esc(e["title"])
        note_cls = " green" if done else ""
        note_html = f'<div class="note{note_cls}">{esc(e["note"])}</div>' if e.get("note") else ""
        html += (
            f"<tr{row_cls}>"
            f"<td class='time'>{time_str}</td>"
            f"<td{col_cls}><span{name_cls}>{title}</span></td>"
            f"<td>{note_html}</td>"
            f"</tr>\n"
        )
    return html

def r_calendar_notices(notices):
    return "\n".join(f"<span>{esc(n)}</span>" for n in notices)

def r_list_items(items):
    html = ""
    for item in items:
        prefix = ""
        if item.get("pill") and item.get("pill_color"):
            prefix = pill(item["pill"], PILL_CLASS.get(item["pill_color"], "pill-gray")) + " "
        html += f"<li>{prefix}{esc(item['text'])}</li>\n"
    return html

def r_priority_threads(threads):
    html = ""
    for t in threads:
        drafted  = '<div class="drafted">✏️ Draft ready in Slack</div>' if t.get("drafted") else ""
        link_btn = f'<a href="{t["slack_url"]}" target="_blank">Open in Slack →</a>' if t.get("slack_url") else ""
        html += (
            f'<div class="thread-item">'
            f'<div class="thread-body"><strong>{esc(t["title"])}</strong> — {esc(t["body"])}{drafted}</div>'
            f'<div class="thread-link">{link_btn}</div>'
            f'</div>\n'
        )
    return html

def r_team_commitments(people):
    html = ""
    for person in people:
        items_html = ""
        for item in person["items"]:
            cls, label = STATUS_MAP.get(item.get("status",""), ("pill-gray", item.get("status","").upper()))
            note = f' — {esc(item["note"])}' if item.get("note") else ""
            items_html += f'<div class="team-item">{pill(label, cls)} {esc(item["text"])}{note}</div>\n'
        html += (
            f'<div class="team-person">'
            f'<div class="person-name">{esc(person["person"])}</div>'
            f'{items_html}</div>\n'
        )
    return html

def r_elixir_signals(signals):
    html = ""
    for s in signals:
        icon = SIGNAL_ICONS.get(s["type"], "⚪")
        link = f' <a href="{s["url"]}" target="_blank">{esc(s.get("url_text","View →"))}</a>' if s.get("url") else ""
        html += (
            f'<div class="signal-card">'
            f'<div class="signal-icon">{icon}</div>'
            f'<div><div class="signal-title">{esc(s["title"])}</div>{esc(s["body"])}{link}</div>'
            f'</div>\n'
        )
    return html

def r_drive_mentions(mentions):
    html = ""
    for m in mentions:
        html += (
            f'<div class="drive-item">'
            f'<div class="doc-title"><a href="{m["url"]}" target="_blank">{esc(m["title"])}</a></div>'
            f'<div class="doc-meta">Owner: {esc(m["owner"])} · {esc(m["note"])}</div>'
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
                f'{src_badge} {esc(s["text"])}{link}'
                f'</div>\n'
            )
        html += (
            f'<div class="milestone-card">'
            f'<div class="milestone-hdr">'
            f'<span class="milestone-name">{esc(m["name"])}</span>'
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


def r_jira(jira):
    if not jira:
        return ""
    body = ""
    specs = [
        ("create",      "🟠 Create",              "jira-create"),
        ("in_progress", "🔵 Move to In Progress",  "jira-progress"),
        ("done",        "✅ Move to Done",          "jira-done"),
    ]
    for key, heading, cls in specs:
        items = jira.get(key, [])
        if not items:
            continue
        tickets = ""
        for t in items:
            desc_key = "description" if "description" in t else "note"
            tickets += (
                f'<div class="jira-ticket {cls}">'
                f'<div class="ticket-title">{esc(t["title"])}</div>'
                f'<div class="ticket-desc">{esc(t.get(desc_key,""))}</div>'
                f'</div>\n'
            )
        body += f'<div class="jira-subsection"><div class="jira-subsection-title">{heading}</div>{tickets}</div>\n'
    if not body:
        return ""
    return f'<section><div class="section-title">🎫 Jira</div>{body}</section>'

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
        top_fire   = fires[0]["title"]
        state      = "state-fire"
    else:
        fire_label = f"🔥 {count} fires"
        top_fire   = fires[0]["title"]
        state      = "state-fire"
    return fire_label, top_fire, str(rollout_days), state


def build():
    with open(TEMPLATE) as f:
        tmpl = f.read()
    with open(DATA_FILE) as f:
        data = json.load(f)

    date_str     = data.get("date", datetime.today().strftime("%Y-%m-%d"))
    dt           = datetime.strptime(date_str, "%Y-%m-%d")
    date_display = dt.strftime("%A, %B %-d, %Y")
    date_short   = dt.strftime("%a %b %-d")

    fires = data.get("fires", [])
    summary_fire, summary_top_fire, summary_days, bar_state = r_summary_bar(
        fires, data.get("rollout_days", "—")
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
        "DUE_THIS_WEEK_ITEMS": r_list_items(data.get("due_this_week",[])),
        "SLIPPED_ITEMS":       r_list_items(data.get("slipped",[])),
        "PRIORITY_THREADS":    r_priority_threads(data.get("priority_threads",[])),
        "TEAM_COMMITMENTS":    r_team_commitments(data.get("team_commitments",[])),
        "ELIXIR_SIGNALS":      r_elixir_signals(data.get("elixir_signals",[])),
        "DRIVE_MENTIONS":      r_drive_mentions(data.get("drive_mentions",[])),
        "ROLLOUT_DAYS":        str(data.get("rollout_days","—")),
        "ROLLOUT_NOTE":        esc(data.get("rollout_note","")),
        "JIRA_SECTION":        r_jira(data.get("jira")),
        "GENERATED_AT":        datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "DELTA_HTML":          delta_html,
        "DELTA_HIDDEN":        delta_hidden,
        "BAT_LOGO_PATH":       f"file://{BRIEFS_DIR}/batman-logo.png",
        "MILESTONES_SECTION":  milestones_html,
        "MILESTONES_HIDDEN":   milestones_hidden,
        "MILESTONES_JSON":     milestones_json,
        "UPDATE_HIDDEN":       update_hidden,
        "LATEST_VERSION":      esc(latest_ver),
        "UPDATE_CMD":          f"cd {repo_dir} && git pull && python3 {repo_dir}/setup/alfred-update.py",
    }

    for key, val in slots.items():
        tmpl = tmpl.replace(f"{{{{{key}}}}}", val)

    out = BRIEFS_DIR / f"alfred-brief-{date_str}.html"
    with open(out, "w") as f:
        f.write(tmpl)
    print(str(out))

if __name__ == "__main__":
    build()
