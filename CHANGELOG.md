# Changelog

All notable changes to the Smartschool integration.

## 0.6.1 - 2026-09-13

### Bugfixes
- **Severe performance regression: `_fetch_planned_elements` had no caching.** Since 0.6.0, every single agenda item sensor (one per upcoming planner item, potentially dozens per child) independently triggered its own full, uncached planner API fetch on every poll — on top of the planner and student sensors already doing so. With multiple children configured, this caused hundreds of redundant requests per poll cycle, exhausting the shared HTTP connection pool (`Connection pool is full, discarding connection`) and making the whole Home Assistant UI sluggish, including unrelated pages like Settings. Added a 10-minute session-level cache, matching the existing caching for messages and results.
- The calendar platform had its own separate, equally uncached planner fetch (`_fetch_raw_elements_for_session`), called independently by both the Planner and Timetable calendar entities every poll. Also now cached per session.
- `SCAN_INTERVAL` in `const.py` was defined as a plain `int` and never actually imported by the sensor/calendar platforms, so Home Assistant's much shorter default poll interval was used instead of the intended 15 minutes. Fixed to a proper `timedelta` and wired into both platforms.

## 0.6.0 - 2026-09-12

### Breaking changes
- **Renamed the integration from `smartschool_api` to `smartschool`.** Domain, folder, service names, and all internal identifiers changed accordingly. Existing config entries were created under the old `smartschool_api` domain and will **not** carry over automatically — remove the old integration and add it again under its new name after upgrading. Entity IDs are based on child name and sensor type (not on the domain), so most `entity_id`s stay the same; unique IDs and the `Timetable` calendar's entity id (previously `..._lessenrooster`) do change.
- All code comments, log messages and UI text were translated from Dutch to English (Smartschool's own Dutch category labels used for classification, e.g. "toets"/"taak"/"studeer", are intentionally left as-is since they match real API content, not UI text).

### Bugfixes
- **Agenda item sensors never refreshed after initial setup** (no `async_update()`, static data from setup only). They now refresh periodically, matched to their planner item by a stable id instead of their creation-time list position.
- **Unread status of messages was inverted.** The `unread` field of the Smartschool API turned out to mean "has been opened/read" in practice (False = truly unread) rather than what the name suggests. The interpretation in `_message_is_unread()` was flipped.
- **Our own polling silently marked messages as read.** Every fetch cycle opened (via `Message()`) the full content of all selected messages, which Smartschool registers as "read" — even for messages the user had never opened. The read status is now automatically restored to unread (`MarkMessageUnread`) right after fetching content, for messages that were previously unread, and content stays cached so this only happens once per message.
- **`mark_message_read`/`mark_message_unread` services crashed.** Registered with an incorrect function signature (`hass` wasn't passed in), causing every call to raise a `TypeError`.
- **New results never appeared automatically.** There was no mechanism to add new test results as a new sensor during a regular update cycle (only messages had this). Added `_add_new_result_entities()`, mirroring the messages approach.
- **`SmartschoolPlannerSensor` crashed on every poll cycle** with `AttributeError: object has no attribute '_child_name'` — `child_name` was never stored in `__init__`.
- **Sensors could freeze permanently after a hanging HTTP call.** No Smartschool request had a timeout; a stuck call could permanently occupy an executor thread, so that specific sensor would never update again. All requests now get a 30s timeout.

### New features
- **Relative `<img src="...">` paths in message content are automatically made absolute** (`_fix_relative_image_urls()`), using the logged-in user's platform subdomain as the base URL. Prevents broken images when the body HTML is displayed outside of Smartschool (e.g. in a Lovelace card).
- **Per-instance debug logging** for unread status: `logging/{child}_unread_debug.log`, shows raw header fields and the derived status per message.
- After `mark_message_read`/`mark_message_unread`: the cache is invalidated and the sensor is immediately force-refreshed (`homeassistant.update_entity`) instead of waiting for the next poll.
- Unit tests added (`tests/test_image_urls.py`) for the URL-rewriting logic.
- `README.md` added describing current functionality.
