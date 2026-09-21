# Changelog

All notable changes to the Smartschool integration.

## 0.24.0 - 2026-09-21

### Features
- **Optional `person.<child>` entity**, so a child can be used directly on dashboards (e.g. the built-in "Person" card/badge, or any card with a person picker) instead of only via the Student sensor. Off by default; enable it per child via the integration's **Configure** button. Kept in sync with the Student sensor's name and profile picture on every update. Created through Home Assistant's own person storage collection (the same mechanism `Settings -> People` uses), so it's a normal, user-editable entity that isn't removed if the integration itself is later removed.

## 0.23.0 - 2026-09-21

### Bugfixes
- **The Student sensor showed the wrong person**: `full_name` and `entity_picture` were scraped from whichever teacher happened to be the first "organiser" found in the planner data (falling back to `session.authenticated_user` if none matched), which itself is the *login account*, not the child -- on a parent/co-account login that's the parent, e.g. name "Bart Van Bouwel" for a login used to view "Stella". `startingWithFirstName`/`startingWithLastName` were also wrongly treated as separate first/last name parts and concatenated, when they're actually two full-name renderings of the same person (first-name-first vs. last-name-first) -- producing a visibly duplicated name on top of being the wrong person entirely.
- Fixed by looking the student up via the message-composer's recipient search (`MessageComposerForm.search_users`) for the configured child name instead, matched to the login's own numeric user id -- this is the same lookup Smartschool itself uses when you start writing that student a message, and returns their real full name, own profile picture and class.

### Features
- **Student sensor now exposes `class_name`** (e.g. "1A02"), and the entity's friendly name is now just the configured child's name (e.g. "Stella") instead of "Stella Student".

