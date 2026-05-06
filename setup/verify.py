#!/usr/bin/env python3
"""
alfred-verify.py
Run after completing setup to confirm everything is wired correctly.
Usage: python3 ~/alfred-repo/setup/verify.py
"""

import json, sys
from pathlib import Path

CLAUDE_DIR  = Path.home() / ".claude"
CONFIG_PATH = Path.home() / ".alfred-config.json"

PASS = "  ✅"
FAIL = "  ❌"
WARN = "  ⚠️ "

results = []

def check(label, passed, fix=None):
    status = PASS if passed else FAIL
    results.append((passed, label, fix))
    print(f"{status}  {label}")
    if not passed and fix:
        print(f"       → {fix}")

def section(title):
    print(f"\n  {'─'*44}")
    print(f"  {title}")
    print(f"  {'─'*44}")

# ── Load config ───────────────────────────────────────────────────────────────
print("\n" + "═"*50)
print("  🦇  ALFRED — Install Verifier")
print("═"*50)

config = {}
if CONFIG_PATH.exists():
    try:
        config = json.loads(CONFIG_PATH.read_text())
        print(f"\n  Config found: {CONFIG_PATH}")
    except Exception:
        print(f"\n  ⚠️  Config file exists but couldn't be parsed: {CONFIG_PATH}")
else:
    print(f"\n  ❌  Config file not found at {CONFIG_PATH}")
    print("     Run the setup wizard first: python3 ~/alfred-repo/setup/alfred-setup.py")
    sys.exit(1)

briefs_dir  = Path(config.get("paths", {}).get("briefs_dir", ""))
memory_dir  = Path(config.get("paths", {}).get("memory_dir", ""))
repo_dir    = Path(config.get("paths", {}).get("repo_dir",   ""))
home        = Path.home()

# ── Section 1: Core files ─────────────────────────────────────────────────────
section("1 / 5  Core files")

check("Config file exists",          CONFIG_PATH.exists())
check("Briefs directory exists",     briefs_dir.is_dir(),
      f"Create it: mkdir -p \"{briefs_dir}\"")
check("alfred-build.py installed",   (briefs_dir / "alfred-build.py").exists(),
      f"Re-run setup: python3 {repo_dir}/setup/alfred-setup.py")
check("alfred-template.html installed", (briefs_dir / "alfred-template.html").exists(),
      f"Re-run setup: python3 {repo_dir}/setup/alfred-setup.py")
check("read-notepad.py installed",   (briefs_dir / "read-notepad.py").exists(),
      f"Re-run setup: python3 {repo_dir}/setup/alfred-setup.py")

test_file = briefs_dir / ".alfred-write-test"
try:
    test_file.write_text("ok"); test_file.unlink()
    writable = True
except Exception:
    writable = False
check("Briefs directory is writable", writable,
      f"Check permissions: chmod 755 \"{briefs_dir}\"")

# ── Section 2: Scheduled tasks ────────────────────────────────────────────────
section("2 / 5  Scheduled tasks")

PLACEHOLDER_SIGNALS = ("Read and execute the instructions", "SKILL.md\n")

for task in ["morning-brief", "pre-meeting-brief", "friday-wrap"]:
    skill_path = CLAUDE_DIR / "scheduled-tasks" / task / "SKILL.md"
    exists = skill_path.exists()
    check(f"{task}/SKILL.md exists", exists,
          f"Re-run finish-setup prompt in a new Claude Code session")
    if exists:
        content = skill_path.read_text()
        is_full = len(content) > 500  # one-liner is ~80 chars; full file is thousands
        has_placeholder = "{{" in content
        check(f"{task}/SKILL.md is fully restored (not one-liner)", is_full,
              "The scheduled task tool overwrote SKILL.md. Re-run the finish-setup prompt — "
              "it will restore the full contents.")
        check(f"{task}/SKILL.md has no unfilled placeholders", not has_placeholder,
              f"Open {skill_path} and search for '{{{{' — replace any remaining placeholders manually.")

# ── Section 3: Memory files ───────────────────────────────────────────────────
section("3 / 5  Memory files")

