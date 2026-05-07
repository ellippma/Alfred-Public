#!/usr/bin/env python3
"""
alfred-setup.py
Installs Alfred — your personal AI Chief of Staff — for a new user.
Detects MCP tool IDs, collects config, installs all files, and generates
a finish-setup prompt to paste into Claude Code.

Usage: python3 alfred-setup.py
"""

import json, os, re, shutil, sys
from pathlib import Path
from datetime import datetime

# ── Constants ────────────────────────────────────────────────────────────────

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

# Tools Alfred actually calls — pre-approved during install so user never sees prompts
ALFRED_TOOLS = {
    "slack":    ["slack_search_channels", "slack_search_public_and_private", "slack_send_message_draft"],
    "calendar": ["list_events", "create_event"],
    "gmail":    ["search_threads", "create_draft"],
    "drive":    ["search_files", "list_recent_files"],
    "granola":  ["list_meetings", "query_granola_meetings"],
}
FIXED_PERMISSIONS = [
    "mcp__granola__list_meetings",
    "mcp__granola__query_granola_meetings",
    "mcp__scheduled-tasks__create_scheduled_task",
    "mcp__scheduled-tasks__list_scheduled_tasks",
    "mcp__scheduled-tasks__update_scheduled_task",
]

COMMON_TIMEZONES = {
    "1": ("America/New_York",    "Eastern"),
    "2": ("America/Chicago",     "Central"),
    "3": ("America/Denver",      "Mountain"),
    "4": ("America/Los_Angeles", "Pacific"),
    "5": ("America/Phoenix",     "Arizona (no DST)"),
    "6": ("Europe/London",       "London"),
    "7": ("Europe/Berlin",       "Central Europe"),
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def banner(text):
    print(f"\n{'─'*50}")
    print(f"  {text}")
    print(f"{'─'*50}")

def ask(prompt, default=None, required=True):
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"  {prompt}{suffix}: ").strip()
        if not val and default:
            return default
        if val or not required:
            return val
        print("  ⚠  This field is required.")

def ask_list(prompt, example=""):
    hint = f" (comma-separated{', e.g. ' + example if example else ''})"
    raw = input(f"  {prompt}{hint}: ").strip()
    return [x.strip() for x in raw.split(",") if x.strip()]

def validate_slack_uid(uid):
    if uid and not uid.startswith("U"):
        print(f"  ⚠  Slack user IDs start with U (e.g. U012AB3CD456). Got: {uid}")
        return False
    return True

def validate_slack_workspace(ws):
    if ws and not ws.startswith("T"):
        print(f"  ⚠  Slack workspace IDs start with T (e.g. T012AB3CD). Got: {ws}")
        return False
    return True

def claude_project_segment():
    """Convert home path to Claude Code project directory name.
    /Users/john.doe → -Users-john-doe (slashes and dots become dashes)
    """
    return str(Path.home()).replace("/", "-").replace(".", "-")

def detect_mcp_ids():
    """
    Parse Claude settings files to extract MCP service prefixes.
    Checks both settings.local.json (manual) and settings.json (UI-connected).
    Returns dict: service_name → tool_prefix (e.g. 'slack' → 'mcp__UUID__')
    """
    prefixes = {}
    settings_files = [
        CLAUDE_DIR / "settings.local.json",
        CLAUDE_DIR / "settings.json",
    ]
    for settings_file in settings_files:
        if not settings_file.exists():
            continue
        try:
            data = json.loads(settings_file.read_text())
            # Check permissions/allow list
            allowed = data.get("permissions", {}).get("allow", [])
            # Also check mcpServers keys for service names
            mcp_servers = data.get("mcpServers", {})
            for server_name in mcp_servers:
                prefix = f"mcp__{server_name}__"
                for service, tool_hints in KNOWN_SERVICES.items():
                    if service not in prefixes and any(hint in server_name.lower() for hint in [service, service.replace("_", "")]):
                        prefixes[service] = prefix
            for entry in allowed:
                if not entry.startswith("mcp__"):
                    continue
                parts = entry.split("__", 2)
                if len(parts) < 3:
                    continue
                prefix = f"mcp__{parts[1]}__"
                tool   = parts[2]
                for service, tool_hints in KNOWN_SERVICES.items():
                    if any(hint in tool for hint in tool_hints):
                        if service not in prefixes:
                            prefixes[service] = prefix
        except Exception:
            pass
    # scheduled-tasks and ccd_session are Claude Code built-ins — always present.
    # Granola is detected via alias matching above; don't hardcode it.
    for svc in ["scheduled-tasks", "ccd_session"]:
        prefixes[svc] = f"mcp__{svc}__"
    return prefixes