### Other
- Removed the `organiser_picture_urls`/`participant_picture_urls` attributes -- unused noise scraped from planner data that had nothing reliably to do with the student's own profile.
- Investigated exposing the class's home-room teacher ("klastitularis") too, but there's no dedicated field for it in any endpoint used by the integration or the underlying `smartschool` library -- the closest available data (a lesson's organiser) is just that subject's teacher, not necessarily the titularis, so it was left out rather than risk showing another wrong name.
- **Removed the "Planner Count" diagnostic sensor** (`SmartschoolPlannerSensor`) -- it was only ever a development leftover from before the message/result sensors existed, and its raw item count served no purpose once the planner calendar took over showing that data. It also still fetched messages/results and discovered new sensors for them on every poll, which the message/result sensors already do themselves once they exist; that discovery step moved to the Student sensor's update instead, so a child with zero messages/results at setup time still picks up their first one automatically.

## 0.22.1 - 2026-09-21

### Other
- **Made the integration installable as a HACS custom repository**: added `hacs.json` (`content_in_root: true`, since the standalone repo has the integration files at its root rather than under `custom_components/`) and a `LICENSE` file (MIT), both required by HACS' validation. Fixed `manifest.json`'s `documentation`/`issue_tracker` links, which incorrectly pointed at the upstream `smartschool` Python library's repo instead of this integration's own repo. Documented the HACS custom-repository install steps in the README. Not submitted to the HACS default store (would additionally need GitHub topics and a `hacs/action` validation workflow) — this only covers manual "custom repository" installs.

## 0.22.0 - 2026-09-21

### Features
- **Planner calendar events for taken/toetsen/meebrengen are now prefixed with their Smartschool type** (e.g. "Taak: Maak pagina 5", "Toets: Hoofdstuk 3"), read from the planner's own `assignmentType.name` field (with its "( < 14 dagen )"-style qualifier stripped) rather than guessed from keywords in the title.

### Bugfixes
- **Assignments linked to a lesson cluster (`planned-lesson-cluster-assignments`) were misclassified as lessons** because they carry a `courses` field like real lessons do, so they showed up under the course name instead of their own task title. They're now correctly treated as assignments, same as plain `planned-assignments`.

## 0.21.0 - 2026-09-20

### Features
- **CSV/debug-log export (`logging/<child>_*.csv`, `logging/<child>_unread_debug.log`) is now an opt-in option, off by default**, instead of always-on. Reachable via the integration's "Configure" button per config entry (Settings -> Devices & services -> Smartschool -> a child -> Configure). Changing it reloads that entry automatically. This also addresses the underlying reason it was worth turning off: the unread-debug log had no rotation or size limit and could grow to multiple hundred MB over a few weeks, containing real message content -- an explicit opt-in is a better default than "on forever, unbounded".

## 0.20.0 - 2026-09-20

### Features
- **`smartschool-messages-card`'s `child` field is now a multi-select `children` list** (checkboxes in the editor), instead of a single child or "all". Old configs with the singular `child` string still work (`selectedChildren()` falls back to it) and get migrated to `children` the next time the editor is touched. The refresh button now scopes to all currently-selected children (one representative entity per child), or every configured child if none are selected.

### Other
- **Privacy pass before sharing the integration**: replaced example child name "Felix" and school subdomain "kosh.smartschool.be" in README.md, the results card's header comment, and the test file with generic placeholders ("Alex", "myschool.smartschool.be"); removed a changelog line's reference to a real child's debug CSV. The `logging/` folder (per-child message/result/calendar CSVs and debug logs) was already gitignored and was never committed. The integration itself has no hardcoded school, username, or child name anywhere -- `main_url`, credentials and child naming are all free-text config-flow fields, so it should work unmodified for any Smartschool school and any child names.

## 0.19.0 - 2026-09-20

### Bugfixes
- **Found the actual root cause of "Custom element doesn't exist" via a matching issue in another HA integration that bundles a custom card the same way** (aex351/home-assistant-neerslag-card #58: "extra_module_url races the frontend's custom element registry"). `add_extra_js_url()` injects an eager `<script>` that runs *concurrently with* Home Assistant's own frontend bundle while it boots -- and that bundle replaces `window.customElements` with its own scoped registry shim during that boot. If our script's `customElements.define()` runs before that swap (which it usually does, and a warm cache makes it resolve *faster*, making the bug *more* likely, matching exactly what was observed), it registers on the old registry object while Lovelace later checks the new one -- so the card silently "doesn't exist" to it, unrelated to actual load timing/speed.
- **Fix: stopped using `add_extra_js_url()` for our own card scripts entirely** (still used as a fallback only if Lovelace resource registration itself fails, e.g. a YAML-mode dashboard). Now relies solely on the Lovelace resource loader (added in 0.18.0), which runs after that frontend bundle/shim swap has already completed and doesn't hit this race. `_async_register_lovelace_resource()` now returns whether it succeeded so `async_setup()` knows when the `add_extra_js_url()` fallback is actually needed.

## 0.18.1 - 2026-09-20

### Bugfixes
- **Reproduced the exact "Custom element doesn't exist" timing on a cold/hard load, self-heals on a subsequent normal reload (confirmed live: broken → F5 fixes it → Ctrl+F5 breaks it again → F5 fixes it again), even with both cards now registered as real Lovelace resources.** This confirms it's a genuine load-time race on a dashboard with dozens of competing resources -- Lovelace can try to build a card before this module's `import()` finishes, and doesn't appear to retry on its own. Both card scripts now fire a `window.dispatchEvent(new Event("ll-rebuild", ...))` right after registering their custom element -- the same event Home Assistant's own dashboard listens for to rebuild a view's cards -- so any instance already stuck in the broken state self-heals within a moment of this script finishing, instead of requiring the user to notice and manually reload.

## 0.18.0 - 2026-09-20

### Bugfixes
- **Root cause of the intermittent "Custom element doesn't exist: smartschool-messages-card" found.** `frontend.add_extra_js_url()` injects a fire-and-forget `import(...).catch(...)` that is *not* awaited anywhere before Lovelace starts building the dashboard's cards -- confirmed live: the browser console showed "SMARTSCHOOL-MESSAGES-CARD is loaded" (so the module did load and register), yet the card still errored, because Lovelace had already given up before that happened. This only showed up on a dashboard with dozens of other resources competing for load time (confirmed: fine on a phone, broken on a heavier laptop dashboard) -- unlike the *actual* Lovelace resources list every other HACS card here goes through, which Home Assistant's own `load-resources.ts` properly awaits before building cards.
- **Fix:** in addition to `add_extra_js_url` (kept as a fallback), the integration now also auto-registers the two card scripts (and mammoth.js) as real Lovelace resources via the same storage collection the "Add resource" UI uses (`_async_register_lovelace_resource()`), so they go through that awaited path like every other card. This touches internal, undocumented Lovelace APIs and is wrapped defensively -- if it can't register (e.g. a YAML-mode dashboard with no writable resource collection), it logs a warning instead of failing, and the resource can still be added by hand as a fallback (Settings -> Dashboards -> Resources, URL as before, type "JavaScript Module").

## 0.17.1 - 2026-09-20

### Features
- **Both cards now log `console.info(...)` on load**, matching the pattern every other installed Lovelace card uses -- makes it possible to confirm in the browser console whether the script loaded and executed at all, instead of silence being ambiguous between "loaded fine, nothing to log" and "never loaded".

## 0.17.0 - 2026-09-20

### Features
- **Added a refresh button to both cards** (top-right on `smartschool-results-card`, next to the "Messages"/"Berichten" title on `smartschool-messages-card`), calling the new `smartschool.refresh` service. On `smartschool-messages-card`, refreshing scopes to the currently selected child (`child` config) if one is set, otherwise refreshes every configured child, matching "the (selected) children" the card is currently showing.
- **Added `smartschool.refresh` service** (`__init__.py`): clears each session's results/messages cache timestamps and then forces `homeassistant.update_entity` on that child's sensors -- plain `update_entity` alone isn't enough, since `_fetch_results`/`_fetch_message_records` still return cached data as long as it's within the normal TTL. Accepts an optional `entity_id` (one or more) to scope the refresh to specific children; omitted, every configured child is refreshed.
- **Added the teacher's name to a result's detail view** (`smartschool-results-card`), pulled from the sensor's existing `Teacher` attribute.

## 0.16.2 - 2026-09-20

### Bugfixes
- **A plain browser reload (F5) could show "Configuration error" for every card, while a hard reload (Ctrl+F5) always fixed it.** The card/mammoth scripts are registered as `type="module"`, which browsers cache very aggressively on the exact URL -- since that URL never changed between edits, a normal reload could keep reusing a stale (possibly from-before-a-fix, broken) cached copy indefinitely; only a hard reload bypasses that cache. Added a `?v=<mtime>` cache-busting query parameter (via `_asset_version()`) to each registered URL, derived from the file's last-modified time, so any future edit to these files automatically gets a fresh URL on the next Home Assistant start -- no more relying on users to hard-refresh, and no version number to remember bumping by hand.

## 0.16.1 - 2026-09-20

### Features
- **Bundled `mammoth.browser.min.js`** (used by `smartschool-messages-card`'s inline .docx preview) into the integration (`www/mammoth.browser.min.js`) and auto-registered it via `frontend.add_extra_js_url(..., es5=True)` -- loaded as a classic script, not an ES module, since it's a UMD bundle that assigns to `window.mammoth` (a module's top-level `this` isn't `window`, which would break that assignment). The manually-added `/local/smartschool/mammoth.browser.min.js` Lovelace resource is no longer needed and can be removed.

## 0.16.0 - 2026-09-20

### Features
- **Added `smartschool-messages-card`**, the same native-Lovelace-card treatment as `smartschool-results-card` applied to the messages mailbox view (`www/smartschool-messages-card.js`, auto-registered via `frontend.add_extra_js_url()`). Ported 1:1 from the hand-built `html-template-card` mailbox layout (message list + reading pane, avatar initials, attachment previews incl. inline PDF/docx viewing via `window.mammoth` if present). Marks a message read via a direct `hass.callService('smartschool', 'mark_message_read', ...)` call instead of the webhook/automation combo the old card needed -- the "Smartschool - mark message read (webhook)" automation is no longer required once a dashboard switches to this card. Has a visual editor (`title`, `language` EN/NL). Scans all `sensor.*_message_*` entities regardless of child, same as the original template (a combined mailbox across every configured login).

## 0.15.0 - 2026-09-20

### Features
- **`smartschool-results-card` now shows "Counts towards average" (yes/no) for every result** in its detail view, so it's clear at a glance why a result is or isn't included.
- **Added `include_non_counting` toggle** (editor "Details" section, defaults to off = previous behavior) that, when enabled, includes `does_count: false` results in the course/period average and the per-period chart too, alongside the normally-counting ones.

## 0.14.1 - 2026-09-20

### Bugfixes
- **`achieved_points`/`total_points` were missing (showing as "0/0" in the results card) whenever Smartschool's score description used a comma as the decimal separator** (e.g. `"5,5/6"`, `"11,5/14"`) -- `_result_graphic()` parsed the fallback `achieved/total` split with `float()`, which raises on a comma decimal, was silently caught, and left both fields `None`. Confirmed live in a child's `logging/<child>_results.csv`: every result with a comma in its `graphic_description` had empty `achieved_points`/`total_points`, while plain-integer scores (e.g. `"6/9"`) parsed fine. Now normalizes the comma to a dot before parsing.
- (Separately confirmed not a bug: a course/period showing "n.v.t." and no chart on the results card, e.g. Frans for one child, is correct when Smartschool itself marks every result in it `does_count: false` -- other courses in the same data have `does_count: true` results and render normally.)

## 0.14.0 - 2026-09-20

### Features
- **`smartschool-results-card` editor is now in English**, with a new `language` field (English/Nederlands dropdown, defaults to `nl` for existing configs) that independently controls the language of the card's own rendered text (labels, "n/a"/"n.v.t.", date formatting, etc.) via a small `STRINGS` table.
- **Editor now shows every color/icon field pre-filled with its default value** (already true structurally, via merging `DEFAULTS` into the form's `data`) and adds a "Reset colors & icons to default" button that resets just the seven color/icon fields, leaving `child`/`title`/`language`/`show_chart`/`show_average` untouched.

## 0.13.0 - 2026-09-20

### Features
- **`smartschool-results-card` editor: real color pickers and icon pickers.** `course_color`/`period_color`/`result_color`/`unread_color` switched from plain text fields to `selector: {color_rgb: {}}` (a genuine RGB color wheel), stored as `[r, g, b]` arrays -- plain CSS-string values from an existing config still work (`colorToCss()` accepts both). Added `course_icon`/`period_icon`/`result_icon` (`selector: {icon: {}}`, a searchable mdi icon picker); `result_icon` falls back to the icon Smartschool itself provides on the sensor when left empty. Added a configurable `unread_color` for the "new result" dot, previously hardcoded gold.

## 0.12.0 - 2026-09-20

### Features
- **`smartschool-results-card` visual editor now has a collapsible "Details" section** (`ha-form` `expandable` schema) with: `show_chart` and `show_average` toggles, and `course_color` / `period_color` / `result_color` text fields accepting any CSS color (hex or `rgba(...)`) for the three box levels' backgrounds. All five are optional and fall back to the previous look when left empty.

## 0.11.1 - 2026-09-20

### Bugfixes
- **Card picker showed a spinner forever for `smartschool-results-card` and it couldn't be added.** `setConfig()` threw when `child` was missing/empty, and the picker/preview dialog calls `setConfig()` with a stub config (from `getStubConfig()`) without catching exceptions from it -- an empty `child` there (e.g. no result sensors loaded yet at that moment) left the preview stuck instead of showing a normal error. `setConfig()` no longer throws; a missing `child` now renders a plain "kies een kind" placeholder like any other custom card's incomplete-config state.

## 0.11.0 - 2026-09-20

### Features
- **`smartschool-results-card` now has a visual editor.** Added `getConfigElement()`/`getStubConfig()` plus a `smartschool-results-card-editor` element built on `ha-form`, with a dropdown of children auto-detected from `sensor.<child>_result_*` entities currently in `hass.states` -- no more "Visual editor not supported" / hand-typed YAML needed to pick a child.
- Card header now title-cases the child name when no explicit `title` is set (`child: alex` → header "Alex" instead of "alex"). An explicitly given `title` is still used verbatim.
- Course/period averages now show "n.v.t." instead of a misleading "0%" when none of that course/period's results have `does_count: true` (e.g. Smartschool marking every result in that period as non-counting) -- the chart is likewise only omitted in that case, not because of any parsing error.

## 0.10.2 - 2026-09-20

### Bugfixes
- **"Custom element not found: smartschool-results-card" after setup.** `frontend.add_extra_js_url()` was called from `async_setup()` without the integration declaring a dependency on `frontend` (`dependencies: []` in the manifest), so there was no guarantee the frontend component's internal state existed yet when we called it -- it could silently no-op or raise before ever registering the URL, meaning the card's JS was never added to the page. Declared `dependencies: ["http", "frontend"]` in `manifest.json` so HA sets those up first, and wrapped the call in a try/except with logging so a future failure there is visible instead of silently breaking card loading.

## 0.10.1 - 2026-09-20

### Features
- **`smartschool-results-card`'s JS is now auto-registered on every frontend page load** via `frontend.add_extra_js_url()`, the same mechanism integrations like Browser Mod and Spook use. No more manual "add as a Lovelace resource" step -- the card is available right after a restart.

## 0.10.0 - 2026-09-20

### Features
- **Added `smartschool-results-card`, a native Lovelace custom card bundled with the integration** (`www/smartschool-results-card.js`, served at `/smartschool_static/smartschool-results-card.js`). Replaces the hand-built `html-template-card` + webhook/automation combo used so far for showing a child's results: groups by course/period, shows a per-period percentage chart, and marks a result read via a direct `hass.callService()` call to `smartschool.mark_result_read` instead of a webhook (no automation needed for this card). Requires the file to be added as a Lovelace JavaScript-module resource; see README.

## 0.9.1 - 2026-09-20

### Bugfixes
- **`mark_result_read` raised "Unknown Smartschool result entity" for a real, existing sensor.** Result sensors were registered into a dict keyed by `sensor.entity_id` right after an unawaited `async_add_entities(...)` call -- HA assigns `entity_id` asynchronously, so it wasn't necessarily set yet at that point, especially for results discovered after initial setup (via the periodic update path). That could capture a stale/empty key, so a later lookup by the sensor's real `entity_id` failed. Replaced the dict with a flat list of sensor instances, matched by their *current* `entity_id` at service-call time instead.

## 0.9.0 - 2026-09-20

### Features
- **Result sensors now expose an `unread` attribute.** A result sensor starts with `unread: true` when it's first created (i.e. a new result appeared). Refetching/updating an *existing* result (`async_update`, `_apply_result`) never touches this flag, so it stays as-is until explicitly cleared. Added a `mark_result_read` service (mirrors `mark_message_read`'s entity-lookup pattern) to flip a result's `unread` attribute to `false`, meant to be called from a dashboard card on click. Since Smartschool itself has no server-side concept of "read" for results, this status is tracked purely locally and survives HA restarts via `RestoreEntity`.

## 0.8.2 - 2026-09-19

### Bugfixes
- **Downloaded attachments lost their file extension.** `slugify(attachment_name)` turns every dot into an underscore, so `"report.pdf"` was saved (and linked via `download_url`) as `report_pdf` — no `.pdf` extension. Static file serving then couldn't determine the correct `Content-Type`, so browsers wouldn't render PDFs inline (an `<iframe>` pointed at the file just showed nothing); explicit `download` links still worked since those force a save using the *original* filename regardless of the server's response headers. Added `_slugify_filename()`, which slugifies only the base name and keeps the original extension intact. Only affects attachments fetched from now on — files already saved under the old, extension-less names need their message re-fetched (e.g. via `mark_message_unread` then `mark_message_read`) to regenerate with the correct filename.

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
