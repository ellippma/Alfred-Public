#!/usr/bin/env python3
"""
alfred-update.py
Updates Alfred's renderer, scheduled task skills, and slash command to the latest version.
Reads ~/.alfred-config.json for paths and template vars.
Never touches memory files (calibrations, stakeholders, last_brief, etc.)

Usage (from bell panel in brief):
  cd ~/alfred-repo && git pull && python3 ~/alfred-repo/setup/alfred-update.py
"""

import json, os, re, shutil, subprocess, sys
from pathlib import Path
from datetime import datetime

CONFIG_PATH = Path.home() / ".alfred-config.json"
CLAUDE_DIR  = Path.home() / ".claude"

RED    = '\033[0;31m'
YELLOW = '\033[1;33m'
GREEN  = '\033[0;32m'
RESET  = '\033[0m'

def fail(msg):  print(f"\n{RED}  ✗  {msg}{RESET}\n"); sys.exit(1)
def warn(msg):  print(f"{YELLOW}  ⚠  {msg}{RESET}")
def ok(msg):    print(f"{GREEN}  ✓  {msg}{RESET}")
def info(msg):  print(f"     {msg}")

def fill_template(text, config):
    return re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: config.get(m.group(1), m.group(0)), text)

def install_template(src, dst, config):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(fill_template(Path(src).read_text(), config))

def detect_mcp_prefixes():
    """Re-detect MCP server prefixes from current Claude settings."""
    known = {
        "slack":    ["slack_send_message", "slack_search_public"],
        "gmail":    ["search_threads", "create_draft"],
        "calendar": ["list_events", "create_event"],
        "drive":    ["search_files", "read_file_content"],
        "granola":  ["list_meetings", "get_meeting_transcript"],
    }
    prefixes = {}
    for sf in [CLAUDE_DIR / "settings.local.json", CLAUDE_DIR / "settings.json"]:
        if not sf.exists():
            continue
        try:
            data = json.loads(sf.read_text())
            for name in data.get("mcpServers", {}):
                prefix = f"mcp__{name}__"
                for svc, hints in known.items():
                    if svc not in prefixes and any(h in name.lower() for h in [svc, svc.replace("_", "")]):
                        prefixes[svc] = prefix
            for entry in data.get("permissions", {}).get("allow", []):
                if not entry.startswith("mcp__"):
                    continue
                parts = entry.split("__", 2)
                if len(parts) < 3:
                    continue
                prefix = f"mcp__{parts[1]}__"
                tool = parts[2]
                for svc, hints in known.items():
                    if any(h in tool for h in hints) and svc not in prefixes:
                        prefixes[svc] = prefix
        except Exception:
            pass
    for svc in ["granola", "scheduled-tasks", "ccd_session"]:
        prefixes[svc] = f"mcp__{svc}__"
    return prefixes


def update_permissions(prefixes):
    """Add any new permissions from the latest release."""
    FIXED = [
        "Bash(*)", "Read(*)", "Write(*)", "Edit(*)", "Glob(*)", "Grep(*)",
        "mcp__granola__list_meetings", "mcp__granola__query_granola_meetings",
        "mcp__scheduled-tasks__create_scheduled_task",
        "mcp__scheduled-tasks__list_scheduled_tasks",
        "mcp__scheduled-tasks__update_scheduled_task",
    ]
    TOOLS = {
        "slack":    ["slack_search_channels","slack_search_public_and_private","slack_send_message_draft"],
        "calendar": ["list_events","create_event"],
        "gmail":    ["search_threads","create_draft"],
        "drive":    ["search_files","list_recent_files"],
        "granola":  ["list_meetings","query_granola_meetings"],
    }
    entries = list(FIXED)
    for svc, tools in TOOLS.items():
        if prefix := prefixes.get(svc):
            for tool in tools:
                entries.append(f"{prefix}{tool}")

    settings_local = CLAUDE_DIR / "settings.local.json"
    data = {}
    if settings_local.exists():
        try:
            data = json.loads(settings_local.read_text())
        except Exception:
            pass
    perms = data.setdefault("permissions", {})
    existing = set(perms.get("allow", []))
    new_entries = set(entries) - existing
    perms["allow"] = sorted(existing | set(entries))
    settings_local.write_text(json.dumps(data, indent=2))
    return len(new_entries)


