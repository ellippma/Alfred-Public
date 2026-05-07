#!/usr/bin/env python3
"""
alfred-setup-ui.py
Browser-based setup wizard for Alfred.
Starts a local web server, opens the browser automatically, no terminal interaction needed.
"""

import http.server, json, os, queue, re, shutil, socket, sys, threading, webbrowser
from datetime import datetime
from pathlib import Path

# ─── Constants ────────────────────────────────────────────────────────────────

ALFRED_REPO    = Path(__file__).parent.parent
TEMPLATES_DIR  = ALFRED_REPO / "templates"
CLAUDE_DIR     = Path.home() / ".claude"
SETTINGS_LOCAL = CLAUDE_DIR / "settings.local.json"
CONFIG_PATH    = Path.home() / ".alfred-config.json"

KNOWN_SERVICES = {
    "slack":    ["slack_send_message", "slack_search_public"],
    "gmail":    ["search_threads", "create_draft"],
    "calendar": ["list_events", "create_event"],
    "drive":    ["search_files", "read_file_content"],
    "granola":  ["list_meetings", "get_meeting_transcript"],
}
ALFRED_TOOLS = {
    "slack":    ["slack_search_channels", "slack_search_public_and_private", "slack_send_message_draft"],
    "calendar": ["list_events", "create_event"],
    "gmail":    ["search_threads", "create_draft"],
    "drive":    ["search_files", "list_recent_files"],
    "granola":  ["list_meetings", "query_granola_meetings"],
}
FIXED_PERMISSIONS = [
    # Built-in tool wildcards — Alfred needs full autonomy, no per-call prompts
    "Bash(*)",
    "Read(*)",
    "Write(*)",
    "Edit(*)",
    "Glob(*)",
    "Grep(*)",
    "mcp__granola__list_meetings",
    "mcp__granola__query_granola_meetings",
    "mcp__scheduled-tasks__create_scheduled_task",
    "mcp__scheduled-tasks__list_scheduled_tasks",
    "mcp__scheduled-tasks__update_scheduled_task",
]
TIMEZONES = [
    ("America/New_York",    "Eastern — New York"),
    ("America/Chicago",     "Central — Chicago"),
    ("America/Denver",      "Mountain — Denver"),
    ("America/Los_Angeles", "Pacific — Los Angeles"),
    ("America/Phoenix",     "Arizona (no DST)"),
    ("Europe/London",       "London"),
    ("Europe/Berlin",       "Central Europe"),
]

# ─── Setup logic ──────────────────────────────────────────────────────────────

def claude_project_segment():
    return str(Path.home()).replace("/", "-").replace(".", "-")

SVC_NAME_ALIASES = {
    "slack":    ["slack"],
    "gmail":    ["gmail", "google-mail", "googlemail", "google_mail"],
    "calendar": ["calendar", "gcal", "google-calendar", "google_calendar", "googlecal", "googlecalendar"],
    "drive":    ["drive", "gdrive", "google-drive", "google_drive", "googledrive"],
    "granola":  ["granola"],
}

def _svc_from_aliases(text):
    """Return the first service whose aliases appear in text (lowercased), or None."""
    tl = text.lower()
    for svc, aliases in SVC_NAME_ALIASES.items():
        if any(a in tl for a in aliases):
            return svc
    return None

def detect_mcp_ids():
    prefixes = {}
    # Scan all known Claude config files that may contain mcpServers entries.
    # Note: Claude app Connectors (Gmail, Calendar, Drive, Slack set up via
    # Settings → Connectors) are cloud-managed and have no local config entry —
    # they cannot be auto-detected here. The wizard UI lets users mark those manually.
    scan_files = [
        CLAUDE_DIR / "settings.local.json",
        CLAUDE_DIR / "settings.json",
        Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
    ]
    for sf in scan_files:
        if not sf.exists():
            continue
        try:
            data = json.loads(sf.read_text())
            for name, srv_cfg in data.get("mcpServers", {}).items():
                prefix = f"mcp__{name}__"
                # 1. Match on server key name (human-readable MCPs like "granola")
                svc = _svc_from_aliases(name)
                if svc and svc not in prefixes:
                    prefixes[svc] = prefix
                # 2. Match on server config values (catches MCPs with UUID keys but
                #    recognizable URLs/commands)
                if isinstance(srv_cfg, dict) and svc is None:
                    haystack = " ".join(str(v) for v in srv_cfg.values() if isinstance(v, str))
                    svc = _svc_from_aliases(haystack)
                    if svc and svc not in prefixes:
                        prefixes[svc] = prefix
            # 3. Match on permissions.allow tool names (catches already-permissioned installs)
            for entry in data.get("permissions", {}).get("allow", []):
                if not entry.startswith("mcp__"):
                    continue
                parts = entry.split("__", 2)
                if len(parts) < 3:
                    continue
                tool = parts[2]
                for svc, hints in KNOWN_SERVICES.items():
                    if any(h in tool for h in hints) and svc not in prefixes:
                        prefixes[svc] = f"mcp__{parts[1]}__"
        except Exception:
            pass
    # scheduled-tasks and ccd_session are Claude Code built-ins — always present.
    # Granola is detected via alias matching above; don't hardcode it.
    for svc in ["scheduled-tasks", "ccd_session"]:
        prefixes[svc] = f"mcp__{svc}__"
    return prefixes

def fill_template(text, config):
    return re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: config.get(m.group(1), m.group(0)), text)

def install_template(src, dst, config):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(fill_template(Path(src).read_text(), config))

def pre_populate_permissions(prefixes):
    entries = list(FIXED_PERMISSIONS)
    for svc, tools in ALFRED_TOOLS.items():
        if prefix := prefixes.get(svc):
            for tool in tools:
                entries.append(f"{prefix}{tool}")
    data = {}
    if SETTINGS_LOCAL.exists():
        try:
            data = json.loads(SETTINGS_LOCAL.read_text())
        except Exception:
            pass
    perms = data.setdefault("permissions", {})
    existing = set(perms.get("allow", []))
    new_entries = set(entries) - existing
    perms["allow"] = sorted(existing | set(entries))
    SETTINGS_LOCAL.write_text(json.dumps(data, indent=2))
    return len(new_entries)

def _read_skill(task_name, config):
    installed = CLAUDE_DIR / "scheduled-tasks" / task_name / "SKILL.md"
    if installed.exists():
        content = installed.read_text()
        if len(content) > 500:
            return content
    tmpl = TEMPLATES_DIR / "brain" / task_name / "SKILL.md.template"
    return fill_template(tmpl.read_text(), config) if tmpl.exists() else ""

def _build_milestones_list(milestones):
    """Format milestone list for milestones.md template."""
    if not milestones:
        return "<!-- No milestones added yet — manage them from the 🏁 MILESTONES button in your Alfred brief -->"
    parts = []
    for m in milestones:
        name = m.get("name", "").strip()
        if not name:
            continue
        desc        = m.get("description", "").strip() or "No description provided."
        target_date = m.get("target_date", "").strip() or "TBD"
        parts.append(f"## {name}\n**Description:** {desc}\n**Target date:** {target_date}\n**Status:** active")
    return "\n\n".join(parts) if parts else "<!-- No milestones added yet — manage them from the 🏁 MILESTONES button in your Alfred brief -->"