def fill_template(text, config):
    """Replace all {{KEY}} placeholders with values from config dict."""
    def replacer(m):
        key = m.group(1)
        return config.get(key, m.group(0))  # leave unreplaced if missing
    return re.sub(r"\{\{([A-Z0-9_]+)\}\}", replacer, text)

def install_template(src, dst, config):
    """Read .template file, fill placeholders, write to dst."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = Path(src).read_text()
    dst.write_text(fill_template(text, config))
    print(f"    ✅  {dst}")

# ── Setup steps ───────────────────────────────────────────────────────────────

def _build_milestones_list(product, rollout_date, company):
    """Build the initial milestones.md block from wizard inputs."""
    if not product:
        return "<!-- No milestones added yet — manage them from the 🏁 MILESTONES button in your Alfred brief -->"
    target = rollout_date or "TBD"
    return (
        f"## {product} Rollout\n"
        f"**Description:** Roll out {product} across {company}\n"
        f"**Target date:** {target}\n"
        f"**Status:** active"
    )


def collect_config():
    banner("Step 1 — About you")
    name     = ask("Your full name")
    email    = ask("Your work email")
    company  = ask("Company name")
    role     = ask("Your role (one sentence, e.g. 'VP of Sales at Acme')")
    mission  = ask("Your mission / what you're responsible for (one sentence)")

    while True:
        slack_uid = ask("Your Slack user ID (open Slack → profile → ··· → Copy member ID)")
        if validate_slack_uid(slack_uid):
            break

    while True:
        slack_ws = ask("Your Slack workspace ID (optional — requires workspace admin access; starts with T)", required=False)
        if not slack_ws or validate_slack_workspace(slack_ws):
            break

    banner("Step 2 — Key stakeholders")
    print("  These are the people whose requests define a 'fire' for you.")
    t1_name1  = ask("Top stakeholder #1 name (e.g. your CEO or CRO)")
    t1_title1 = ask(f"  {t1_name1}'s title")
    t1_note1  = ask(f"  One-line note on how to work with {t1_name1}", required=False)
    t1_name2  = ask("Top stakeholder #2 name (or press Enter to skip)", required=False)
    t1_title2 = ask(f"  {t1_name2}'s title", required=False) if t1_name2 else ""
    t1_note2  = ask(f"  One-line note on working with {t1_name2}", required=False) if t1_name2 else ""
    mgr_name  = ask("Your manager's name")
    mgr_title = ask(f"  {mgr_name}'s title")
    mgr_note  = ask(f"  One-line note on working with {mgr_name}", required=False)
    nofly1    = ask("Calendar no-fly #1 (C-suite who needs EA scheduling, e.g. your CEO)", required=False)
    nofly2    = ask("Calendar no-fly #2 (another exec, or press Enter to skip)", required=False)
    nofly3    = ask("Calendar no-fly #3 (or press Enter to skip)", required=False)

    banner("Step 3 — Your team")
    dr1_name  = ask("Direct report / key peer #1 name")
    dr1_title = ask(f"  {dr1_name}'s title")
    dr2_name  = ask("Direct report / key peer #2 name (or press Enter to skip)", required=False)
    dr2_title = ask(f"  {dr2_name}'s title", required=False) if dr2_name else ""

    banner("Step 4 — Your main product / initiative to track")
    product      = ask("What's the main product or initiative Alfred should track? (e.g. 'Elixir')")
    rollout_date = ask("Target delivery / rollout date for that initiative (YYYY-MM-DD)", required=False)
    q_label      = ask("Current quarter label (e.g. 'Q2 2026')", default=f"Q{((datetime.today().month-1)//3)+1} {datetime.today().year}")

    banner("Step 5 — Paths & timezone")

    print("\n  Timezone options:")
    for num, (tz, label) in COMMON_TIMEZONES.items():
        print(f"    {num}. {label} ({tz})")
    tz_choice = ask("Enter number (or type a timezone like America/Chicago)", default="1")
    if tz_choice in COMMON_TIMEZONES:
        timezone = COMMON_TIMEZONES[tz_choice][0]
    else:
        timezone = tz_choice

    briefs_dir = ask("Where should Alfred save briefs?", default=str(Path.home() / "Documents" / "Alfred Briefs"))
    repo_dir   = ask("Path to your alfred-repo clone", default=str(ALFRED_REPO))

    # Escape spaces for use in bash commands
    briefs_dir_esc = briefs_dir.replace(" ", "\\ ")

    # ── Build composite placeholders ─────────────────────────────────────────
    # Tier-1 stakeholders list (markdown bullets for stakeholders.md)
    tier1_entries = [(t1_name1, t1_title1, t1_note1 or "")]
    if t1_name2:
        tier1_entries.append((t1_name2, t1_title2, t1_note2 or ""))
    stakeholders_list = "\n".join(
        f"- **{n}** — {t}. {note}" for n, t, note in tier1_entries
    ) or "- (none set)"

    # No-fly list
    nofly_entries = [e for e in [nofly1, nofly2, nofly3] if e]
    nofly_list    = ", ".join(nofly_entries) if nofly_entries else ""
    nofly_list_md = "\n".join(f"- {e}" for e in nofly_entries) if nofly_entries else "- (none set)"

    # Direct reports (markdown bullets and inline)
    dr_entries = [(dr1_name, dr1_title)]
    if dr2_name:
        dr_entries.append((dr2_name, dr2_title))
    direct_reports_list   = "\n".join(
        f"- **{n}** — {t}. Track commitments closely." for n, t in dr_entries
    )
    direct_reports_inline = " + ".join(n for n, _ in dr_entries) or "team"

    # Milestones block
    milestones_list = _build_milestones_list(product, rollout_date, company)

    return {
        "USER_NAME":              name,
        "USER_EMAIL":             email,
        "COMPANY":                company,
        "USER_ROLE":              role,
        "USER_MISSION":           mission,
        "SLACK_USER_ID":          slack_uid,
        "SLACK_WORKSPACE_ID":     slack_ws,
        "TIER1_NAME_1":           t1_name1,
        "TIER1_TITLE_1":          t1_title1,
        "TIER1_NOTE_1":           t1_note1 or "",
        "TIER1_NAME_2":           t1_name2 or t1_name1,
        "TIER1_TITLE_2":          t1_title2 or t1_title1,
        "TIER1_NOTE_2":           t1_note2 or "",
        "MANAGER_NAME":           mgr_name,
        "MANAGER_TITLE":          mgr_title,
        "MANAGER_NOTE":           mgr_note or "",
        "NOFLY_1":                nofly1 or "",
        "NOFLY_2":                nofly2 or "",
        "NOFLY_3":                nofly3 or "",
        "NOFLY_LIST":             nofly_list,
        "NOFLY_LIST_MD":          nofly_list_md,
        "STAKEHOLDERS_LIST":      stakeholders_list,
        "DIRECT_REPORT_1":        dr1_name,
        "DIRECT_REPORT_1_TITLE":  dr1_title,
        "DIRECT_REPORT_2":        dr2_name or "",
        "DIRECT_REPORT_2_TITLE":  dr2_title or "",
        "DIRECT_REPORTS_LIST":    direct_reports_list,
        "DIRECT_REPORTS_INLINE":  direct_reports_inline,
        "MILESTONES_LIST":        milestones_list,
        "PRODUCT_NAME":           product,
        "ROLLOUT_DATE":           rollout_date or "",
        "CURRENT_QUARTER":        q_label,
        "TIMEZONE":               timezone,
        "BRIEFS_DIR":             briefs_dir,
        "BRIEFS_DIR_ESC":         briefs_dir_esc,
        "REPO_DIR":               repo_dir,
        "HOME_DIR":               str(Path.home()),
        "SLACK_SIGNAL_FILTER":    f"Surface signals relevant to {product} and {role}. Filter out deal-specific noise unless it involves {t1_name1} or {mgr_name}.",
        "INITIATIVE_1_NAME":      product,
        "INITIATIVE_1_DESC":      f"Rolling out {product} across {company}",
        "INITIATIVE_1_METRIC":    "Adoption rate, active usage",
        "INITIATIVE_1_DATE":      rollout_date or "TBD",
    }


def detect_mcps(config):
    banner("Detecting MCP tools")
    prefixes = detect_mcp_ids()
    available = []

    service_display = {
        "slack":    "Slack",
        "gmail":    "Gmail",
        "calendar": "Google Calendar",
        "drive":    "Google Drive",
        "granola":  "Granola",
    }

    for svc, label in service_display.items():
        if svc in prefixes:
            print(f"    ✅  {label} ({prefixes[svc]})")
            available.append(svc)
        else:
            req = "(REQUIRED)" if svc in ("slack", "calendar") else "(recommended)"
            print(f"    ⚠️   {label} — not detected {req}")

    # Warn but don't block — UI-connected MCPs may not be auto-detectable
    missing_required = [s for s in ("slack", "calendar") if s not in prefixes]
    if missing_required:
        print(f"""
  ⚠️   Could not auto-detect: {', '.join(service_display[s] for s in missing_required)}
  If they're connected in Claude Code (green dot), this is fine — continuing.
  Alfred will use placeholder IDs that Claude Code will resolve at runtime.
