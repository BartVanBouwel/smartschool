# Changelog

All notable changes to the Smartschool integration.

## 0.8.1 - 2026-09-13

### Bugfixes
- **The real root cause of `mark_message_read`/`mark_message_unread` having no effect: both services were registered with a `lambda call: _async_mark_message_...(hass, call)`.** Home Assistant decides how to schedule a service handler by checking `asyncio.iscoroutinefunction()` on the callable itself -- a lambda that returns a coroutine always fails that check, even though calling it produces one. So HA scheduled it as a plain sync callback, called it once, and discarded the returned (never-awaited) coroutine without ever running its body -- while still reporting a successful (200 OK / empty response) service call. Confirmed live with a debug file written as the very first line of the handler: it never got created after calling the service. Fixed by registering real `async def` wrapper functions instead. This means `mark_message_unread` was equally broken, not just `mark_message_read`.
- Fixed `automations.yaml`'s "Smartschool - mark message read (webhook)" automation (the one driving the dashboard's mark-as-read button) still calling `smartschool_api.mark_message_read` -- the domain name from before the integration was renamed to `smartschool`. It's been silently failing (unknown service) since the rename.
- Fixed `configuration.yaml`'s `logger` block still pointing at `custom_components.smartschool_api` instead of `custom_components.smartschool`, meaning debug logging for this integration was never actually enabled since the rename either.

## 0.8.0 - 2026-09-13

### Bugfixes
- **`mark_message_read` service had no effect.** It relied on fetching the message content ("show message" action) to implicitly mark it read, per the `smartschool` library's own docs/naming -- but confirmed live (with a real unread message, including a 10-second wait) that this never flips Smartschool's server-side unread flag on this platform. The library only wraps the opposite action (`MarkMessageUnread`); its exact counterpart, `"mark message read"` (subsystem `postboxes`), isn't wrapped by the library but is accepted by the server and does flip the flag (confirmed live). The service now posts that action directly via the same XML dispatcher the library itself uses.
- **Message sensors for messages older than 14 days never refreshed once marked read**, even after the above fix. `_fetch_message_records()` only keeps a message "selected" (and therefore refreshed) while it's unread or within the last 14 days; once marked read, an old message dropped out of that selection entirely, so its existing sensor's `async_update()` found no matching record and silently kept showing stale attributes (`unread: true`) forever. Any message that already has a sensor entity is now always kept selected/refreshed, regardless of age or read status.

## 0.7.1 - 2026-09-13

### Bugfixes
- **Combined/level-group lessons (`planned-lesson-cluster-moments`) never showed up in any calendar.** Smartschool uses a third `plannedElementType` for lessons merged across courses or a course cluster (shown with a distinct icon in the app) that neither calendar knew about: `_is_lesson_item()`'s generic fallback correctly classified them as lessons (so the Planner calendar excluded them), but the Timetable calendar's own type whitelist didn't include this type, so they were excluded there too -- vanishing from both. Introduced a shared `_LESSON_TYPES` constant (now including `planned-lesson-cluster-moments`) used consistently across `_get_item_title`, `_is_lesson_item`, and the Timetable calendar's filter. Confirmed against a live query that these lessons were present in the raw `/planner/api/v1/planned-elements` response all along.

## 0.7.0 - 2026-09-13

### Removed
- **Per-item agenda sensors** (`SmartschoolAgendaItemSensor`, one entity per upcoming planner item). Fully redundant with the Planner and Timetable calendar entities, which already show the same planner data (all real-world `plannedElementType` values were verified to be covered by the two calendars combined) — and unlike a plain sensor, their number changed on every poll as items entered/left the 4-week window, churning the entity registry. Removed the now-unused `_detect_item_type` and `_get_item_start` helpers along with it.

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