def run_install(raw, emit):
    """Full install pipeline. raw = dict from browser form. Calls emit(msg, level) for progress."""
    home = str(Path.home())
    briefs_dir = raw.get("briefs_dir") or str(Path.home() / "Documents" / "Alfred Briefs")
    repo_dir = str(ALFRED_REPO)

    stk   = raw.get("stakeholders", [{}])
    nofly = [e for e in raw.get("nofly_emails", []) if e]
    nofly_never = bool(raw.get("nofly_never", False))
    drs   = raw.get("direct_reports", [{}])
    product = raw.get("product", "")
    quarter = f"Q{((datetime.today().month-1)//3)+1} {datetime.today().year}"

    config = {
        "USER_NAME":             raw["name"],
        "USER_EMAIL":            raw["email"],
        "COMPANY":               raw["company"],
        "USER_ROLE":             raw["role"],
        "USER_MISSION":          raw["mission"],
        "SLACK_USER_ID":         raw["slack_uid"],
        "SLACK_WORKSPACE_ID":    raw["slack_ws"],
        "TIER1_NAME_1":          stk[0].get("name", "") if stk else "",
        "TIER1_TITLE_1":         stk[0].get("title", "") if stk else "",
        "TIER1_NOTE_1":          stk[0].get("note", "") if stk else "",
        "TIER1_NAME_2":          stk[1].get("name", "") if len(stk) > 1 else (stk[0].get("name", "") if stk else ""),
        "TIER1_TITLE_2":         stk[1].get("title", "") if len(stk) > 1 else (stk[0].get("title", "") if stk else ""),
        "TIER1_NOTE_2":          stk[1].get("note", "") if len(stk) > 1 else "",
        "MANAGER_NAME":          raw["mgr_name"],
        "MANAGER_TITLE":         raw["mgr_title"],
        "MANAGER_NOTE":          raw.get("mgr_note", ""),
        "NOFLY_1":               "everyone" if nofly_never else (nofly[0] if len(nofly) > 0 else ""),
        "NOFLY_2":               "" if nofly_never else (nofly[1] if len(nofly) > 1 else ""),
        "NOFLY_3":               "" if nofly_never else (nofly[2] if len(nofly) > 2 else ""),
        "NOFLY_LIST":            "everyone — never send any calendar invites on my behalf" if nofly_never else (", ".join(nofly) if nofly else ""),
        "NOFLY_LIST_MD":         "- everyone — never send any calendar invites on my behalf" if nofly_never else ("\n".join(f"- {e}" for e in nofly) if nofly else "- (none set)"),
        "DIRECT_REPORT_1":       drs[0].get("name", "") if drs else "",
        "DIRECT_REPORT_1_TITLE": drs[0].get("title", "") if drs else "",
        "DIRECT_REPORT_1_NOTE":  drs[0].get("note", "") if drs else "",
        "DIRECT_REPORT_2":       drs[1].get("name", "") if len(drs) > 1 else "",
        "DIRECT_REPORT_2_TITLE": drs[1].get("title", "") if len(drs) > 1 else "",
        "DIRECT_REPORT_2_NOTE":  drs[1].get("note", "") if len(drs) > 1 else "",
        "STAKEHOLDERS_LIST":     "\n".join(
            f"- **{s.get('name','')}** — {s.get('title','')}. {s.get('note','')}"
            for s in stk if s.get("name")
        ) or "- (none set)",
        "DIRECT_REPORTS_LIST":   "\n".join(
            f"- **{d.get('name','')}** — {d.get('title','')}. {d.get('note','')} Track commitments closely."
            for d in drs if d.get("name")
        ) or "- (none set)",
        "DIRECT_REPORTS_INLINE": " + ".join(d.get("name", "") for d in drs if d.get("name")) or "team",
        "MILESTONES_LIST":        _build_milestones_list(raw.get("milestones", [])),
        "PRODUCT_NAME":          product,
        "ROLLOUT_DATE":          raw.get("rollout_date", ""),
        "CURRENT_QUARTER":       quarter,
        "TIMEZONE":              raw.get("timezone", "America/New_York"),
        "BRIEFS_DIR":            briefs_dir,
        "BRIEFS_DIR_ESC":        briefs_dir.replace(" ", "\\ "),
        "REPO_DIR":              repo_dir,
        "HOME_DIR":              home,
    }
    product_label = product or "the main initiative"
    config["SLACK_SIGNAL_FILTER"] = (
        f"Surface signals relevant to {product_label} and {config['USER_ROLE']}. "
        f"Filter out deal-specific noise unless it involves {config['TIER1_NAME_1']} or {config['MANAGER_NAME']}."
    )
    config["INITIATIVE_1_NAME"]   = product_label
    config["INITIATIVE_1_DESC"]   = f"Rolling out {product_label} across {config['COMPANY']}"
    config["INITIATIVE_1_METRIC"] = "Adoption rate, active usage"
    config["INITIATIVE_1_DATE"]   = raw.get("rollout_date", "") or "TBD"

    # Detect MCPs
    emit("Detecting MCP connections…", "info")
    prefixes = detect_mcp_ids()
    svc_labels = {"slack": "Slack", "gmail": "Gmail", "calendar": "Google Calendar",
                  "drive": "Google Drive", "granola": "Granola"}
    found = []
    for svc, label in svc_labels.items():
        if svc in prefixes:
            emit(f"✓ {label} detected", "ok")
            found.append(svc)
        else:
            req = " (required)" if svc in ("slack", "calendar") else " (optional)"
            emit(f"⚠ {label} not detected{req}", "warn")

    config["MCP_SLACK"]    = prefixes.get("slack",    "mcp__REPLACE_SLACK_ID__")
    config["MCP_GMAIL"]    = prefixes.get("gmail",    "mcp__REPLACE_GMAIL_ID__")
    config["MCP_CALENDAR"] = prefixes.get("calendar", "mcp__REPLACE_CALENDAR_ID__")
    config["MCP_DRIVE"]    = prefixes.get("drive",    "mcp__REPLACE_DRIVE_ID__")
    # Granola always uses the fixed prefix mcp__granola__ if installed.
    config["MCP_GRANOLA"]  = prefixes.get("granola",  "mcp__granola__")
    config["MCP_AVAILABLE"] = ", ".join(found)

    # Permissions
    emit("Pre-approving tool permissions…", "info")
    n = pre_populate_permissions(prefixes)
    emit(f"✓ {n} permission(s) pre-approved", "ok")

    # Directories
    bd = Path(briefs_dir).expanduser()
    segment = claude_project_segment()
    memory_dir = CLAUDE_DIR / "projects" / segment / "memory"
    tasks_dir  = CLAUDE_DIR / "scheduled-tasks"
    cmds_dir   = CLAUDE_DIR / "commands"
    for d in [bd, memory_dir, tasks_dir, cmds_dir]:
        d.mkdir(parents=True, exist_ok=True)

    config["MEMORY_DIR"] = str(memory_dir)
    config["CLAUDE_PROJECT_SEGMENT"] = segment

    # Renderer
    emit("Installing renderer…", "info")
    for fname in ["alfred-build.py", "alfred-template.html", "read-notepad.py"]:
        src = ALFRED_REPO / "renderer" / fname
        if src.exists():
            shutil.copy2(src, bd / fname)
            emit(f"✓ {fname}", "ok")
    logo_src = ALFRED_REPO / "batman-logo.png"
    if logo_src.exists():
        shutil.copy2(logo_src, bd / "batman-logo.png")
        emit("✓ batman-logo.png", "ok")

    # Scheduled tasks
    emit("Installing scheduled tasks…", "info")
    for task in ["morning-brief", "pre-meeting-brief", "friday-wrap"]:
        src = TEMPLATES_DIR / "brain" / task / "SKILL.md.template"
        if src.exists():
            install_template(src, tasks_dir / task / "SKILL.md", config)
            emit(f"✓ {task}", "ok")

    # Slash commands
    emit("Installing /alfred commands…", "info")
    for cmd in ["alfred", "alfred-config"]:
        src = TEMPLATES_DIR / "commands" / f"{cmd}.md.template"
        if src.exists():
            install_template(src, cmds_dir / f"{cmd}.md", config)
            emit(f"✓ /{cmd} command", "ok")

    # Memory files
    emit("Installing memory files…", "info")
    # Files regenerated every run — purely derived from wizard inputs.
    mem_templates_always = {
        "user_role.md.template":            "user_role.md",
        "project_initiatives.md.template":  "project_q2_initiatives.md",
        "project_personal_cos.md.template": "project_personal_cos.md",
        "milestones.md.template":           "milestones.md",
        "MEMORY.md.template":               "MEMORY.md",
    }
    # Files written only on first install — preserved on re-run to protect
    # calibrations, trained feedback rules, and hand-edited stakeholder notes.
    mem_templates_preserve = {
        "stakeholders.md.template":         "stakeholders.md",
        "calibrations.md.template":         "calibrations.md",
        "feedback_blindspots.md.template":  "feedback_blindspots.md",
        "delivered.md.template":            "delivered.md",
    }
    for tmpl, dst_name in mem_templates_always.items():
        src = TEMPLATES_DIR / "memory" / tmpl
        if src.exists():
            install_template(src, memory_dir / dst_name, config)
            emit(f"✓ {dst_name}", "ok")
    for tmpl, dst_name in mem_templates_preserve.items():
        src  = TEMPLATES_DIR / "memory" / tmpl
        dst  = memory_dir / dst_name
        if dst.exists():
            emit(f"⏭  {dst_name} — already exists, preserved", "info")
        elif src.exists():
            install_template(src, dst, config)
            emit(f"✓ {dst_name}", "ok")
    for fname, content in [
        ("last_brief.md", "# Last Brief State\n\n(Populated by Alfred after first run)\n"),
    ]:
        dst = memory_dir / fname
        if not dst.exists():
            dst.write_text(content)
            emit(f"✓ {fname}", "ok")

    # Config file
    installed_version = "1.0.0"
    ver_file = ALFRED_REPO / "VERSION"
    if ver_file.exists():
        installed_version = ver_file.read_text().strip()

    TEMPLATE_VAR_KEYS = [
        "USER_NAME","USER_EMAIL","COMPANY","USER_ROLE","SLACK_USER_ID","SLACK_WORKSPACE_ID",
        "TIER1_NAME_1","TIER1_TITLE_1","TIER1_NOTE_1","TIER1_NAME_2","TIER1_TITLE_2","TIER1_NOTE_2",
        "MANAGER_NAME","MANAGER_TITLE","MANAGER_NOTE",
        "NOFLY_1","NOFLY_2","NOFLY_3","NOFLY_LIST","NOFLY_LIST_MD",
        "DIRECT_REPORT_1","DIRECT_REPORT_2","DIRECT_REPORTS_INLINE","DIRECT_REPORTS_LIST",
        "STAKEHOLDERS_LIST","PRODUCT_NAME","CURRENT_QUARTER","TIMEZONE",
        "BRIEFS_DIR","BRIEFS_DIR_ESC","MEMORY_DIR","REPO_DIR","HOME_DIR",
        "MCP_SLACK","MCP_GMAIL","MCP_CALENDAR","MCP_DRIVE","MCP_GRANOLA","MCP_AVAILABLE",
        "SLACK_SIGNAL_FILTER","INITIATIVE_1_NAME","INITIATIVE_1_DESC",
        "INITIATIVE_1_METRIC","INITIATIVE_1_DATE","CLAUDE_PROJECT_SEGMENT",
    ]
    config_out = {
        "version": installed_version,
        "generated": datetime.now().isoformat(),
        "user": {k: config[k] for k in ["USER_NAME","USER_EMAIL","COMPANY","USER_ROLE","SLACK_USER_ID","SLACK_WORKSPACE_ID"]},
        "paths": {"briefs_dir": briefs_dir, "memory_dir": str(memory_dir), "repo_dir": repo_dir},
        "timezone": config["TIMEZONE"],
        "template_vars": {k: config.get(k, "") for k in TEMPLATE_VAR_KEYS},
    }
    CONFIG_PATH.write_text(json.dumps(config_out, indent=2))
    emit("✓ Config saved", "ok")

    # Finish prompt — uses read-before-create pattern to avoid SKILL.md being overwritten
    emit("Building finish prompt…", "info")

    prompt = f"""You are Alfred, the personal AI Chief of Staff. A new user just ran the setup wizard. Complete their installation in two tasks.

**User:** {config["USER_NAME"]} ({config["USER_EMAIL"]})
**Timezone:** {config["TIMEZONE"]}
**Briefs directory:** {config["BRIEFS_DIR"]}

---

# Task 1 — Register scheduled tasks

First, check whether the `mcp__scheduled-tasks__create_scheduled_task` tool is available in your current session.

---

## Path A — if `scheduled-tasks` is available (preferred)

⚠️ `create_scheduled_task` overwrites SKILL.md with a short string. For each task: (1) read the file first, (2) create the task, (3) write the content back immediately.

### Morning brief
1. Read `{home}/.claude/scheduled-tasks/morning-brief/SKILL.md`
2. Create scheduled task — cronExpression: `57 7 * * 1-5`, prompt: `Read and execute the instructions in {home}/.claude/scheduled-tasks/morning-brief/SKILL.md`, description: `Alfred — morning brief, Mon–Fri 7:57 AM`
3. Write the content from step 1 back to `{home}/.claude/scheduled-tasks/morning-brief/SKILL.md`

### Pre-meeting brief
1. Read `{home}/.claude/scheduled-tasks/pre-meeting-brief/SKILL.md`
2. Create scheduled task — cronExpression: `*/10 7-19 * * 1-5`, prompt: `Read and execute the instructions in {home}/.claude/scheduled-tasks/pre-meeting-brief/SKILL.md`, description: `Alfred — pre-meeting brief, every 10 min on weekdays`, notifyOnCompletion: false
3. Write the content from step 1 back to `{home}/.claude/scheduled-tasks/pre-meeting-brief/SKILL.md`

### Friday wrap
1. Read `{home}/.claude/scheduled-tasks/friday-wrap/SKILL.md`
2. Create scheduled task — cronExpression: `0 16 * * 5`, prompt: `Read and execute the instructions in {home}/.claude/scheduled-tasks/friday-wrap/SKILL.md`, description: `Alfred — Friday week wrap at 4 PM`, notifyOnCompletion: false
3. Write the content from step 1 back to `{home}/.claude/scheduled-tasks/friday-wrap/SKILL.md`

---

## Path B — if `scheduled-tasks` is NOT available

`scheduled-tasks` is Claude Code's Desktop Scheduled Tasks feature. If it's not injected in your session, the user's Claude Code needs an update.

Tell the user:

> The `scheduled-tasks` tool isn't available in this session — this means Claude Code needs to be updated. Please:
> 1. Open Claude Code → **Help → Check for Updates** and install any available update
> 2. Quit and reopen Claude Code
> 3. Start a **new session** and re-paste this setup prompt
>
> After updating, Path A above will work automatically.
>
> **Do not use CronCreate as a workaround** — CronCreate tasks expire after 7 days and Alfred will silently stop running.

Do not proceed to Task 2 until the user has confirmed Path A succeeded.

---

# Task 1.5 — Resolve any undetected MCP placeholders

The setup wizard auto-detects MCP tool prefixes, but some Claude Code configurations don't expose them in settings files. Scan these files for any remaining `mcp__REPLACE_` placeholder strings:

- `{home}/.claude/scheduled-tasks/morning-brief/SKILL.md`
- `{home}/.claude/scheduled-tasks/pre-meeting-brief/SKILL.md`
- `{home}/.claude/scheduled-tasks/friday-wrap/SKILL.md`
- `{home}/.claude/commands/alfred.md`

If any `mcp__REPLACE_` strings are present:
1. Read `{home}/.claude/settings.local.json` and `{home}/.claude/settings.json`
2. Identify the actual MCP prefix for each service — look for tool entries in `permissions.allow` (e.g. `mcp__UUID__slack_send_message`) and server keys in `mcpServers`
3. In every affected file, replace:
   - `mcp__REPLACE_SLACK_ID__` → the detected Slack prefix
   - `mcp__REPLACE_GMAIL_ID__` → the detected Gmail prefix
   - `mcp__REPLACE_CALENDAR_ID__` → the detected Google Calendar prefix
   - `mcp__REPLACE_DRIVE_ID__` → the detected Google Drive prefix
4. Write the corrected content back to each file

If no `mcp__REPLACE_` strings are found in any file, skip this step entirely.

---

# Task 2 — Generate first brief

Read and execute `{home}/.claude/scheduled-tasks/morning-brief/SKILL.md` to generate {config["USER_NAME"]}'s first Alfred brief now.

Confirm when done.
"""

    out = ALFRED_REPO / "setup" / "complete-setup-prompt.txt"
    out.write_text(prompt)

    clipboard = False
    try:
        import subprocess
        subprocess.run(["pbcopy"], input=prompt.encode(), check=True)
        clipboard = True
    except Exception:
        pass

    emit("✓ Installation complete!", "ok")
    return {"prompt": prompt, "clipboard": clipboard, "prompt_file": str(out)}


