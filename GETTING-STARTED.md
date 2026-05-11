# Alfred — Getting Started

Alfred is a personal AI Chief of Staff that runs inside Claude Code. Every morning it reads your calendar, Slack, email, and meeting transcripts, then opens a single browser page with your fires, your day, your team's status, and suggested first moves — including pre-drafted Slack and email replies you can send in one click.

There's no app to check. No prompts to write. Alfred shows up at 7:57 AM with what you need.

---

## What you get

| | When | What's in it |
|---|---|---|
| **Morning brief** | 7:57 AM, Mon–Fri | Active fires, calendar with prep notes, team commitment tracking, drafted replies, Drive mentions, kanban board |
| **Pre-meeting brief** | 15 min before Director+ meetings | That person's context, your open commitments to them, recent Slack threads |
| **Friday wrap** | 4 PM Fridays | Week patterns, slippage trends, initiative status |
| **On-demand** | Anytime | Type `/alfred What did I commit to [person] this week?` in Claude Code |

Alfred drafts replies and places them in Slack Drafts or Gmail Drafts — **nothing is ever sent without your review**.

---

## Before you install — what you need

Budget **20–30 minutes** for this part. You need four things ready:

### 1. Claude Code
Download and install from **[claude.ai/code](https://claude.ai/code)**. Sign in with your Anthropic account (create one if needed). After installing, go to **Help → Check for Updates** and make sure you're fully up to date.

### 2. MCP connectors (the data sources)
Inside Claude Code, press **Cmd + ,** to open Settings, then go to **MCP Servers** and connect:

| Service | Required? |
|---|---|
| Slack | Required |
| Google Calendar | Required |
| Gmail | Strongly recommended |
| Google Drive | Strongly recommended |
| Granola (meeting transcripts) | If your team uses it |

Each connector shows a green dot when it's working. If you see red, disconnect and reconnect.

### 3. Git
Open Terminal (Cmd + Space → "Terminal") and run:
```
git --version
```
If you see a version number, you're good. If not, macOS will offer to install it — click Install.

### 4. Python 3
Already on your Mac. Confirm with:
```
python3 --version
```

---

## Install — 3 steps

### Step 1 — Run the installer

Paste this into Terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ellippma/Alfred-Public/main/setup/install.sh)"
```

This downloads Alfred and opens the setup wizard in your browser automatically.

### Step 2 — Answer the wizard (~5 minutes)

The wizard walks you through five short steps:

1. **You** — name, email, role, Slack user ID
2. **People** — your manager, key stakeholders you want tracked, calendar no-fly list
3. **Team** — direct reports Alfred monitors commitments for
4. **Goals** — your main initiative, target date
5. **Timezone & save location** — when and where briefs land

> **Finding your Slack user ID:** Slack → your profile photo → Profile → `···` → "Copy member ID". Starts with `U`.

Nothing is written to your computer until you click **Install Alfred** on the final review screen.

### Step 3 — Paste into Claude Code

When the wizard finishes, it copies a setup prompt to your clipboard and tells you what to do:

1. Open Claude Code
2. **Cmd + N** for a new session
3. **Cmd + V** to paste, then Enter

Claude registers your scheduled tasks and opens your first brief — usually within 2–3 minutes.

---

## Confirm it worked

Run this in Terminal after Step 3:

```bash
python3 ~/alfred-repo/setup/verify.py
```

All checks should pass. You're set when:
- ✅ Your first brief opens in the browser
- ✅ Verifier reports all checks passed
- ✅ The next weekday at 7:57 AM, a macOS notification appears: *"Alfred — Morning Brief is ready"*

> **Keep Claude Code running in the background.** Alfred's scheduled tasks only fire when it's open — it doesn't need to be in the foreground, just not quit.

---

## How Alfred gets smarter over time

Alfred isn't static. It builds a persistent memory of your world and refines it with every brief run.

**It remembers people.** For each person you interact with — stakeholders, direct reports, counterparts — Alfred maintains a running log: what they've committed to, what signals have appeared about them, their open items. Over time it can surface patterns like *"Jordan has slipped the last three deadlines"* or *"this person responds well to morning pings."*

**It learns what's a fire and what isn't.** The first time Alfred flags something that isn't really urgent, click **✏️ FEEDBACK** in the brief header or just tell Claude: *"That's not a fire because..."* Alfred saves a calibration rule and never flags that type of signal again.

**It tracks your commitments.** Anything you or your team commits to in Slack or a meeting goes into tracked commitments with status signals (done / in progress / stalled / overdue). The longer Alfred runs, the richer the pattern detection.

**It spots recurring themes.** After a few weeks, Alfred can cluster signals across people and projects — surfacing things like *"three separate Slack threads this week all touch the same bottleneck."*

**You can also edit the memory files directly.** After setup, Alfred creates a set of plain-text files describing you, your team, and your priorities. Edit them anytime to update your stakeholders, adjust what Alfred watches for, or add standing context. Alfred reads these files at the start of every brief run.

The payoff compounds: a brief on day one is useful. A brief at week six knows your world.

---

## Teaching Alfred mid-flight

You don't need to reconfigure anything to update Alfred's behavior. In any Claude Code session, just say what you'd say to a chief of staff:

- *"That's not a fire — we decided to accept that risk last quarter"*
- *"Always check with [person] before flagging anything in [channel] as urgent"*
- *"[Person] is now reporting to me"*
- *"Add a milestone: we need to close the enterprise pilot by July 1"*

Alfred saves it and applies it on the next run.

---

## Troubleshooting

**Brief didn't generate at 7:57 AM**
Make sure Claude Code is open. Run `python3 ~/alfred-repo/setup/verify.py` to check task registration. Re-paste the finish-setup prompt in a new session if tasks are missing.

**An MCP connector shows red**
Disconnect and reconnect it in Settings (Cmd + ,) → MCP Servers. Re-authorize with your Google or Slack account.

**Some brief sections are empty**
Alfred only shows sections with real data — an empty Fires section means no fires, which is good.

**Need to change your configuration**
```bash
python3 ~/alfred-repo/setup/alfred-setup-ui.py
```
Your memory files, calibrations, and brief history are preserved — only the config updates.