""")

    # Inject prefixes into config
    config["MCP_SLACK"]    = prefixes.get("slack",    "mcp__REPLACE_SLACK_ID__")
    config["MCP_GMAIL"]    = prefixes.get("gmail",    "mcp__REPLACE_GMAIL_ID__")
    config["MCP_CALENDAR"] = prefixes.get("calendar", "mcp__REPLACE_CALENDAR_ID__")
    config["MCP_DRIVE"]    = prefixes.get("drive",    "mcp__REPLACE_DRIVE_ID__")
    config["MCP_GRANOLA"]  = prefixes.get("granola",  "mcp__granola__")
    config["MCP_AVAILABLE"] = ", ".join(available)

    return config, available, prefixes


def pre_populate_permissions(prefixes):
    """Write all Alfred tool permissions to settings.local.json so Claude never prompts for Allow."""
    banner("Pre-approving tool permissions")

    entries = list(FIXED_PERMISSIONS)
    for svc, tools in ALFRED_TOOLS.items():
        prefix = prefixes.get(svc)
        if not prefix:
            continue
        for tool in tools:
            entries.append(f"{prefix}{tool}")

    # Read existing file or start fresh
    if SETTINGS_LOCAL.exists():
        try:
            data = json.loads(SETTINGS_LOCAL.read_text())
        except Exception:
            data = {}
    else:
        data = {}

    perms = data.setdefault("permissions", {})
    existing = set(perms.get("allow", []))
    new_entries = [e for e in entries if e not in existing]

    if new_entries:
        perms["allow"] = sorted(existing | set(entries))
        SETTINGS_LOCAL.write_text(json.dumps(data, indent=2))
        print(f"    ✅  Pre-approved {len(new_entries)} tool permission(s) — Alfred will never ask for Allow")
    else:
        print(f"    ✅  All tool permissions already approved")


def install_files(config):
    banner("Installing files")
    briefs_dir   = Path(config["BRIEFS_DIR"]).expanduser()
    segment      = claude_project_segment()
    memory_dir   = CLAUDE_DIR / "projects" / segment / "memory"
    tasks_dir    = CLAUDE_DIR / "scheduled-tasks"
    commands_dir = CLAUDE_DIR / "commands"

    briefs_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    commands_dir.mkdir(parents=True, exist_ok=True)

    config["MEMORY_DIR"]             = str(memory_dir)
    config["CLAUDE_PROJECT_SEGMENT"] = segment

    # Renderer files (no templating needed — copy as-is)
    print("\n  Renderer:")
    renderer_files = ["alfred-build.py", "alfred-template.html", "read-notepad.py"]
    for fname in renderer_files:
        src = ALFRED_REPO / "renderer" / fname
        dst = briefs_dir / fname
        if src.exists():
            shutil.copy2(src, dst)
            print(f"    ✅  {dst}")
        else:
            print(f"    ⚠️   {src} not found — skipping")

    # Copy batman logo so alfred-build.py can reference it with a correct absolute path
    logo_src = ALFRED_REPO / "batman-logo.png"
    logo_dst = briefs_dir / "batman-logo.png"
    if logo_src.exists():
        shutil.copy2(logo_src, logo_dst)
        print(f"    ✅  {logo_dst}")

    # SKILL.md files
    print("\n  Scheduled tasks:")
    for task in ["morning-brief", "pre-meeting-brief", "friday-wrap"]:
        src = TEMPLATES_DIR / "brain" / task / "SKILL.md.template"
        dst = tasks_dir / task / "SKILL.md"
        if src.exists():
            install_template(src, dst, config)
        else:
            print(f"    ⚠️   {src} not found — skipping")

    # Slash commands
    print("\n  Commands:")
    for cmd in ["alfred", "alfred-config"]:
        src = TEMPLATES_DIR / "commands" / f"{cmd}.md.template"
        if src.exists():
            install_template(src, CLAUDE_DIR / "commands" / f"{cmd}.md", config)
        else:
            print(f"    ⚠️   {cmd}.md.template not found — skipping")

    # Memory files
    print("\n  Memory:")
    # Files regenerated every run — purely derived from wizard inputs.
    memory_templates_always = {
        "user_role.md.template":            "user_role.md",
        "project_initiatives.md.template":  "project_q2_initiatives.md",
        "project_personal_cos.md.template": "project_personal_cos.md",
        "milestones.md.template":           "milestones.md",
        "MEMORY.md.template":               "MEMORY.md",
    }
    # Files written only on first install — preserved on re-run to protect
    # calibrations, trained feedback rules, and hand-edited stakeholder notes.
    memory_templates_preserve = {
        "stakeholders.md.template":         "stakeholders.md",
        "calibrations.md.template":         "calibrations.md",
        "feedback_blindspots.md.template":  "feedback_blindspots.md",
        "delivered.md.template":            "delivered.md",
    }
    for tmpl_name, dst_name in memory_templates_always.items():
        src = TEMPLATES_DIR / "memory" / tmpl_name
        dst = memory_dir / dst_name
        if src.exists():
            install_template(src, dst, config)
        else:
            print(f"    ⚠️   {src} not found — skipping")
    for tmpl_name, dst_name in memory_templates_preserve.items():
        src = TEMPLATES_DIR / "memory" / tmpl_name
        dst = memory_dir / dst_name
        if dst.exists():
            print(f"    ⏭   {dst_name} — already exists, preserved")
        elif src.exists():
            install_template(src, dst, config)
        else:
            print(f"    ⚠️   {src} not found — skipping")

    # Blank rolling files (only if they don't already exist — preserve on re-run)
    for fname, content in [
        ("last_brief.md", "# Last Brief State\n\n(Populated by Alfred after first run)\n"),
    ]:
        dst = memory_dir / fname
        if not dst.exists():
            dst.write_text(content)
            print(f"    ✅  {dst}")
        else:
            print(f"    ⏭   {dst} — already exists, preserved")

    # Validate BRIEFS_DIR is writable
    test_file = briefs_dir / ".alfred-write-test"
    try:
        test_file.write_text("ok")
        test_file.unlink()
    except OSError:
        print(f"\n  ⚠️   Warning: briefs directory may not be writable: {briefs_dir}")

    return memory_dir


TEMPLATE_VAR_KEYS = [
    "USER_NAME","USER_EMAIL","COMPANY","USER_ROLE","SLACK_USER_ID","SLACK_WORKSPACE_ID",
    "TIER1_NAME_1","TIER1_TITLE_1","TIER1_NOTE_1","TIER1_NAME_2","TIER1_TITLE_2","TIER1_NOTE_2",
    "MANAGER_NAME","MANAGER_TITLE","MANAGER_NOTE",
    "NOFLY_1","NOFLY_2","NOFLY_3","NOFLY_LIST","NOFLY_LIST_MD",
    "DIRECT_REPORT_1","DIRECT_REPORT_1_TITLE","DIRECT_REPORT_2","DIRECT_REPORT_2_TITLE",
    "DIRECT_REPORTS_INLINE","DIRECT_REPORTS_LIST","STAKEHOLDERS_LIST",
    "PRODUCT_NAME","ROLLOUT_DATE","CURRENT_QUARTER","TIMEZONE",
    "BRIEFS_DIR","BRIEFS_DIR_ESC","MEMORY_DIR","REPO_DIR","HOME_DIR",
    "MCP_SLACK","MCP_GMAIL","MCP_CALENDAR","MCP_DRIVE","MCP_GRANOLA","MCP_AVAILABLE",
    "SLACK_SIGNAL_FILTER","INITIATIVE_1_NAME","INITIATIVE_1_DESC",
    "INITIATIVE_1_METRIC","INITIATIVE_1_DATE","CLAUDE_PROJECT_SEGMENT",
]

def write_config(config, memory_dir):
    """Save config.json for reference and future re-runs."""
    config_out = {
        "version": "1.0",
        "generated": datetime.now().isoformat(),
        "user": {k: config[k] for k in ["USER_NAME","USER_EMAIL","COMPANY","USER_ROLE","SLACK_USER_ID","SLACK_WORKSPACE_ID"]},
        "paths": {
            "briefs_dir": config["BRIEFS_DIR"],
            "memory_dir": str(memory_dir),
            "repo_dir":   config["REPO_DIR"],
        },
        "timezone": config["TIMEZONE"],
        "template_vars": {k: config.get(k, "") for k in TEMPLATE_VAR_KEYS},
    }
    CONFIG_PATH.write_text(json.dumps(config_out, indent=2))
    print(f"\n  Config saved → {CONFIG_PATH}")


def confirm_config(config):
    """Show a summary and ask the user to confirm before writing any files."""
    banner("Review your answers before we install")
    rows = [
        ("Name",            config["USER_NAME"]),
        ("Email",           config["USER_EMAIL"]),
        ("Company",         config["COMPANY"]),
        ("Role",            config["USER_ROLE"]),
        ("Slack user ID",   config["SLACK_USER_ID"]),
        ("Top stakeholder", f"{config['TIER1_NAME_1']} — {config['TIER1_TITLE_1']}"),
        ("Manager",         f"{config['MANAGER_NAME']} — {config['MANAGER_TITLE']}"),
        ("Direct report 1", f"{config['DIRECT_REPORT_1']} — {config['DIRECT_REPORT_1_TITLE']}"),
        ("Product to track",config["PRODUCT_NAME"]),
        ("Quarter",         config["CURRENT_QUARTER"]),
        ("Timezone",        config["TIMEZONE"]),
        ("Briefs saved to", config["BRIEFS_DIR"]),
    ]
    for label, value in rows:
        print(f"  {label:<20} {value}")
    print()
    answer = input("  Everything look right? (y = install / n = start over): ").strip().lower()
    return answer in ("y", "yes", "")


def copy_to_clipboard(text):
    """Copy text to macOS clipboard via pbcopy. Returns True on success."""
    try:
        import subprocess
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        return True
    except Exception:
        return False


def _read_skill(task_name, config):
    """Read an installed SKILL.md. Falls back to filled template if missing."""
    installed = CLAUDE_DIR / "scheduled-tasks" / task_name / "SKILL.md"
    if installed.exists():
        content = installed.read_text()
        # If it was already overwritten to a one-liner, use the template instead
        if len(content) > 500:
            return content
    # Fill template directly as fallback
    tmpl = TEMPLATES_DIR / "brain" / task_name / "SKILL.md.template"
    if tmpl.exists():
        return fill_template(tmpl.read_text(), config)
    return ""


def generate_finish_prompt(config):
    """Write a prompt file the user pastes into Claude Code to finish setup."""
    home = config["HOME_DIR"]
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
    out = Path(config["REPO_DIR"]).expanduser() / "setup" / "complete-setup-prompt.txt"
    out.write_text(prompt)
    return out, prompt


def main():
    print("\n" + "═"*50)
    print("  🦇  ALFRED SETUP WIZARD")
    print("  Personal AI Chief of Staff")
    print("═"*50)
    print("""
  This wizard will install Alfred for you.
  It takes about 5 minutes.

  Before you begin, make sure these MCP servers are
  connected in Claude Code (Settings → MCP Servers):
    ✅ Required: Slack, Google Calendar
    ⭐ Recommended: Gmail, Google Drive, Granola
