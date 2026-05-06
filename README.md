# 🦇 Alfred — Personal AI Chief of Staff

Alfred is a personal AI Chief of Staff that runs inside Claude Code. Every morning at 7:57 AM it reads your calendar, Slack, email, meeting transcripts, and documents — then delivers a single HTML brief in your browser with your fires, your day, your team's status, and suggested next moves. It handles follow-through drafts so you don't have to.

---

## What you get

| Brief | When | What's in it |
|-------|------|--------------|
| **Morning brief** | 7:57 AM, Mon–Fri | Fires, calendar prep, team commitments, Slack drafts, Gmail drafts, Drive mentions, Jira suggestions |
| **Pre-meeting brief** | 15 min before any Director+ meeting | Granola history, open commitments, Slack context for that person |
| **Friday wrap** | 4 PM Fridays | Week patterns: repeated slippage, team trends, initiative status |
| **On-demand queries** | Anytime | Type `/alfred What did I promise [person] this week?` in Claude Code |

---

## Before you start — what you need

You need four things installed and working before running setup. Budget 20–30 minutes for this part.

### 1. Claude Code

Claude Code is the desktop app Alfred lives inside. Download and install it from:

**[claude.ai/code](https://claude.ai/code)**

Open it and sign in with your Anthropic account. If you don't have one, create one at that link.

### 2. The MCP connectors

MCP connectors let Alfred read your real data — Slack, calendar, email, etc. You connect them inside Claude Code's settings.

**How to open MCP settings:**
1. Open Claude Code
2. Click the **gear icon** (⚙️) in the bottom-left corner, or press `Cmd + ,`
3. Go to **Integrations** or **MCP Servers**
4. Click **Add** for each service below

**Connect these (required):**

- **Slack** — search the MCP marketplace for "Slack", click Install, authorize with your Slack account
- **Google Calendar** — search for "Google Calendar", click Install, sign in with your Google account

**Connect these (strongly recommended — Alfred uses them for richer briefs):**

- **Gmail** — search for "Gmail", click Install, sign in with the same Google account
- **Google Drive** — search for "Google Drive", click Install
- **Granola** — search for "Granola", click Install (Granola is a meeting transcript tool — if your company doesn't use it, skip this one)

> **Tip:** After connecting each tool, you'll see it appear in your MCP Servers list with a green dot. If it shows a red dot, try disconnecting and reconnecting.

### 3. Git (to download Alfred)

Git is how you download Alfred from GitHub. Check if you already have it:

1. Open **Terminal** (press `Cmd + Space`, type "Terminal", press Enter)
2. Type `git --version` and press Enter
3. If you see a version number, you're good. If not, macOS will prompt you to install it — click Install.

### 4. Python 3 (comes with macOS)

macOS includes Python 3. Verify it works:

```
python3 --version
```

You should see `Python 3.x.x`. If you don't, download it from [python.org](https://python.org).

---

## Install Alfred — 3 steps

### Step 1 — Run the installer

Open **Terminal** (press `Cmd + Space`, type "Terminal", press Enter) and paste this single command:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ellippma/Alfred/main/setup/install.sh)"
```

The installer will check your requirements, download Alfred, and launch the setup wizard automatically.

### Step 2 — Answer the wizard questions (~5 minutes)

The wizard will ask you about yourself, your stakeholders, and your team. At the end, it shows you a summary — if anything looks wrong, type `n` and it starts over. Nothing is written to your computer until you confirm.

**Questions it will ask:**

- Your name, work email, Slack user ID
- Your key stakeholders (who defines a "fire" for you)
- Your manager and direct reports
- The main product or initiative Alfred should track
- Your timezone and where to save your daily briefs

> **Finding your Slack user ID:** Open Slack → click your profile photo → click "Profile" → click the three dots `···` → "Copy member ID". It starts with the letter `U`.

> **Finding your Slack workspace ID:** In Slack, click your workspace name in the top-left → "Settings & administration" → "Workspace settings" — the ID starts with `T` and appears in the URL bar.

### Step 3 — Paste into Claude Code

When the wizard finishes, it automatically copies a setup prompt to your clipboard and tells you exactly what to do:

1. Open Claude Code
2. Press **Cmd + N** to open a new session
3. Press **Cmd + V** to paste, then press **Enter**

Claude will register your scheduled tasks and open your **first brief** in the browser — usually within 2–3 minutes.

---

## How to know it worked

### Step 4 — Run the verifier

After Claude finishes Step 3, run this in Terminal to confirm everything is wired correctly:

```bash
python3 ~/alfred-repo/setup/verify.py
```

It checks every install artifact and tells you exactly what to fix if anything is missing. All checks should pass before you close Terminal.

### You're good when you see:

- ✅ Your first brief opens in your browser (within minutes of completing Step 3)
- ✅ The verifier reports all checks passed
- ✅ At 7:57 AM the next weekday, a macOS notification appears: *"Alfred — Morning Brief is ready"*

> **Important: Claude Code must stay running** for Alfred's scheduled tasks to fire. You don't need to be actively using it — it just needs to be open in the background (it can be minimized or in the Dock). If you quit Claude Code, Alfred goes quiet until you reopen it.

### Step 5 — Review your first brief

Your brief opens as a page in your browser. It's a live file — check off calendar items, add notes to the notepad, and click the **✏️ FEEDBACK** button to teach Alfred what matters to you.

> **Notepad requires Chrome.** The in-brief notepad reads from Chrome's storage and only works if Chrome is your default browser. If you use Safari or Firefox, all other brief features work normally — just not the notepad.

---

## What happens after install

| Time | What Alfred does |
|------|-----------------|
| **7:57 AM weekdays** | Generates your morning brief, opens it in your browser, fires a macOS notification |
| **Every 10 min, 7 AM–7 PM weekdays** | Checks your calendar — if a Director+ meeting is starting in 15 min, opens a quick pre-meeting brief |
| **4 PM Fridays** | Generates your Friday wrap — patterns from the whole week |
| **Anytime** | Type `/alfred [question]` in any Claude Code session for on-demand answers |

Alfred runs even when Claude Code is in the background. You don't need to do anything to trigger it.

---

## The brief — what's inside

The morning brief opens as a single HTML page in your browser. Here's what each section means:

- **⚡ Since Yesterday** — what changed since your last brief (new fires, resolved items, status flips)
- **📅 Yesterday** — meetings you had, decisions made, commitments given and received
- **🔥 Fires** — things needing same-day action, each with a suggested first move
- **🧭 Coach's Note** — one pattern Alfred noticed about how you're working
- **⏰ Today** — your real calendar with prep notes for key meetings
- **📋 Due This Week** — commitments with approaching deadlines
- **⚠️ Slipped** — commitments with no movement signal (Alfred checks Slack, Granola, and Drive before calling anything slipped)
- **💬 Priority Threads** — Slack/email threads needing a reply (Alfred drafts replies for you — they land in Slack Drafts or Gmail Drafts, never sent automatically)
- **🤝 Team Commitments** — what your direct reports committed to and their current status
- **📡 Product Signals** — wins, capability gaps, strategy signals from Slack about your main initiative
- **📄 Drive Mentions** — docs where you were @-mentioned in the last 7 days
- **🎫 Jira** — tickets Alfred thinks should be created, moved to In Progress, or closed

---

## Teaching Alfred what matters

Alfred learns from your feedback. Two ways to calibrate:

**1. In the brief itself**
Click the **✏️ FEEDBACK** button in the top bar of any brief. You can mark something "not a fire," add a standing instruction, or leave a one-off note. Alfred picks up these files at the start of every brief run — you can submit multiple and they'll all be ingested.

**2. Just tell Claude**
In any Claude Code session, say: *"That's not a fire because..."* or *"Always check X before flagging Y."* Alfred saves it automatically.

---

## Personalizing your memory files

After setup, Alfred created memory files that describe you, your context, and your world. You can edit them directly to improve Alfred's accuracy:

| File | What to update |
|------|----------------|
| `~/.claude/projects/.../memory/user_role.md` | Your role, mission, what counts as a signal vs. noise |
| `~/.claude/projects/.../memory/stakeholders.md` | Your leadership chain, key relationships, how to work with each person |
| `~/.claude/projects/.../memory/feedback_blindspots.md` | Coaching patterns Alfred watches for |
| `~/.claude/projects/.../memory/project_q2_initiatives.md` | Your quarter's priorities, success metrics, target dates |
| `~/.claude/projects/.../memory/calibrations.md` | "Not a fire" rules — Alfred appends these automatically |

> **Where are these files?** In Finder, press `Cmd + Shift + G`, type `~/.claude/projects/` and press Enter. Open the folder that matches your username.

---

## Troubleshooting

**Alfred didn't generate a brief at 7:57 AM**
- Make sure Claude Code is open in the background — Alfred's scheduled tasks only run when Claude Code is running
- Run the verifier to check task registration: `python3 ~/alfred-repo/setup/verify.py`
- Re-run the finish-setup prompt in a new Claude Code session if tasks are missing

**An MCP tool shows a red dot or isn't working**
- Disconnect and reconnect it in Claude Code Settings → Integrations
- Re-authorize with your Google or Slack account
- Re-run the verifier after reconnecting

**The brief opened but some sections are empty**
- Alfred only shows sections with real data — an empty Fires section means no fires, which is good
- If Granola sections are empty, make sure the Granola MCP is connected and you've had meetings this week
7. Re-run `python3 ~/alfred-repo/setup/verify.py` to confirm

**Notepad isn't working**
- The in-brief notepad only works in Chrome. If you use Safari or Firefox, all other brief sections work normally

**The brief says "Run Now" — where does that go?**
- Clicking **▶ Run Now** in the brief copies the trigger command to your clipboard. Switch to Claude Code, press Cmd+N for a new session, and paste (Cmd+V)

**I need to update my stakeholders or role**
- Tell Claude directly: *"Update my stakeholders — [person] is now my new manager"* — Alfred saves it automatically
- Or edit `~/.claude/projects/.../memory/stakeholders.md` directly (see "Personalizing your memory files" above)

**Re-running setup (if you change MCP connections or want to reconfigure)**
```bash
python3 ~/alfred-repo/setup/alfred-setup.py
```
Your calibrations, last brief state, and Jira ledger are preserved — only the config is updated.

---

## For developers

<details>
<summary>Architecture, file structure, and template system</summary>

### How Alfred works

Alfred uses a strict data pipeline — Claude never writes raw HTML:

```
Claude gathers data (Slack, Calendar, Granola, Drive, Gmail)
       ↓
alfred-data.json  (Claude writes structured data here)
       ↓
alfred-build.py   (renderer reads data, fills template)
       ↓
alfred-brief-YYYY-MM-DD.html  (opened in browser)
```

### File structure

```
alfred-repo/
├── setup/
│   ├── alfred-setup.py           ← Run this to install
│   └── complete-setup-prompt.txt ← Generated at setup — paste into Claude
├── templates/
│   ├── brain/                    ← SKILL.md templates (with {{PLACEHOLDERS}})
│   │   ├── morning-brief/
│   │   ├── pre-meeting-brief/
│   │   └── friday-wrap/
│   ├── memory/                   ← Memory file templates
│   └── commands/                 ← /alfred slash command template
├── renderer/
│   ├── alfred-build.py           ← Turns alfred-data.json → styled HTML
│   ├── alfred-template.html      ← Batman-themed brief UI
│   └── read-notepad.py           ← Reads notepad from Chrome localStorage
└── README.md
```

After install, Alfred places files in:
- `~/.claude/scheduled-tasks/` — morning-brief, pre-meeting-brief, friday-wrap SKILL.md files
- `~/.claude/commands/alfred.md` — /alfred slash command
- `~/.claude/projects/{segment}/memory/` — personalized memory files
- `{briefs_dir}/` — briefs + renderer (default: `~/Documents/Alfred Briefs/`)

### Template system

All `*.template` files use `{{PLACEHOLDER}}` substitution. The setup wizard fills every placeholder from user input and auto-detected MCP tool IDs.

Key placeholders:
- `{{MEMORY_DIR}}` — absolute path to the user's Claude project memory directory
- `{{BRIEFS_DIR}}` — where HTML briefs are saved
- `{{MCP_SLACK}}`, `{{MCP_CALENDAR}}`, etc. — MCP tool ID prefixes (auto-detected)

### MCP ID detection

Claude Code assigns UUIDs to MCP servers. The setup wizard parses `~/.claude/settings.local.json` to extract these automatically — users never need to find or enter them manually.

### SKILL.md restoration

`mcp__scheduled-tasks__create_scheduled_task` overwrites the SKILL.md with just the prompt string. The finish-setup prompt includes explicit instructions to restore the full SKILL.md content immediately after each task registration.

</details>