def main():
    print()
    print("══════════════════════════════════════════════════")
    print("  🦇  ALFRED UPDATE")
    print("══════════════════════════════════════════════════")
    print()

    # ── Load config ───────────────────────────────────────────────────────
    if not CONFIG_PATH.exists():
        fail(f"No config found at {CONFIG_PATH}. Re-run the Alfred setup wizard to fix this.")
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception as e:
        fail(f"Could not read config: {e}")

    repo_dir   = Path(cfg["paths"]["repo_dir"])
    briefs_dir = Path(cfg["paths"]["briefs_dir"])
    installed  = cfg.get("version", "0.0.0")
    tvars      = cfg.get("template_vars", {})

    if not tvars:
        warn("No template_vars in config — SKILL.md files will not be re-rendered.")
        warn("To fix, re-run the Alfred setup wizard once.")

    # ── Pull latest ───────────────────────────────────────────────────────
    info("Pulling latest from GitHub…")
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "pull", "--quiet"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        fail(f"git pull failed:\n{result.stderr.strip()}")
    ok("Repo updated")

    ver_file = repo_dir / "VERSION"
    new_version = ver_file.read_text().strip() if ver_file.exists() else installed
    if new_version == installed:
        ok(f"Already on latest version ({installed})")
    else:
        ok(f"Version: {installed} → {new_version}")

    # ── Copy renderer files ───────────────────────────────────────────────
    info("Updating renderer…")
    for fname in ["alfred-build.py", "alfred-template.html"]:
        src = repo_dir / "renderer" / fname
        if src.exists():
            shutil.copy2(src, briefs_dir / fname)
            ok(fname)
        else:
            warn(f"{fname} not found in repo — skipped")
    for asset in ["batman-logo.png", "read-notepad.py"]:
        src = repo_dir / "renderer" / asset
        if src.exists():
            shutil.copy2(src, briefs_dir / asset)

    # ── Re-render scheduled task skills ──────────────────────────────────
    if tvars:
        info("Updating scheduled task skills…")
        tasks_dir  = CLAUDE_DIR / "scheduled-tasks"
        templates  = repo_dir / "templates" / "brain"
        for task in ["morning-brief", "pre-meeting-brief", "friday-wrap"]:
            src = templates / task / "SKILL.md.template"
            if src.exists():
                install_template(src, tasks_dir / task / "SKILL.md", tvars)
                ok(f"{task}/SKILL.md")
            else:
                warn(f"Template not found for {task} — skipped")

        # ── Re-render slash commands ──────────────────────────────────────
        info("Updating /alfred commands…")
        for cmd in ["alfred", "alfred-config"]:
            cmd_src = repo_dir / "templates" / "commands" / f"{cmd}.md.template"
            if cmd_src.exists():
                install_template(cmd_src, CLAUDE_DIR / "commands" / f"{cmd}.md", tvars)
                ok(f"/{cmd} command")

    # ── Update permissions ────────────────────────────────────────────────
    info("Checking permissions…")
    prefixes = detect_mcp_prefixes()
    n = update_permissions(prefixes)
    if n:
        ok(f"{n} new permission(s) pre-approved")
    else:
        ok("Permissions up to date")

    # ── Save new version to config ────────────────────────────────────────
    cfg["version"] = new_version
    cfg["updated"] = datetime.now().isoformat()
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    ok(f"Config updated to v{new_version}")

    print()
    print("══════════════════════════════════════════════════")
    print(f"  ✅  Alfred updated to v{new_version}!")
    print("  The bell will disappear on your next brief run.")
    print("══════════════════════════════════════════════════")
    print()


if __name__ == "__main__":
    main()