required_memory = [
    "MEMORY.md", "user_role.md", "stakeholders.md", "calibrations.md",
    "feedback_blindspots.md", "project_q2_initiatives.md",
    "project_personal_cos.md", "last_brief.md", "jira_state.md",
]
for fname in required_memory:
    fpath = memory_dir / fname
    check(f"{fname}", fpath.exists(),
          f"Re-run setup: python3 {repo_dir}/setup/alfred-setup.py")

# Check for unfilled placeholders in memory files
placeholder_files = []
for fname in required_memory:
    fpath = memory_dir / fname
    if fpath.exists() and "{{" in fpath.read_text():
        placeholder_files.append(fname)
check("No unfilled placeholders in memory files", len(placeholder_files) == 0,
      f"Files with unfilled placeholders: {', '.join(placeholder_files)}. "
      "Re-run the finish-setup prompt to fill canvas IDs, or edit files manually.")

# ── Section 4: Canvas IDs ─────────────────────────────────────────────────────
section("4 / 5  Slack canvas IDs")

cos_path = memory_dir / "project_personal_cos.md"
canvas_ok = True
if cos_path.exists():
    cos_text = cos_path.read_text()
    todo_ok     = "CANVAS_TODO_ID_PLACEHOLDER"     not in cos_text
    feedback_ok = "CANVAS_FEEDBACK_ID_PLACEHOLDER" not in cos_text
    check("To-Do canvas ID is set",     todo_ok,
          "Canvas not created. See 'Manual canvas setup' in the README, then edit project_personal_cos.md AND morning-brief/SKILL.md replacing CANVAS_TODO_ID_PLACEHOLDER.")
    check("Feedback canvas ID is set",  feedback_ok,
          "Canvas not created. See 'Manual canvas setup' in the README, then edit project_personal_cos.md AND morning-brief/SKILL.md AND friday-wrap/SKILL.md replacing CANVAS_FEEDBACK_ID_PLACEHOLDER.")
    canvas_ok = todo_ok and feedback_ok

    # Also check SKILL.md files for leftover canvas placeholders
    for task in ["morning-brief", "friday-wrap"]:
        skill = CLAUDE_DIR / "scheduled-tasks" / task / "SKILL.md"
        if skill.exists():
            skill_text = skill.read_text()
            for token, label in [("CANVAS_TODO_ID_PLACEHOLDER", "To-Do"), ("CANVAS_FEEDBACK_ID_PLACEHOLDER", "Feedback")]:
                if token in skill_text:
                    check(f"{task}/SKILL.md has {label} canvas ID", False,
                          f"Edit {skill} and replace {token} with the real canvas ID.")
else:
    check("project_personal_cos.md exists for canvas ID check", False,
          f"Re-run setup: python3 {repo_dir}/setup/alfred-setup.py")

# ── Section 5: Slash command ──────────────────────────────────────────────────
section("5 / 5  Slash command")

alfred_cmd = CLAUDE_DIR / "commands" / "alfred.md"
check("/alfred command installed", alfred_cmd.exists(),
      f"Re-run setup: python3 {repo_dir}/setup/alfred-setup.py")
if alfred_cmd.exists():
    cmd_text = alfred_cmd.read_text()
    check("/alfred command has no unfilled placeholders", "{{" not in cmd_text,
          f"Re-run setup: python3 {repo_dir}/setup/alfred-setup.py")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n  {'═'*44}")
total   = len(results)
passed  = sum(1 for r in results if r[0])
failed  = total - passed

if failed == 0:
    print(f"\n  ✅  All {total} checks passed — Alfred is ready.")
    if not canvas_ok:
        pass  # already reported above
    print("""
  Your first brief will arrive at 7:57 AM tomorrow.
  Make sure Claude Code is running in the background.

  To generate a brief right now:
    1. Open Claude Code
    2. Start a new session (Cmd+N)
    3. Type: Read and execute ~/.claude/scheduled-tasks/morning-brief/SKILL.md
""")
else:
    print(f"\n  ❌  {failed} of {total} checks failed — fix the items marked ❌ above.")
    print("     Re-run this verifier after fixing: python3 ~/alfred-repo/setup/verify.py\n")

sys.exit(0 if failed == 0 else 1)