""")

    # Detect MCPs — warn if not found but allow user to proceed
    prefixes = detect_mcp_ids()
    missing = [s for s in ("slack", "calendar") if s not in prefixes]
    if missing:
        svc_names = {"slack": "Slack", "calendar": "Google Calendar"}
        print(f"""
  ⚠️   MCP tools not auto-detected: {', '.join(svc_names[s] for s in missing)}

  This can happen when MCPs are connected via Claude Code's UI.
  If you've already connected them (green dot in Settings → MCP Servers),
  type 'y' to continue — Alfred will still work correctly.

  If you haven't connected them yet:
  1. Open Claude Code settings (gear icon or Cmd+,)
  2. Go to Integrations → MCP Servers and connect the missing tools
  3. Re-run this wizard: python3 {__file__}
""")
        cont = input("  Continue anyway? (y/n): ").strip().lower()
        if cont != "y":
            sys.exit(0)

    # Collect config — loop until user confirms
    while True:
        config = collect_config()
        if confirm_config(config):
            break
        print("\n  Starting over — no files written.\n")

    config, available, prefixes = detect_mcps(config)
    pre_populate_permissions(prefixes)

    banner("Installing")
    memory_dir = install_files(config)
    write_config(config, memory_dir)

    finish_prompt_path, finish_prompt_text = generate_finish_prompt(config)
    clipboard_ok = copy_to_clipboard(finish_prompt_text)

    banner("✅  Installation complete — one final step")

    if clipboard_ok:
        print(f"""
  The setup prompt has been copied to your clipboard automatically.

  To finish:

  1. Open Claude Code
  2. Press Cmd+N to start a new session
  3. Press Cmd+V to paste and then press Enter

  Claude will register your scheduled tasks and generate your first brief right now.

  ─────────────────────────────────────────────
  If the paste doesn't work, the prompt is also saved here:
     {finish_prompt_path}
  Open that file, select all (Cmd+A), copy (Cmd+C), and paste into Claude Code.
  ─────────────────────────────────────────────
""")
    else:
        print(f"""
  To finish:

  1. Open the file below in any text editor (TextEdit, Notes, etc.)

     {finish_prompt_path}

  2. Select all text (Cmd+A) and copy (Cmd+C)
  3. Open Claude Code, press Cmd+N for a new session
  4. Paste (Cmd+V) and press Enter

  Claude will register your scheduled tasks and generate your first brief right now.
""")

    print(f"""  ─────────────────────────────────────────────
  MCP tools detected: {config["MCP_AVAILABLE"] or "none — check your MCP connections"}
  Briefs will be saved to: {config["BRIEFS_DIR"]}
  Timezone: {config["TIMEZONE"]}

  If any tools are missing, connect them in Claude Code first,
  then re-run: python3 {__file__}
  ─────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()
