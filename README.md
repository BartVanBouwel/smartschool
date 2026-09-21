![Version](https://img.shields.io/badge/version-0.22.1-blue)

# Smartschool for Home Assistant

A custom Home Assistant integration that exposes [Smartschool](https://www.smartschool.be/) data (messages, results, planner/agenda and timetable) as sensors and calendars — a convenient way for parents to see what's going on for their kid(s) at a glance, without checking the Smartschool app every time.

Built on top of the [`smartschool`](https://github.com/svaningelgem/smartschool) Python library.

## Features

### Sensors
- **Messages** — a separate sensor per relevant message (unread + messages from the last 14 days), with subject, sender, full body (HTML), recipients, attachments and `unread` status as attributes. Attachments are automatically downloaded locally (`www/smartschool_messages/`) and reachable via a `download_url` attribute. New messages automatically get a new sensor, without reloading the integration.
- **Results** — a separate sensor per result/course combination, with score, percentage, feedback, teacher, period, publication status and `unread` status as attributes. New results automatically get a new sensor and start out unread; the `unread` flag is only ever cleared via the `smartschool.mark_result_read` action (e.g. clicking the result on a dashboard card) — it's left untouched when an existing result gets updated with fresh data, and survives Home Assistant restarts.
- **Student** — name and profile picture of the logged-in student.
- **Planner Count** — total number of planned elements (diagnostic sensor).

### Calendars
- **Planner** — all planned items (tests, tasks, activities, ...) as calendar events. Tasks/tests/to-bring items are titled with their Smartschool type (e.g. "Taak: Maak pagina 5", "Toets: Hoofdstuk 3"), read from Smartschool's own `assignmentType`.
- **Timetable** — the class schedule as calendar events.

### Actions (services)
- `smartschool.mark_message_read` — deliberately open a message, so Smartschool registers it as read.
- `smartschool.mark_message_unread` — mark a message back as unread.
- `smartschool.mark_result_read` — flag a result sensor's `unread` attribute as read. This status is tracked entirely locally (Smartschool has no server-side read/unread concept for results); intended to be called from a dashboard card when a result is clicked.

The integration never fetches the content of an unread message on its own (that would silently mark it as read) — only via the actions above, or once it's already been read elsewhere.

### Dashboard cards
- **`smartschool-results-card`** — a native Lovelace custom card bundled with the integration (`www/smartschool-results-card.js`, served at `/smartschool_static/smartschool-results-card.js` and auto-registered as a Lovelace resource on startup — no manual resource needed), showing one child's results grouped by course and period, with a per-period percentage chart and click-to-mark-read on unread results. Add it to a dashboard:
  ```yaml
  type: custom:smartschool-results-card
  title: Alex
  child: alex   # matches the sensor.<child>_result_* entities
  ```
  No automation or webhook needed for this card — it calls `smartschool.mark_result_read` directly. Has a visual editor (English UI; child picker dropdown auto-detected from existing result sensors) — adding the card through the dashboard UI works without touching YAML. A `language` field (English/Nederlands) independently controls the language the *card itself* renders its text in, defaulting to `nl`. A collapsible "Details" section in the editor exposes `show_chart` / `show_average` (booleans), `include_non_counting` (include `does_count: false` results in the average/chart too, default off), `course_icon` / `period_icon` / `result_icon` (mdi icon pickers, `result_icon` empty = use the icon Smartschool provides), and `course_color` / `period_color` / `result_color` / `unread_color` (real RGB color pickers, stored as `[r, g, b]`) — plus a "reset to default" button for those seven color/icon fields. Each result's detail view also shows whether it counts towards the average.
- **`smartschool-messages-card`** — the same native-card treatment applied to the messages mailbox view (`www/smartschool-messages-card.js`, also auto-registered). A message list + reading pane (avatar initials, attachments with inline PDF/docx preview via `window.mammoth` if present on the page). Add it to a dashboard:
  ```yaml
  type: custom:smartschool-messages-card
  title: Berichten
  ```
  No automation or webhook needed — clicking an unread message calls `smartschool.mark_message_read` directly (the old "Smartschool - mark message read (webhook)" automation can be removed once a dashboard uses this card instead of the old `html-template-card`). Has a visual editor (`title`, `language` EN/NL, a `children` multi-select to limit the mailbox to specific kids). Defaults to scanning all `sensor.*_message_*` entities regardless of child — a combined mailbox across every configured login. `mammoth.browser.min.js` (used for inline .docx attachment preview) is bundled and auto-registered too — a manually-added `/local/...` Lovelace resource for it can be removed.

### Other
- Multiple children/accounts at once: each Smartschool login is a separate config entry, with sensors/calendars per child.
- Relative image paths (`<img src="/...">`) in message content are automatically rewritten to absolute Smartschool URLs, so images also display correctly outside of Smartschool (e.g. in a Lovelace card).
- Optional CSV export of messages/results and an unread-status debug log per child in `logging/` (handy for debugging or external processing) — off by default, turn it on per child via the integration's **Configure** button (Settings → Devices & services → Smartschool → the child → Configure).
- Debug logging of all Smartschool API requests/responses (with redaction of passwords/tokens) — enable it via the standard Home Assistant `logger` configuration on `custom_components.smartschool`.

## Installation

### Via HACS (custom repository)

This repository isn't in the default HACS store, so add it as a custom repository:

1. HACS → the **⋮** menu (top right) → **Custom repositories**.
2. Repository: `https://github.com/BartVanBouwel/smartschool`, type: **Integration**.
3. Find "Smartschool" in HACS and install it.
4. Restart Home Assistant.
5. Add the integration via **Settings → Devices & services → Add integration → Smartschool**.

### Manually

1. Copy the `smartschool` folder into `config/custom_components/`.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & services → Add integration → Smartschool**.

## Configuration

When adding the integration, the config flow asks for:

| Field | Required | Description |
|---|---|---|
| Username | Yes | Your Smartschool login name |
| Password | Yes | Your Smartschool password |
| Platform URL | Yes | Your school's subdomain, e.g. `myschool.smartschool.be` |
| MFA | No | Date of birth (`YYYY-MM-DD`) or Google Authenticator secret, if 2FA is enabled |
| Name | No | Display name for this child/account (defaults to being derived from the username) |

Add the integration multiple times (each with a different login) to track multiple children.

## Requirements

- `smartschool==0.10.0`
- `requests>=2.32.0`
- `pyotp>=2.9.0`

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full history of bug fixes and new features per version.
