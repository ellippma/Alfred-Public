#!/usr/bin/env python3
"""
dry_run_test.py
Runs the Alfred setup wizard with fake CRO data in a temp directory.
Verifies all {{PLACEHOLDERS}} are filled in every output file.
Nothing touches real ~/.claude or ~/Documents.
"""

import json, re, shutil, sys, tempfile, textwrap
from pathlib import Path
from unittest.mock import patch

# ── Fake CRO answers (in wizard prompt order) ─────────────────────────────────

FAKE_INPUTS = [
    # Step 1 — About you
    "Jane Smith",                          # name
    "jane.smith@acmecorp.com",             # email
    "Acme Corp",                           # company
    "CRO at Acme Corp",                    # role
    "Drive revenue growth across all GTM", # mission
    "U99ABC123XYZ",                        # Slack user ID
    "T88DEF456ABC",                        # Slack workspace ID
    # Step 2 — Key stakeholders
    "Bob Chen",                            # tier1 name 1
    "CEO",                                 # tier1 title 1
    "Direct, data-driven",                 # tier1 note 1
    "Sara Park",                           # tier1 name 2
    "CFO",                                 # tier1 title 2
    "",                                    # tier1 note 2 (optional, skip)
    "Alice Wong",                          # manager name
    "VP RevOps",                           # manager title
    "Send weekly digest every Friday",     # manager note
    "Sara Park",                           # no-fly 1
    "",                                    # no-fly 2 (skip)
    "",                                    # no-fly 3 (skip)
    # Step 3 — Team
    "Marcus Lee",                          # DR1 name
    "VP Sales",                            # DR1 title
    "Priya Nair",                          # DR2 name
    "VP Marketing",                        # DR2 title
    # Step 4 — Product
    "Launchpad",                           # product name
    "2026-09-30",                          # rollout date
    "Q3 2026",                             # quarter label
    # Step 5 — Paths & timezone
    "1",                                   # timezone (Eastern)
    "",                                    # briefs dir (accept default)
    "",                                    # repo dir (accept default)
    # Confirm step
    "y",
]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    tmp = Path(tempfile.mkdtemp(prefix="alfred_dryrun_"))
    print(f"\n🧪  Dry-run sandbox: {tmp}\n")

    # Fake home structure
    fake_home      = tmp / "home"
    fake_claude    = fake_home / ".claude"
    fake_settings  = fake_claude / "settings.local.json"
    fake_briefs    = fake_home / "Documents" / "Alfred Briefs"
    fake_home.mkdir(parents=True)
    fake_claude.mkdir(parents=True)
    fake_briefs.mkdir(parents=True)

    # Fake settings.local.json with Slack + Calendar MCP entries
    fake_settings.write_text(json.dumps({
        "permissions": {
            "allow": [
                "mcp__aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb__slack_send_message",
                "mcp__aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb__slack_search_public",
                "mcp__cccccccc-3333-4444-5555-dddddddddddd__list_events",
                "mcp__cccccccc-3333-4444-5555-dddddddddddd__create_event",
                "mcp__eeeeeeee-6666-7777-8888-ffffffffffff__search_threads",
                "mcp__11111111-9999-aaaa-bbbb-222222222222__search_files",
                "mcp__granola__list_meetings",
                "mcp__scheduled-tasks__create_scheduled_task",
            ]
        }
    }))

    # Patch Path.home() and the wizard's constants
    import alfred_setup as s

    input_iter = iter(FAKE_INPUTS)

    def fake_input(prompt=""):
        try:
            val = next(input_iter)
            # Print so we can trace the flow
            print(f"  INPUT [{val!r}] ← {prompt.strip()[:60]}")
            return val
        except StopIteration:
            raise EOFError("Ran out of fake inputs")

    with (
        patch.object(Path, "home", return_value=fake_home),
        patch("builtins.input", side_effect=fake_input),
        patch.object(s, "SETTINGS_LOCAL", fake_settings),
        patch.object(s, "CLAUDE_DIR",     fake_claude),
        patch.object(s, "CONFIG_PATH",    fake_home / ".alfred-config.json"),
    ):
        print("── Step 1-5: collecting config ──")
        config = s.collect_config()

        print("\n── Confirm step ──")
        assert s.confirm_config(config), "User said no to confirm"

        print("\n── MCP detection ──")
        config, available, prefixes = s.detect_mcps(config)

        print("\n── Pre-populating permissions ──")
        s.pre_populate_permissions(prefixes)

        # Override BRIEFS_DIR so it lands in sandbox
        config["BRIEFS_DIR"]     = str(fake_briefs)
        config["BRIEFS_DIR_ESC"] = str(fake_briefs).replace(" ", "\\ ")

        print("\n── Installing files ──")
        memory_dir = s.install_files(config)

        print("\n── Writing config ──")
        s.write_config(config, memory_dir)

        print("\n── Generating finish prompt ──")
        prompt_path, _ = s.generate_finish_prompt(config)

    # ── Check: no {{PLACEHOLDER}} left in any output file ─────────────────────
    print("\n" + "═"*55)
    print("  PLACEHOLDER CHECK")
    print("═"*55)

    search_roots = [
        fake_claude / "scheduled-tasks",
        fake_claude / "commands",
        fake_claude / "projects",
        fake_home / ".alfred-config.json",
    ]
    # Also check the finish prompt
    extra_files = [prompt_path] if prompt_path.exists() else []

    pattern = re.compile(r"\{\{[A-Z0-9_]+\}\}")
    failures = []

    def check_file(path):
        try:
            text = Path(path).read_text()
        except Exception:
            return
        matches = pattern.findall(text)
        if matches:
            failures.append((path, matches))
            print(f"  ❌  {path}")
            for m in set(matches):
                print(f"        unfilled: {m}")
        else:
            print(f"  ✅  {path}")

    for root in search_roots:
        if root.is_dir():
            for f in sorted(root.rglob("*")):
                if f.is_file() and f.suffix in (".md", ".txt", ".json", ".html", ".py"):
                    check_file(f)
        elif root.is_file():
            check_file(root)
    for f in extra_files:
        check_file(f)

    # ── Check: permissions were written to settings.local.json ───────────────
    print("\n" + "═"*55)
    print("  PERMISSIONS CHECK")
    print("═"*55)
    settings_data = json.loads(fake_settings.read_text())
    approved = settings_data.get("permissions", {}).get("allow", [])
    required = [
        "mcp__scheduled-tasks__create_scheduled_task",
        "mcp__aaaaaaaa-0000-1111-2222-bbbbbbbbbbbb__slack_send_message_draft",
        "mcp__cccccccc-3333-4444-5555-dddddddddddd__list_events",
        "mcp__eeeeeeee-6666-7777-8888-ffffffffffff__search_threads",
    ]
    perm_failures = []
    for entry in required:
        if entry in approved:
            print(f"  ✅  {entry}")
        else:
            print(f"  ❌  {entry} — MISSING")
            perm_failures.append(entry)
    print(f"\n  Total permissions written: {len(approved)}")

    print("\n" + "═"*55)
    all_ok = not failures and not perm_failures
    if not all_ok:
        msgs = []
        if failures:    msgs.append(f"{len(failures)} file(s) have unfilled placeholders")
        if perm_failures: msgs.append(f"{len(perm_failures)} permission(s) missing")
        print(f"  RESULT: ❌  {' | '.join(msgs)}")
        sys.exit(1)
    else:
        print("  RESULT: ✅  All placeholders filled. All permissions written. Ready to ship.")
    print("═"*55 + "\n")

    # Cleanup
    shutil.rmtree(tmp)


if __name__ == "__main__":
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "alfred_setup",
        Path(__file__).parent / "alfred-setup.py"
    )
    alfred_setup = importlib.util.module_from_spec(spec)
    sys.modules["alfred_setup"] = alfred_setup
    spec.loader.exec_module(alfred_setup)
    main()