# ─── HTML wizard ──────────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alfred Setup</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
     background:#f0f0f5;color:#1d1d1f;min-height:100vh;
     display:flex;flex-direction:column;align-items:center;padding:40px 16px 60px}
.header{text-align:center;margin-bottom:28px}
.bat{font-size:44px;line-height:1;margin-bottom:10px}
.header h1{font-size:26px;font-weight:700;letter-spacing:-.3px}
.header p{color:#6e6e73;margin-top:5px;font-size:14px}

/* Step bar */
.stepbar{display:flex;align-items:center;justify-content:center;margin-bottom:28px;gap:0}
.sbdot{width:30px;height:30px;border-radius:50%;border:2px solid #d2d2d7;background:#fff;
       display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;
       color:#6e6e73;transition:all .2s;flex-shrink:0}
.sbdot.active{border-color:#F5C518;background:#F5C518;color:#1d1d1f}
.sbdot.done{border-color:#34c759;background:#34c759;color:#fff}
.sbline{width:36px;height:2px;background:#d2d2d7;transition:background .2s}
.sbline.done{background:#34c759}

/* Card */
.card{background:#fff;border-radius:18px;padding:36px 40px;
      box-shadow:0 2px 24px rgba(0,0,0,.07);width:100%;max-width:660px}
.card h2{font-size:20px;font-weight:700;margin-bottom:6px}
.card .desc{color:#6e6e73;font-size:14px;line-height:1.55;margin-bottom:26px}

/* Fields */
.field{margin-bottom:16px}
.field label{display:block;font-size:13px;font-weight:600;margin-bottom:5px;color:#1d1d1f}
.field .hint{font-size:12px;color:#6e6e73;margin-bottom:6px;line-height:1.4}
.field input,.field select{
  width:100%;padding:10px 13px;border:1.5px solid #d2d2d7;border-radius:9px;
  font-size:14px;outline:none;transition:border-color .15s;background:#fff;color:#1d1d1f}
.field input:focus,.field select:focus{border-color:#F5C518;box-shadow:0 0 0 3px rgba(245,197,24,.15)}
.field input.err{border-color:#ff3b30}
.errmsg{color:#ff3b30;font-size:12px;margin-top:4px;display:none}
.field-row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.opt{color:#6e6e73;font-weight:400;margin-left:4px;font-size:11px}
.how-link{font-size:11px;color:#0a84ff;cursor:pointer;margin-left:6px}
.how-box{background:#f5f5f7;border-radius:8px;padding:10px 13px;font-size:12px;
         line-height:1.5;color:#3d3d3f;margin-top:6px;display:none}

/* MCP status */
.mcp-panel{background:#f5f5f7;border-radius:11px;padding:14px 16px;margin-bottom:22px}
.mcp-title{font-size:12px;font-weight:600;color:#6e6e73;margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px}
.mcp-row{display:flex;align-items:center;gap:9px;padding:4px 0;font-size:13px}
.mcp-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.mcp-dot.ok{background:#34c759}
.mcp-dot.warn{background:#FF9500}
.mcp-dot.spin{background:#d2d2d7;animation:pulse 1.2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.4}50%{opacity:1}}
.mcp-badge{font-size:10px;padding:2px 7px;border-radius:20px;font-weight:600;margin-left:auto}
.mcp-badge.req{background:#fff0f0;color:#ff3b30}
.mcp-badge.rec{background:#f0f0ff;color:#5856d6}

/* Dynamic items (stakeholders, DRs) */
.ditem{background:#f9f9fb;border:1.5px solid #e8e8ed;border-radius:11px;
       padding:16px 18px;margin-bottom:12px}
.ditem-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.ditem-lbl{font-size:11px;font-weight:700;color:#6e6e73;text-transform:uppercase;letter-spacing:.5px}
.ditem-rm{background:none;border:none;color:#aeaeb2;cursor:pointer;font-size:20px;
          line-height:1;padding:0 2px;transition:color .15s}
.ditem-rm:hover{color:#ff3b30}
.ditem .field{margin-bottom:10px}
.ditem .field:last-child{margin-bottom:0}

/* Add button */
.add-btn{display:flex;align-items:center;justify-content:center;gap:6px;width:100%;
         background:none;border:1.5px dashed #d2d2d7;border-radius:9px;
         padding:10px;font-size:13px;color:#6e6e73;cursor:pointer;
         transition:all .15s;margin-top:4px}
.add-btn:hover{border-color:#F5C518;color:#1d1d1f;background:#fffce8}

/* Section separator */
.sep{border:none;border-top:1px solid #eee;margin:24px 0 20px}
.sub-h{font-size:14px;font-weight:700;margin-bottom:4px}
.sub-p{font-size:13px;color:#6e6e73;line-height:1.5;margin-bottom:14px}

/* No-fly info box */
.nofly-box{display:flex;gap:10px;background:#eef3ff;border-radius:10px;
           padding:12px 14px;margin-bottom:14px;font-size:13px;color:#3d3d3f;line-height:1.55}
.nofly-icon{font-size:20px;flex-shrink:0;margin-top:1px}

/* Nav buttons */
.btnrow{display:flex;justify-content:space-between;align-items:center;margin-top:30px}
.btn{padding:11px 26px;border-radius:10px;font-size:14px;font-weight:600;
     border:none;cursor:pointer;transition:all .15s}
.btn-primary{background:#F5C518;color:#1d1d1f}
.btn-primary:hover{background:#e6b800}
.btn-ghost{background:transparent;color:#6e6e73;padding-left:8px}
.btn-ghost:hover{color:#1d1d1f}

/* Review table */
.rtable{width:100%;border-collapse:collapse;font-size:13px}
.rtable td{padding:7px 2px;border-bottom:1px solid #f0f0f2;vertical-align:top}
.rtable tr:last-child td{border-bottom:none}
.rtable td:first-child{color:#6e6e73;width:150px;font-weight:500;padding-right:12px}

/* Progress log */
.plog{background:#1d1d1f;border-radius:11px;padding:16px;font-family:'SF Mono',Monaco,Menlo,monospace;
      font-size:12px;color:#e5e5e7;height:220px;overflow-y:auto;line-height:1.7}
.plog .ok{color:#34c759}
.plog .warn{color:#FF9500}
.plog .info{color:#636366}

/* Done */
.done-hero{text-align:center;padding:10px 0 20px}
.done-hero .icon{font-size:52px;margin-bottom:12px}
.done-hero h2{font-size:22px;font-weight:700;margin-bottom:6px}
.done-hero p{color:#6e6e73;font-size:14px;line-height:1.55}
.prompt-box{background:#f5f5f7;border-radius:11px;padding:16px;margin-top:18px}
.prompt-box pre{font-family:'SF Mono',Monaco,Menlo,monospace;font-size:10.5px;
                white-space:pre-wrap;word-break:break-word;max-height:160px;overflow-y:auto;
                color:#1d1d1f;line-height:1.5}
.copy-row{display:flex;gap:10px;margin-top:12px;align-items:center}
.copy-note{font-size:12px;color:#6e6e73}
.copy-note.ok{color:#34c759}
</style>
</head>
<body>

<div class="header">
  <div class="bat">🦇</div>
  <h1>Alfred Setup</h1>
  <p>Personal AI Chief of Staff — about 5 minutes</p>
</div>

<div class="stepbar" id="stepbar"></div>

<div class="card" id="card">
  <p style="color:#6e6e73;font-size:14px">Loading…</p>
</div>

<script>
// ── Config ────────────────────────────────────────────────────────────────────
const STEPS = [
  { label:'You',       id:'you' },
  { label:'People',    id:'people' },
  { label:'Team',      id:'team' },
  { label:'Goals',     id:'goals' },
  { label:'Paths',     id:'paths' },
];
const REVIEW_STEP  = STEPS.length + 1;  // 5
const INSTALL_STEP = REVIEW_STEP  + 1;  // 6
const DONE_STEP    = INSTALL_STEP + 1;  // 7

let step = 0;
let formData = {};
let mcpStatus = null;

// ── Dynamic state ─────────────────────────────────────────────────────────────
let stakeholders  = [{name:'', title:'', note:''}];
let noflyEmails   = [''];
let noflyNever    = false;
let directReports = [{name:'', title:'', note:''}];
let milestones    = [{name:'', description:'', target_date:''}];

// ── Step bar ──────────────────────────────────────────────────────────────────
function renderStepBar() {
  const sb = document.getElementById('stepbar');
  if (step >= REVIEW_STEP) { sb.style.display = 'none'; return; }
  sb.style.display = 'flex';
  const wi = step - 1;
  let html = '';
  STEPS.forEach((s, i) => {
    const cls = i < wi ? 'done' : i === wi ? 'active' : '';
    html += `<div class="sbdot ${cls}">${i < wi ? '&#10003;' : i+1}</div>`;
    if (i < STEPS.length - 1) html += `<div class="sbline ${i < wi ? 'done' : ''}"></div>`;
  });
  sb.innerHTML = html;
}

// ── MCP detection ─────────────────────────────────────────────────────────────
async function loadMCPs() {
  try {
    const r = await fetch('/api/detect-mcps');
    mcpStatus = await r.json();
  } catch(e) { mcpStatus = {}; }
  if (step === 0) renderStep();
}

// Per-service manual override — set when user checks "I set this up"
var mcpManual = {};
function mcpToggleManual(key) {
  mcpManual[key] = !mcpManual[key];
  renderStep();
}
function mcpIsOk(key) {
  return (mcpStatus && mcpStatus[key] && mcpStatus[key].detected) || !!mcpManual[key];
}

function mcpPanel() {
  if (!mcpStatus) return `<div class="mcp-panel"><div class="mcp-title">Checking connections…</div>
    <div class="mcp-row"><div class="mcp-dot spin"></div> Scanning config files…</div></div>`;
  const svcs = [
    {key:'slack',    label:'Slack',           req:true},
    {key:'calendar', label:'Google Calendar', req:true},
    {key:'gmail',    label:'Gmail',           req:false},
    {key:'drive',    label:'Google Drive',    req:false},
    {key:'granola',  label:'Granola',         req:false},
  ];
  const rows = svcs.map(s => {
    const ok    = mcpIsOk(s.key);
    const auto  = mcpStatus[s.key] && mcpStatus[s.key].detected;
    const badge = s.req ? '<span class="mcp-badge req">Required</span>'
                        : '<span class="mcp-badge rec">Recommended</span>';
    const dot   = ok ? 'ok' : 'warn';
    const col   = ok ? '#34c759' : '#FF9500';
    const lbl   = auto ? 'Auto-detected' : ok ? 'Confirmed (manual)' : 'Not detected';
    const chk   = !auto ? `<label style="margin-left:auto;font-size:11px;color:#6e6e73;cursor:pointer;display:flex;align-items:center;gap:4px">
      <input type="checkbox" ${mcpManual[s.key]?'checked':''} onchange="mcpToggleManual('${s.key}')"> I set this up
    </label>` : '';
    return `<div class="mcp-row" style="gap:6px"><div class="mcp-dot ${dot}"></div>${s.label} — <span style="color:${col}">${lbl}</span>${badge}${chk}</div>`;
  }).join('');
  const allReq = ['slack','calendar'].every(k => mcpIsOk(k));
  const note = `<div style="margin-top:10px;font-size:12px;color:#6e6e73;line-height:1.5">
    Connections set up via <strong>Claude app Settings &rarr; Connectors</strong> can&rsquo;t be auto-detected — check &ldquo;I set this up&rdquo; for each one you&rsquo;ve connected.</div>`;
  const warn = allReq ? '' : `<div style="margin-top:8px;font-size:12px;color:#FF9500;line-height:1.5">
    Mark required connections above before continuing.</div>`;
  return `<div class="mcp-panel"><div class="mcp-title">Connections</div>${rows}${note}${warn}</div>`;
}

// ── Field helpers ─────────────────────────────────────────────────────────────
function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;'); }
function toggleHow(id) {
  const el = document.getElementById('how-'+id);
  if (el) el.style.display = el.style.display === 'block' ? 'none' : 'block';
}
function field(id, label, opts) {
  opts = opts || {};
  const req = opts.required !== false;
  const optLbl = req ? '' : '<span class="opt">(optional)</span>';
  const hint = opts.hint ? `<div class="hint">${opts.hint}</div>` : '';
  const howLnk = opts.how ? `<a class="how-link" onclick="toggleHow('${id}')">How do I find this?</a>` : '';
  const howBox = opts.how ? `<div class="how-box" id="how-${id}">${opts.how}</div>` : '';
  const val = formData[id] ? ` value="${esc(formData[id])}"` : '';
  const errMsg = opts.errMsg || 'This field is required';
  return `<div class="field" id="f-${id}">
    <label for="${id}">${label}${optLbl}${howLnk}</label>
    ${hint}${howBox}
    <input type="text" id="${id}"${val} autocomplete="off">
    <div class="errmsg" id="e-${id}">${errMsg}</div>
  </div>`;
}
function selectField(id, label, options) {
  const sel = formData[id] || '';
  const opts = options.map(function(o){ return `<option value="${esc(o[0])}"${o[0]===sel?' selected':''}>${esc(o[1])}</option>`; }).join('');
  return `<div class="field"><label for="${id}">${label}</label><select id="${id}">${opts}</select></div>`;
}

// ── Dynamic lists ─────────────────────────────────────────────────────────────
function saveStakeholders() {
  stakeholders.forEach(function(s, i) {
    var n = document.getElementById('sh_name_'+i);
    var t = document.getElementById('sh_title_'+i);
    var no = document.getElementById('sh_note_'+i);
    if (n)  s.name  = n.value.trim();
    if (t)  s.title = t.value.trim();
    if (no) s.note  = no.value.trim();
  });
}
function renderStakeholders() {
  var c = document.getElementById('stakeholders-list');
  if (!c) return;
  c.innerHTML = stakeholders.map(function(s, i) {
    var rm = stakeholders.length > 1
      ? `<button class="ditem-rm" onclick="removeStakeholder(${i})" type="button">&times;</button>` : '';
    return `<div class="ditem">
      <div class="ditem-hdr"><span class="ditem-lbl">Stakeholder ${i+1}</span>${rm}</div>
      <div class="field-row">
        <div class="field"><label>Name</label>
          <input type="text" id="sh_name_${i}" value="${esc(s.name)}" autocomplete="off" placeholder="e.g. Sarah">
        </div>
        <div class="field"><label>Title</label>
          <input type="text" id="sh_title_${i}" value="${esc(s.title)}" autocomplete="off" placeholder="e.g. CRO">
        </div>
      </div>
      <div class="field"><label>Working note <span class="opt">(optional)</span></label>
        <input type="text" id="sh_note_${i}" value="${esc(s.note)}" autocomplete="off"
               placeholder="e.g. Move fast, prefers Slack">
      </div>
    </div>`;
  }).join('');
}
function addStakeholder() {
  saveStakeholders();
  stakeholders.push({name:'', title:'', note:''});
  renderStakeholders();
  var el = document.getElementById('sh_name_'+(stakeholders.length-1));
  if (el) el.focus();
}
function removeStakeholder(i) {
  saveStakeholders();
  stakeholders.splice(i, 1);
  renderStakeholders();
}

function saveNofly() {
  noflyEmails = noflyEmails.map(function(_, i) {
    var el = document.getElementById('nf_'+i);
    return el ? el.value.trim() : '';
  });
  var cb = document.getElementById('nofly-never-cb');
  if (cb) noflyNever = cb.checked;
}
function renderNofly() {
  var c = document.getElementById('nofly-list');
  if (!c) return;
  var disabled = noflyNever;
  c.innerHTML = noflyEmails.map(function(v, i) {
    var rm = noflyEmails.length > 1
      ? `<button class="ditem-rm" onclick="removeNofly(${i})" type="button" style="flex-shrink:0"${disabled?' disabled':''}>×</button>` : '';
    return `<div style="display:flex;gap:8px;margin-bottom:8px;align-items:center;opacity:${disabled?0.35:1}">
      <input type="email" id="nf_${i}" value="${esc(v)}" placeholder="name@company.com"
             style="flex:1;padding:10px 13px;border:1.5px solid #d2d2d7;border-radius:9px;font-size:14px;outline:none"
             ${disabled?'disabled':''}>
      ${rm}
    </div>`;
  }).join('');
  var addBtn = document.getElementById('nofly-add-btn');
  if (addBtn) addBtn.disabled = disabled;
}
function toggleNoflyNever() {
  var cb = document.getElementById('nofly-never-cb');
  noflyNever = cb ? cb.checked : false;
  renderNofly();
}
function addNofly() {
  saveNofly();
  noflyEmails.push('');
  renderNofly();
  var el = document.getElementById('nf_'+(noflyEmails.length-1));
  if (el) el.focus();
}
function removeNofly(i) {
  saveNofly();
  noflyEmails.splice(i, 1);
  renderNofly();
}

function saveDirectReports() {
  directReports.forEach(function(d, i) {
    var n = document.getElementById('dr_name_'+i);
    var t = document.getElementById('dr_title_'+i);
    var no = document.getElementById('dr_note_'+i);
    if (n)  d.name  = n.value.trim();
    if (t)  d.title = t.value.trim();
    if (no) d.note  = no.value.trim();
  });
}
function renderDirectReports() {
  var c = document.getElementById('dr-list');
  if (!c) return;
  c.innerHTML = directReports.map(function(d, i) {
    var rm = directReports.length > 1
      ? `<button class="ditem-rm" onclick="removeDirectReport(${i})" type="button">&times;</button>` : '';
    return `<div class="ditem">
      <div class="ditem-hdr"><span class="ditem-lbl">Team member ${i+1}</span>${rm}</div>
      <div class="field-row">
        <div class="field"><label>Name</label>
          <input type="text" id="dr_name_${i}" value="${esc(d.name)}" autocomplete="off">
        </div>
        <div class="field"><label>Title</label>
          <input type="text" id="dr_title_${i}" value="${esc(d.title)}" autocomplete="off">
        </div>
      </div>
      <div class="field"><label>Working note <span class="opt">(optional)</span></label>
        <input type="text" id="dr_note_${i}" value="${esc(d.note)}" autocomplete="off"
               placeholder="e.g. Strong on execution, needs deadlines">
      </div>
    </div>`;
  }).join('');
}
function addDirectReport() {
  saveDirectReports();
  directReports.push({name:'', title:'', note:''});
  renderDirectReports();
  var el = document.getElementById('dr_name_'+(directReports.length-1));
  if (el) el.focus();
}
function removeDirectReport(i) {
  saveDirectReports();
  directReports.splice(i, 1);
  renderDirectReports();
}

// ── Milestones list ───────────────────────────────────────────────────────────
function saveMilestones() {
  milestones.forEach(function(m, i) {
    var n = document.getElementById('ms_name_'+i);
    var d = document.getElementById('ms_desc_'+i);
    var t = document.getElementById('ms_date_'+i);
    if (n) m.name        = n.value.trim();
    if (d) m.description = d.value.trim();
    if (t) m.target_date = t.value.trim();
  });
}
function renderMilestones() {
  var c = document.getElementById('milestones-list');
  if (!c) return;
  c.innerHTML = milestones.map(function(m, i) {
    var rm = milestones.length > 1
      ? `<button class="ditem-rm" onclick="removeMilestone(${i})" type="button">&times;</button>` : '';
    return `<div class="ditem">
      <div class="ditem-hdr"><span class="ditem-lbl">Milestone ${i+1}</span>${rm}</div>
      <div class="field">
        <label>Name</label>
        <input type="text" id="ms_name_${i}" value="${esc(m.name)}" placeholder="e.g. Launch new product line" autocomplete="off">
      </div>
      <div class="field">
        <label>Description <span class="opt">(optional)</span></label>
        <input type="text" id="ms_desc_${i}" value="${esc(m.description)}" placeholder="Plain English — Alfred uses this to find relevant signals" autocomplete="off">
      </div>
      <div class="field">
        <label>Target date <span class="opt">(optional)</span></label>
        <input type="date" id="ms_date_${i}" value="${esc(m.target_date)}">
      </div>
    </div>`;
  }).join('');
}
function addMilestone() {
  saveMilestones();
  milestones.push({name:'', description:'', target_date:''});
  renderMilestones();
  var el = document.getElementById('ms_name_'+(milestones.length-1));
  if (el) el.focus();
}
function removeMilestone(i) {
  saveMilestones();
  milestones.splice(i, 1);
  renderMilestones();
}

// ── Step content ──────────────────────────────────────────────────────────────
function stepContent(i) {
  switch(i) {
    case 0:
      return `<h2>Before we start</h2>
        <p class="desc">Alfred needs Slack and Google Calendar connected. Set them up via <strong>Claude app Settings &rarr; Connectors</strong> (or Claude Code Settings &rarr; Integrations &rarr; MCP Servers), then confirm each one below.</p>
        ${mcpPanel()}
        <div style="font-size:13px;color:#6e6e73;line-height:1.55;margin-top:12px">
          <strong>Also required: Git.</strong> If you don&rsquo;t have Git installed, the installer will detect this and prompt macOS to install it automatically — just follow the pop-up.
        </div>`;

    case 1:
      return `<h2>About you</h2>
        <p class="desc">Basic info Alfred needs to personalize your briefs.</p>
        <div class="field-row">
          ${field('name','Your full name')}
          ${field('email','Work email')}
        </div>
        ${field('company','Company name')}
        ${field('role','Your role',{hint:'One sentence, e.g. "Sr Director of AI GTM at Acme"'})}
        ${field('mission','Your mission',{hint:'What are you responsible for? e.g. "Building the AI-first revenue org"'})}
        ${field('product','Main product or initiative',{required:false,hint:'e.g. "Acme Pro" — Alfred uses this to track signals. You can add this later.'})}
        ${field('slack_uid','Slack user ID',{
          how:'Open Slack &rarr; click your avatar &rarr; <strong>Profile</strong> &rarr; <strong>&middot;&middot;&middot;</strong> menu &rarr; <strong>Copy member ID</strong>. Starts with U.',
          errMsg:'Must start with U'})}
        ${field('slack_ws','Slack workspace ID',{
          required:false,
          how:'In Slack: click workspace name (top-left) &rarr; <strong>Settings &amp; administration</strong> &rarr; <strong>Workspace settings</strong>. ID is in the URL, starts with T. Requires workspace admin access — skip if you don&rsquo;t have it.',
          errMsg:'Must start with T'})}`;

    case 2:
      return `<h2>Key people</h2>
        <p class="desc">Tell Alfred whose asks create fires, and who owns the calendar.</p>

        <div class="sub-h">Your manager</div>
        <p class="sub-p">Used for calendar rules and priority filtering.</p>
        <div class="field-row">
          ${field('mgr_name','Name')}
          ${field('mgr_title','Title')}
        </div>
        ${field('mgr_note','Working note',{required:false,hint:'e.g. "Prefers written updates, slower pace"'})}

        <hr class="sep">

        <div class="sub-h">Key stakeholders</div>
        <p class="sub-p">People whose Slack messages Alfred watches for urgent asks and blockers.</p>
        <div id="stakeholders-list"></div>
        <button class="add-btn" onclick="addStakeholder()" type="button">+ Add another stakeholder</button>

        <hr class="sep">

        <div class="sub-h">No-fly list</div>
        <div class="nofly-box">
          <span class="nofly-icon">&#128065;</span>
          <span>Alfred will <strong>never schedule a calendar invite</strong> to anyone on this list. Add executives or anyone who requires EA scheduling — so Alfred knows to flag it rather than book directly.</span>
        </div>
        <label style="display:flex;align-items:center;gap:10px;margin-bottom:14px;font-size:14px;cursor:pointer;user-select:none">
          <input type="checkbox" id="nofly-never-cb" ${noflyNever?'checked':''} onchange="toggleNoflyNever()"
                 style="width:16px;height:16px;cursor:pointer;accent-color:#F5C518">
          <span>Alfred should <strong>never</strong> send a calendar invite on my behalf to anyone</span>
        </label>
        <div id="nofly-list"></div>
        <button class="add-btn" id="nofly-add-btn" onclick="addNofly()" type="button">+ Add another email</button>`;

    case 3:
      return `<h2>Your team</h2>
        <p class="desc">Alfred tracks commitments and weekly status from these people.</p>
        <div id="dr-list"></div>
        <button class="add-btn" onclick="addDirectReport()" type="button">+ Add another team member</button>`;

    case 4:
      return `<h2>Goals &amp; milestones</h2>
        <p class="desc">Alfred tracks progress signals for each milestone every brief — searching Slack, meetings, and email for what's moving and what's at risk.</p>
        ${field('rollout_date','Main initiative target date',{
          required:false,
          hint:'YYYY-MM-DD — powers the "Days to rollout" countdown in your brief. e.g. 2026-07-01'})}
        <hr class="sep">
        <div class="sub-h">Milestones</div>
        <p class="sub-p">Specific checkpoints Alfred watches each run.</p>
        <div id="milestones-list"></div>
        <button class="add-btn" onclick="addMilestone()" type="button">+ Add another milestone</button>
        <p style="font-size:13px;color:#6e6e73;margin-top:16px">You can skip this and add milestones later from the 🏁 button in your brief.</p>`;

    case 5:
      return `<h2>Timezone &amp; save location</h2>
        <p class="desc">When and where Alfred delivers your briefs.</p>
        ${selectField('timezone','Your timezone',TIMEZONE_OPTIONS)}
        ${field('briefs_dir','Where to save briefs',{required:false,hint:'Leave blank to use the default: ~/Documents/Alfred Briefs (created automatically)'})}`;

    default: return '';
  }
}

// ── Validation ────────────────────────────────────────────────────────────────
const REQUIRED_SCALAR = {
  1: ['name','email','company','role','mission','slack_uid'],
  2: ['mgr_name','mgr_title'],
  3: [],
  4: [],
};

function validate() {
  var required = REQUIRED_SCALAR[step] || [];
  var ok = true;
  required.forEach(function(id) {
    var el = document.getElementById(id);
    if (!el) return;
    var val = el.value.trim();
    var err = !val;
    if (id === 'slack_uid' && val && val[0] !== 'U') err = true;
    if (id === 'slack_ws'  && val && val[0] !== 'T') err = true;
    el.classList.toggle('err', err);
    var em = document.getElementById('e-'+id);
    if (em) em.style.display = err ? 'block' : 'none';
    if (err) ok = false;
  });
  // Dynamic array validation
  if (step === 2) {
    var n0 = document.getElementById('sh_name_0');
    var t0 = document.getElementById('sh_title_0');
    if (n0 && !n0.value.trim()) { n0.classList.add('err'); ok = false; }
    if (t0 && !t0.value.trim()) { t0.classList.add('err'); ok = false; }
  }
  if (step === 3) {
    var dn0 = document.getElementById('dr_name_0');
    var dt0 = document.getElementById('dr_title_0');
    if (dn0 && !dn0.value.trim()) { dn0.classList.add('err'); ok = false; }
    if (dt0 && !dt0.value.trim()) { dt0.classList.add('err'); ok = false; }
  }
  return ok;
}

function collectStep() {
  if (step === 2) { saveStakeholders(); saveNofly(); }
  if (step === 3) { saveDirectReports(); }
  if (step === 4) { saveMilestones(); }
  var ids = ['name','email','company','role','mission','product','slack_uid','slack_ws',
             'mgr_name','mgr_title','mgr_note','rollout_date','timezone','briefs_dir'];
  ids.forEach(function(id) {
    var el = document.getElementById(id);
    if (el && el.value.trim()) formData[id] = el.value.trim();
    else if (el) delete formData[id];
  });
}

// ── Review ────────────────────────────────────────────────────────────────────
function reviewContent() {
  var nfList  = noflyNever ? 'Never send any calendar invites'
              : noflyEmails.filter(function(e){return e;}).join(', ') || '—';
  var stkList = stakeholders.filter(function(s){return s.name;})
                            .map(function(s){return s.name + (s.title ? ' ('+s.title+')' : '');})
                            .join(', ') || '—';
  var drList  = directReports.filter(function(d){return d.name;})
                             .map(function(d){return d.name + (d.title ? ' ('+d.title+')' : '');})
                             .join(', ') || '—';
  var msList = milestones.filter(function(m){return m.name;})
                         .map(function(m){return m.name + (m.target_date ? ' → '+m.target_date : '');})
                         .join(', ') || '—';
  var rows = [
    ['Name',          formData.name||'—'],
    ['Email',         formData.email||'—'],
    ['Company',       formData.company||'—'],
    ['Role',          formData.role||'—'],
    ['Slack user ID', formData.slack_uid||'—'],
    ['Manager',       formData.mgr_name ? formData.mgr_name+' — '+formData.mgr_title : '—'],
    ['Stakeholders',  stkList],
    ['No-fly list',   nfList],
    ['Team',          drList],
    ['Milestones',    msList],
    ['Product',       formData.product||'—'],
    ['Timezone',      formData.timezone||'America/New_York'],
    ['Briefs saved to', formData.briefs_dir||'~/Documents/Alfred Briefs'],
  ];
  var tableRows = rows.map(function(r){return '<tr><td>'+r[0]+'</td><td>'+esc(r[1])+'</td></tr>';}).join('');
  return `<h2>Review your answers</h2>
    <p class="desc">Everything look right? Click <strong>Install Alfred</strong> to write all files.</p>
    <table class="rtable">${tableRows}</table>`;
}

// ── Install ───────────────────────────────────────────────────────────────────
function startInstall() {
  step = INSTALL_STEP;
  renderStep();
  var payload = {
    name:           formData.name||'',
    email:          formData.email||'',
    company:        formData.company||'',
    role:           formData.role||'',
    mission:        formData.mission||'',
    product:        formData.product||'',
    slack_uid:      formData.slack_uid||'',
    slack_ws:       formData.slack_ws||'',
    mgr_name:       formData.mgr_name||'',
    mgr_title:      formData.mgr_title||'',
    mgr_note:       formData.mgr_note||'',
    rollout_date:   formData.rollout_date||'',
    stakeholders:   stakeholders,
    nofly_emails:   noflyEmails.filter(function(e){return e;}),
    nofly_never:    noflyNever,
    direct_reports: directReports,
    milestones:     milestones.filter(function(m){return m.name;}),
    timezone:       formData.timezone||'America/New_York',
    briefs_dir:     formData.briefs_dir||'',
  };
  fetch('/api/install', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload),
  }).then(function(res) {
    var reader = res.body.getReader();
    var dec = new TextDecoder();
    var buf = '';
    function pump() {
      reader.read().then(function(chunk) {
        if (chunk.done) return;
        buf += dec.decode(chunk.value, {stream:true});
        var lines = buf.split('\\n');
        buf = lines.pop();
        lines.forEach(function(line) {
          if (!line.startsWith('data: ')) return;
          try {
            var msg = JSON.parse(line.slice(6));
            if (msg.type === 'progress') appendLog(msg.msg, msg.level);
            else if (msg.type === 'done')  showDone(msg.prompt, msg.clipboard);
            else if (msg.type === 'error') appendLog('Error: ' + msg.msg, 'warn');
          } catch(e) {}
        });
        pump();
      });
    }
    pump();
  }).catch(function(e) { appendLog('Error: ' + e, 'warn'); });
}

function appendLog(msg, level) {
  var log = document.getElementById('plog');
  if (!log) return;
  var div = document.createElement('div');
  div.className = level || 'info';
  div.textContent = msg;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function showDone(prompt, clipboard) {
  step = DONE_STEP;
  renderStep();
  document.getElementById('finish-prompt').textContent = prompt;
  if (clipboard) {
    document.getElementById('clipboard-note').textContent = 'Already copied to your clipboard';
    document.getElementById('clipboard-note').className = 'copy-note ok';
  }
}

function copyPrompt() {
  var text = document.getElementById('finish-prompt').textContent;
  navigator.clipboard.writeText(text).then(function() {
    document.getElementById('clipboard-note').textContent = 'Copied!';
    document.getElementById('clipboard-note').className = 'copy-note ok';
  });
}

// ── Render ────────────────────────────────────────────────────────────────────
function renderStep() {
  renderStepBar();
  var card = document.getElementById('card');
  var content, btnrow;

  if (step === DONE_STEP) {
    card.innerHTML = `<div class="done-hero">
        <div class="icon">&#x1F987;</div>
        <h2>Alfred is installed!</h2>
        <p>One last step — paste the prompt below into Claude Code to register your scheduled tasks and generate your first brief.</p>
      </div>
      <div style="font-size:13px;font-weight:600;margin-bottom:8px">How to finish:</div>
      <ol style="font-size:13px;color:#3d3d3f;line-height:2;padding-left:20px">
        <li>Open <strong>Claude Code</strong></li>
        <li>Press <strong>Cmd+N</strong> to start a new session</li>
        <li>Press <strong>Cmd+V</strong> to paste, then Enter</li>
      </ol>
      <div class="prompt-box">
        <div style="font-size:12px;font-weight:600;color:#6e6e73;margin-bottom:8px">Finish-setup prompt</div>
        <pre id="finish-prompt"></pre>
        <div class="copy-row">
          <button class="btn btn-primary" onclick="copyPrompt()">Copy to Clipboard</button>
          <span class="copy-note" id="clipboard-note"></span>
        </div>
      </div>`;
    return;
  }

  if (step === INSTALL_STEP) {
    card.innerHTML = `<h2>Installing Alfred…</h2>
      <p class="desc" style="margin-bottom:16px">This takes about 15 seconds.</p>
      <div class="plog" id="plog"></div>`;
    return;
  }

  if (step === REVIEW_STEP) {
    content = reviewContent();
    btnrow = `<div class="btnrow">
      <button class="btn btn-ghost" onclick="goBack()">&#8592; Back</button>
      <button class="btn btn-primary" onclick="startInstall()">Install Alfred</button>
    </div>`;
  } else {
    content = stepContent(step);
    var isFirst  = step === 0;
    var isLast   = step === STEPS.length;
    var nextLabel = isLast ? 'Review &#8594;' : isFirst ? 'Get Started &#8594;' : 'Next &#8594;';
    btnrow = `<div class="btnrow">
      ${isFirst ? '<div></div>' : '<button class="btn btn-ghost" onclick="goBack()">&#8592; Back</button>'}
      <button class="btn btn-primary" onclick="goNext()">${nextLabel}</button>
    </div>`;
  }

  card.innerHTML = content + btnrow;

  // Init dynamic sections
  if (step === 2) { renderStakeholders(); renderNofly(); }
  if (step === 3) { renderDirectReports(); }
  if (step === 4) { renderMilestones(); }

  // Re-apply select values
  Object.keys(formData).forEach(function(id) {
    var el = document.getElementById(id);
    if (el && el.tagName === 'SELECT') el.value = formData[id];
  });
}

function goNext() {
  collectStep();
  if (!validate()) return;
  step++;
  if (step > REVIEW_STEP) step = REVIEW_STEP;
  renderStep();
  window.scrollTo(0, 0);
}

function goBack() {
  step = Math.max(0, step - 1);
  renderStep();
  window.scrollTo(0, 0);
}

// ── Boot ──────────────────────────────────────────────────────────────────────
const TIMEZONE_OPTIONS = TIMEZONE_OPTIONS_PLACEHOLDER;
window._homeDir = HOME_DIR_PLACEHOLDER;

renderStep();
loadMCPs();
</script>
</body>
</html>
"""


def build_html():
    """Inject server-side values into the HTML template."""
    tz_js = "[" + ",".join(f'["{tz}","{label}"]' for tz, label in TIMEZONES) + "]"
    home_js = f'"{str(Path.home())}"'
    html = HTML_PAGE.replace("TIMEZONE_OPTIONS_PLACEHOLDER", tz_js)
    html = html.replace("HOME_DIR_PLACEHOLDER", home_js)
    return html


# ─── HTTP server ──────────────────────────────────────────────────────────────

_html_cache = None

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence default request logging

    def do_GET(self):
        global _html_cache
        if self.path in ('/', '/index.html'):
            if _html_cache is None:
                _html_cache = build_html().encode()
            self._send(200, 'text/html; charset=utf-8', _html_cache)
        elif self.path == '/api/detect-mcps':
            prefixes = detect_mcp_ids()
            svc_labels = {
                "slack":    ("Slack",           True),
                "gmail":    ("Gmail",            False),
                "calendar": ("Google Calendar",  True),
                "drive":    ("Google Drive",     False),
                "granola":  ("Granola",          False),
            }
            result = {
                svc: {"label": label, "detected": svc in prefixes, "required": req}
                for svc, (label, req) in svc_labels.items()
            }
            data = json.dumps(result).encode()
            self._send(200, 'application/json', data)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != '/api/install':
            self.send_error(404)
            return
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        q = queue.Queue()

        def emit(msg, level='info'):
            q.put({'type': 'progress', 'msg': msg, 'level': level})

        def worker():
            try:
                result = run_install(body, emit)
                q.put({'type': 'done', **result})
            except Exception as e:
                q.put({'type': 'error', 'msg': str(e)})

        threading.Thread(target=worker, daemon=True).start()

        while True:
            item = q.get()
            line = f"data: {json.dumps(item)}\n\n"
            try:
                self.wfile.write(line.encode())
                self.wfile.flush()
            except Exception:
                break
            if item['type'] in ('done', 'error'):
                break

    def _send(self, code, ctype, data):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)


# ─── Entry point ──────────────────────────────────────────────────────────────

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def main():
    port = find_free_port()
    url  = f"http://localhost:{port}"

    print(f"\n  🦇  Alfred Setup")
    print(f"  ──────────────────────────────────────")
    print(f"  Open this URL in your browser:")
    print(f"  {url}")
    print(f"  ──────────────────────────────────────")
    print(f"  (Press Ctrl+C to quit)\n")

    server = http.server.HTTPServer(('127.0.0.1', port), Handler)

    def open_browser():
        import subprocess
        try:
            subprocess.Popen(['open', url])  # macOS native open
        except Exception:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    threading.Timer(0.8, open_browser).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Setup cancelled.\n")


if __name__ == "__main__":
    main()
