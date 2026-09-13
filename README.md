![Version](https://img.shields.io/badge/version-0.8.0-blue)

# Smartschool for Home Assistant

A custom Home Assistant integration that exposes [Smartschool](https://www.smartschool.be/) data (messages, results, planner/agenda and timetable) as sensors and calendars — a convenient way for parents to see what's going on for their kid(s) at a glance, without checking the Smartschool app every time.

Built on top of the [`smartschool`](https://github.com/svaningelgem/smartschool) Python library.

## Features

### Sensors
- **Messages** — a separate sensor per relevant message (unread + messages from the last 14 days), with subject, sender, full body (HTML), recipients, attachments and `unread` status as attributes. Attachments are automatically downloaded locally (`www/smartschool_messages/`) and reachable via a `download_url` attribute. New messages automatically get a new sensor, without reloading the integration.
- **Results** — a separate sensor per result/course combination, with score, percentage, feedback, teacher, period and publication status. New results automatically get a new sensor.
- **Student** — name and profile picture of the logged-in student.
- **Planner Count** — total number of planned elements (diagnostic sensor).

### Calendars
- **Planner** — all planned items (tests, tasks, activities, ...) as calendar events.
- **Timetable** — the class schedule as calendar events.

### Actions (services)
- `smartschool.mark_message_read` — deliberately open a message, so Smartschool registers it as read.
- `smartschool.mark_message_unread` — mark a message back as unread.

The integration never fetches the content of an unread message on its own (that would silently mark it as read) — only via the actions above, or once it's already been read elsewhere.

### Other
- Multiple children/accounts at once: each Smartschool login is a separate config entry, with sensors/calendars per child.
- Relative image paths (`<img src="/...">`) in message content are automatically rewritten to absolute Smartschool URLs, so images also display correctly outside of Smartschool (e.g. in a Lovelace card).
- CSV export of messages and results per child in `logging/` (handy for debugging or external processing).
- Debug logging of all Smartschool API requests/responses (with redaction of passwords/tokens) — enable it via the standard Home Assistant `logger` configuration on `custom_components.smartschool`.

## Installation

1. Copy the `smartschool` folder into `config/custom_components/`.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & services → Add integration → Smartschool**.

## Configuration

When adding the integration, the config flow asks for:

| Field | Required | Description |
|---|---|---|
| Username | Yes | Your Smartschool login name |
| Password | Yes | Your Smartschool password |
| Platform URL | Yes | Your school's subdomain, e.g. `kosh.smartschool.be` |
| MFA | No | Date of birth (`YYYY-MM-DD`) or Google Authenticator secret, if 2FA is enabled |
| Name | No | Display name for this child/account (defaults to being derived from the username) |

Add the integration multiple times (each with a different login) to track multiple children.

## Requirements

- `smartschool==0.10.0`
- `requests>=2.32.0`
- `pyotp>=2.9.0`

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full history of bug fixes and new features per version.
