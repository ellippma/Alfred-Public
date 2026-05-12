# alfred-data.json — Field Reference

`alfred-data.json` is written by Claude during each brief run and read by
`alfred-build.py` to render the HTML brief. It lives in your briefs directory
alongside the renderer.

See `alfred-data.example.json` for a complete working example with inline notes.

---

## Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `date` | string | yes | Brief date, `YYYY-MM-DD` |
| `delta` | object | no | What changed since yesterday's brief |
| `yesterday_recap` | object | no | Summary of the previous workday |
| `data_sources` | object | no | Status of each data source |
| `fires` | array | no | Active fires — shown as red cards |
| `resolved_fires` | array | no | Fires resolved since last brief |
| `coach_note` | string | no | Strategic coaching note shown below fires |
| `calendar_events` | array | no | Today's calendar entries |
| `calendar_notices` | array of strings | no | Freeform notices below the calendar |
| `due_this_week` | array | no | Items due this week |
| `slipped` | array | no | Items that have slipped |
| `priority_threads` | array | no | Slack threads needing attention |
| `team_commitments` | array | no | Per-person commitment tracking |
| `product_signals` | array | no | Product/initiative signals (also accepted as `elixir_signals`) |
| `drive_mentions` | array | no | Relevant Google Drive documents |
| `rollout_days` | integer | no | Days until main initiative target date |
| `rollout_note` | string | no | Freeform note shown next to countdown |
| `kanban` | object | no | Interactive board state |
| `milestones` | array | no | Project milestones tracked across briefs |
| `update_available` | boolean | no | Whether a newer Alfred version is available |
| `latest_version` | string | no | Latest available version string |
| `calibrations_checked` | array of strings | no | Calibration IDs evaluated this run |

---

## `delta`

| Field | Type | Description |
|---|---|---|
| `new_fires` | array of strings | New fires not in yesterday's brief |
| `resolved` | array of strings | Items resolved since yesterday |
| `status_changes` | array of strings | Notable status changes |
| `new_slipped` | array of strings | Items that slipped since yesterday |
| `other` | array | Anything else worth noting. Each item is a string OR `{"text": "...", "url": "..."}` to render a clickable ↗ link |

---

## `data_sources`

Keys: `calendar`, `slack`, `drive`, `gmail`, `granola`

Each key's value is `"ok"`, `"warn"`, or `"error"`. Add a `{key}_note` sibling
for any source with a warning or error (e.g. `"granola_note": "No sessions recorded today"`).

---

## `fires[]`

| Field | Type | Required | Description |
|---|---|---|---|
| `title` | string | yes | One-line headline shown in bold |
| `body` | string | yes | Context: what happened, who flagged it, when |
| `first_move` | string | yes | The single first action to take |
| `slack_url` | string | no | Deep-link to the Slack thread |

---

## `resolved_fires[]`

| Field | Type | Description |
|---|---|---|
| `title` | string | Short title of the resolved fire |
| `note` | string | How it was resolved / any caveats |

---

## `calendar_events[]`

| Field | Type | Description |
|---|---|---|
| `time` | string | Display string, e.g. `"9:00 AM"` |
| `title` | string | Event name |
| `note` | string | Prep note, context, or action |
| `done` | boolean | `true` grays out the row (for past events on re-runs) |
| `conflict` | boolean | `true` adds a ⚠️ conflict indicator |
| `priority` | boolean | `true` bolds the title |
| `prep` | object\|null | Inline prep card (see below). `null` = no prep card shown |

**`prep`**

| Field | Type | Description |
|---|---|---|
| `last_meeting` | object\|null | Most recent prior meeting with these attendees |
| `last_meeting.date` | string | Display date, e.g. `"Apr 28"` |
| `last_meeting.title` | string | Meeting title |
| `last_meeting.summary` | string | Two-sentence summary of key outcomes |
| `open_items` | array | Outstanding commitments for this meeting |
| `open_items[].tag` | string | `"you"` (you owe them) or `"them"` (they owe you) |
| `open_items[].who` | string\|null | Name if `tag = "them"`, else `null` |
| `open_items[].text` | string | Commitment description |
| `signals` | array | Recent Slack/calendar signals from attendees |
| `signals[].who` | string | `"Name · Source · Date"` label |
| `signals[].text` | string | Message or note content |

---

## `due_this_week[]` / `slipped[]`

| Field | Type | Description |
|---|---|---|
| `text` | string | The item description |
| `pill` | string | Optional label text for a color pill |
| `pill_color` | string | `red`, `yellow`, `green`, `blue`, or `gray` |

---

## `priority_threads[]`

| Field | Type | Description |
|---|---|---|
| `title` | string | Thread headline |
| `body` | string | What the thread is about and why it needs attention |
| `drafted` | boolean | `true` shows a "Draft ready in Slack" indicator |
| `slack_url` | string | Deep-link to open the thread |

---

## `team_commitments[]`

| Field | Type | Description |
|---|---|---|
| `person` | string | Display name |
| `items` | array | List of commitment objects (see below) |

**`items[]`**

| Field | Type | Description |
|---|---|---|
| `text` | string | The commitment |
| `status` | string | `done`, `shipped`, `in_progress`, `overdue`, `at_risk`, `stalled`, `blocked`, `no_signal` |
| `note` | string | Optional extra context shown after the status badge |

---

## `product_signals[]`

Also accepted under the legacy key `elixir_signals`.

| Field | Type | Description |
|---|---|---|
| `type` | string | `win` (green), `gap` (yellow), `strategy` (blue) |
| `title` | string | Signal headline |
| `body` | string | Detail |
| `url` | string | Optional link |
| `url_text` | string | Link label (default: `"View →"`) |

---

## `drive_mentions[]`

| Field | Type | Description |
|---|---|---|
| `title` | string | Document name and last-modified context |
| `owner` | string | Owner email |
| `url` | string | Direct link to the document |
| `note` | string | Why it's relevant today |

---

## `kanban`

| Field | Type | Description |
|---|---|---|
| `board_state.cards[]` | array | Full card list (see below) |
| `board_state_ts` | integer | Unix timestamp of last board write |
| `new_todo` | array | Cards added this run (shown in delta) |
| `acknowledgement` | string | Plain-text summary of board changes this run |

**`board_state.cards[]`**

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique card ID (e.g. `kb-abc123`) |
| `title` | string | Card title |
| `description` | string | Detail and acceptance criteria |
| `source_signal` | string | Where Alfred surfaced this from |
| `col` | string | `todo`, `in_progress`, or `done` |
| `source` | string | `alfred` (auto-surfaced) or `manual` |
| `added` | string | Date added, `YYYY-MM-DD` |
| `moved_done` | string\|null | Date moved to Done, or `null` |

---

## `milestones[]`

| Field | Type | Description |
|---|---|---|
| `name` | string | Milestone name |
| `description` | string | Plain-English description |
| `target_date` | string\|null | `YYYY-MM-DD` target, or `null` |
| `status` | string | `on_track`, `at_risk`, `stalled`, `complete`, `cancelled`, `active` |
| `summary` | string | One-line status summary for this brief |
| `signals` | array | Evidence items (see below) |

**`signals[]`**

| Field | Type | Description |
|---|---|---|
| `type` | string | `win`, `gap`, `strategy`, `concern`, `neutral` |
| `source` | string | Plain label: `slack`, `calendar`, `email`, `drive` |
| `text` | string | Signal description |
| `url` | string\|null | Optional deep-link |
