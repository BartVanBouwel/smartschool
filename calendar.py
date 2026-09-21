import csv
import json
import logging
import os
from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util, slugify

from .const import DOMAIN, SCAN_INTERVAL  # noqa: F401 (SCAN_INTERVAL is read by HA's entity platform)

_LOGGER = logging.getLogger(__name__)
_LOG_DIR = "/config/custom_components/smartschool/logging"


def _get_item_value(item, *keys):
    """Read a value from a dict or object, trying multiple possible field names."""
    if isinstance(item, dict):
        for key in keys:
            if key in item:
                return item[key]
        return None

    for key in keys:
        if hasattr(item, key):
            return getattr(item, key)
    return None


def _stringify(value):
    """Turn an item field into a text value."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return " ".join(_stringify(v) for v in value if _stringify(v))
    if hasattr(value, "name"):
        return str(value.name)
    if hasattr(value, "__dict__"):
        return str(value)
    return str(value)


def _get_course_name(item):
    """Determine the course name from Smartschool's courses field, if available."""
    courses = _get_item_value(item, "courses")
    if courses is None:
        return None
    if isinstance(courses, (list, tuple, set)):
        for course in courses:
            name = _get_item_value(course, "name")
            if name:
                return str(name)
        return None
    if isinstance(courses, dict):
        name = _get_item_value(courses, "name")
        if name:
            return str(name)
        return None
    name = getattr(courses, "name", None)
    if name:
        return str(name)
    return None


def _get_assignment_type_label(item):
    """Return a short display label for the planner's assignment type (e.g. 'Taak', 'Toets', 'Meebrengen').

    Smartschool's `assignmentType.name` includes a parenthesized qualifier (e.g. "Taak ( < 14
    dagen )") that's only useful in the planner UI itself, so it's stripped for the calendar title.
    """
    assignment_type = _get_item_value(item, "assignmentType", "assignment_type")
    if assignment_type is None:
        return None
    name = _get_item_value(assignment_type, "name")
    if not name:
        return None
    label = str(name)
    if "(" in label:
        label = label[: label.index("(")].rstrip()
    return label or None


def _get_assignment_description(item):
    """Read a description if the planner provides one directly."""
    direct_description = _get_item_value(
        item,
        "description",
        "descriptionText",
        "notes",
        "note",
    )
    if direct_description:
        return _flatten_description_text(direct_description)
    return ""


def _log_value(value):
    """Make dataclasses, dates and nested values suitable for CSV log files."""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value.isoformat() if hasattr(value, "isoformat") else value


def _write_csv_log(filename, rows):
    """Write a CSV log with all fields present in the current response."""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
            if not fieldnames:
                fieldnames = ["logged_at", "calendar"]
        with open(os.path.join(_LOG_DIR, filename), "w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows({key: _log_value(value) for key, value in row.items()} for row in rows)
    except OSError as err:
        _LOGGER.warning("Could not write Smartschool CSV log %s: %s", filename, err)


def _log_planner_items(calendar_name, elements):
    """Log planner items for a calendar."""
    rows = []
    for item in elements:
        row = {"logged_at": dt_util.utcnow().isoformat(), "calendar": calendar_name}
        row.update(item if isinstance(item, dict) else {"item": item})
        rows.append(row)
    _write_csv_log(f"{slugify(calendar_name)}_planner.csv", rows)


def _get_planned_element_type(item):
    """Read Smartschool's `plannedElementType` field."""
    value = _get_item_value(item, "plannedElementType", "planned_element_type", "type")
    if value is None:
        return None
    return str(value)


# plannedElementType values that represent an actual timetable lesson (as opposed to
# a to-do, assignment or school activity). `planned-lesson-cluster-moments` covers
# combined/level-group lessons (e.g. a lesson merged across multiple courses or a
# course cluster) -- Smartschool shows these with their own icon in the app.
_LESSON_TYPES = {
    "planned-lesson-free-days",
    "planned-placeholders",
    "planned-lessons",
    "planned-lesson-cluster-moments",
}


def _get_item_title(item):
    """Determine the title of an item based on Smartschool type and data."""
    planned_type = _get_planned_element_type(item)

    if planned_type == "planned-lesson-free-days":
        name = _get_item_value(item, "name", "title")
        if name is not None:
            return name

    if planned_type in _LESSON_TYPES - {"planned-lesson-free-days"}:
        course_name = _get_course_name(item)
        if course_name:
            return course_name

    if _is_lesson_item(item):
        if planned_type not in _LESSON_TYPES:
            course_name = _get_course_name(item)
            if course_name:
                return course_name

    value = _get_item_value(item, "title", "name", "subject", "course", "lessonName", "className")
    if value is not None:
        return value
    return "Unknown"


def _is_lesson_item(item):
    """Smartschool lesson items are recognized via `plannedElementType` and `courses`."""
    if item is None:
        return False

    planned_type = _get_planned_element_type(item)
    if planned_type in _LESSON_TYPES:
        courses = _get_item_value(item, "courses")
        if planned_type == "planned-lesson-free-days":
            return True
        if courses is None:
            return False
        if isinstance(courses, str):
            return bool(courses.strip())
        if isinstance(courses, (list, tuple, set)):
            return len(courses) > 0
        if isinstance(courses, dict):
            return bool(courses)
        return True

    if planned_type in {"planned-school-activities", "planned-assignments", "planned-lesson-cluster-assignments"}:
        return False

    courses = _get_item_value(item, "courses")
    if courses is None:
        return False
    if isinstance(courses, str):
        return bool(courses.strip())
    if isinstance(courses, (list, tuple, set)):
        return len(courses) > 0
    if isinstance(courses, dict):
        return bool(courses)
    return True


def _get_item_start(item):
    """Determine the start time of a Smartschool item in both old and new API structures."""
    period = _get_item_value(item, "period", "period_obj")
    if period is not None:
        start = _get_item_value(period, "date_time_from", "dateTimeFrom")
        if start is not None:
            return start

    value = _get_item_value(item, "start", "dateTimeFrom", "date_time_from")
    if value is not None:
        return value

    for candidate in _iter_nested_values(item):
        if "from" in str(candidate).lower() or "start" in str(candidate).lower():
            if isinstance(candidate, (datetime, str)):
                return candidate
    return None


def _get_item_end(item):
    """Determine the end time of a Smartschool item in both old and new API structures."""
    period = _get_item_value(item, "period", "period_obj")
    if period is not None:
        end = _get_item_value(period, "date_time_to", "dateTimeTo")
        if end is not None:
            return end

    value = _get_item_value(item, "end", "dateTimeTo", "date_time_to")
    if value is not None:
        return value

    for candidate in _iter_nested_values(item):
        if "to" in str(candidate).lower() or "end" in str(candidate).lower():
            if isinstance(candidate, (datetime, str)):
                return candidate
    return None


def _iter_nested_values(value):
    """Recursively collect all values from objects and dicts to find dates."""
    if isinstance(value, dict):
        for v in value.values():
            yield v
            yield from _iter_nested_values(v)
    elif hasattr(value, "__dict__"):
        for v in vars(value).values():
            yield v
            yield from _iter_nested_values(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield v
            yield from _iter_nested_values(v)


def _detect_item_type(item):
    """Classify a planner item based on Smartschool's actual planner metadata.

    NOTE: the keyword lists below match against Smartschool's own (Dutch) labels and
    generic-type names, since that's the language the API returns them in — they are
    not user-facing strings and must not be translated.
    """
    if _is_lesson_item(item):
        return "lesson", "🏫"

    planned_type = _get_item_value(item, "plannedElementType", "planned_element_type", "type")
    generic_type = _get_item_value(item, "genericType", "generic_type")
    generic_name = _get_item_value(generic_type, "name") if isinstance(generic_type, dict) else getattr(generic_type, "name", None)
    generic_name = generic_name or _get_item_value(item, "genericTypeName")
    item_name = _get_item_value(item, "name", "title")
    text = " ".join(filter(None, [str(planned_type), str(generic_name), str(item_name)])).lower()

    if planned_type == "planned-to-dos":
        return "task", "✅"
    if planned_type == "planned-school-activities":
        return "school_activity", "🏫"
    if planned_type == "planned-generics":
        if generic_name and "studeer" in generic_name.lower():
            return "study_time", "📚"
        if generic_name and "vrije tijd" in generic_name.lower():
            return "free_time", "⏳"
        return "generic", "🗓️"
    if generic_name and "studeer" in generic_name.lower():
        return "study_time", "📚"
    if generic_name and "vrije tijd" in generic_name.lower():
        return "free_time", "⏳"

    if any(token in text for token in ["toets", "test", "examen", "tentamen", "proef"]):
        return "test", "📝"
    if any(token in text for token in ["taak", "todo", "task", "opdracht", "huiswerk", "assignment", "workshop", "to-do"]):
        return "task", "✅"
    if any(token in text for token in ["les", "lesson", "agenda", "moment", "uurrooster", "cursus"]):
        return "lesson", "🏫"
    return "other", "📌"


def _parse_date(date_value):
    """Helper to convert a date string or datetime into a timezone-aware datetime."""
    if isinstance(date_value, datetime):
        if date_value.tzinfo is None:
            return date_value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return date_value.astimezone(dt_util.DEFAULT_TIME_ZONE)

    if isinstance(date_value, str):
        cleaned = date_value.strip()
        try:
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return parsed.astimezone(dt_util.DEFAULT_TIME_ZONE)
        except ValueError:
            pass

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(cleaned, fmt)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                return parsed.astimezone(dt_util.DEFAULT_TIME_ZONE)
            except ValueError:
                continue

    _LOGGER.warning("Unknown date format: %s", date_value)
    return datetime.min.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)


def _week_start(dt_value=None):
    """Return Monday 00:00 of the current week."""
    if dt_value is None:
        dt_value = dt_util.now()
    dt_value = _parse_date(dt_value)
    start = dt_value - timedelta(days=dt_value.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def _fetch_window(dt_value=None, days=30):
    """Return a window from the Monday of the week to a number of days ahead."""
    start = _week_start(dt_value)
    end = start + timedelta(days=max(days, 30))
    return start, end


def _lesson_icon_for_name(title):
    """Give all timetable items the same clear school icon."""
    return "📖"


def _flatten_description_text(value, seen=None):
    """Extract textual descriptions from nested dicts/lists/objects."""
    if value is None:
        return ""
    if seen is None:
        seen = set()

    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else ""

    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            text = _flatten_description_text(item, seen)
            if text:
                parts.append(text)
        return "\n".join(parts)

    if isinstance(value, dict):
        id_key = id(value)
        if id_key in seen:
            return ""
        seen.add(id_key)
        for key in [
            "description",
            "descriptionText",
            "text",
            "content",
            "body",
            "bodyText",
            "details",
            "summary",
            "longDescription",
            "long_description",
            "message",
            "notes",
            "html",
            "htmlDescription",
            "eventDescription",
        ]:
            if key in value:
                text = _flatten_description_text(value[key], seen)
                if text:
                    return text
        for v in value.values():
            text = _flatten_description_text(v, seen)
            if text:
                return text
        return ""

    if hasattr(value, "__dict__"):
        obj_id = id(value)
        if obj_id in seen:
            return ""
        seen.add(obj_id)
        for key in [
            "description",
            "descriptionText",
            "text",
            "content",
            "body",
            "bodyText",
            "details",
            "summary",
            "longDescription",
            "long_description",
            "message",
            "notes",
            "html",
            "htmlDescription",
            "eventDescription",
        ]:
            if hasattr(value, key):
                text = _flatten_description_text(getattr(value, key), seen)
                if text:
                    return text
        for v in vars(value).values():
            text = _flatten_description_text(v, seen)
            if text:
                return text
        return ""

    return _stringify(value).strip()


def _strip_name_suffix(value):
    """Remove Smartschool code suffixes such as (VBEL) from the display name."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return ""
    if "(" in text and text.rfind("(") > 0:
        text = text[: text.rfind("(")].rstrip()
    return text


def _get_lesson_teacher(item):
    """Find the teacher from organisers.users[].name.startingWithFirstName."""
    organisers = _get_item_value(item, "organisers")
    if not organisers:
        return None

    candidate_items = []
    if isinstance(organisers, list):
        candidate_items.extend(organisers)
    elif isinstance(organisers, dict):
        for key in ("users", "groups", "organisers"):
            value = organisers.get(key)
            if isinstance(value, list):
                candidate_items.extend(value)
        if not candidate_items and organisers:
            candidate_items.append(organisers)

    for organiser in candidate_items:
        if organiser is None:
            continue

        name_obj = _get_item_value(organiser, "name")
        if isinstance(name_obj, dict):
            first = _get_item_value(name_obj, "startingWithFirstName")
            if first:
                return _strip_name_suffix(first)

        if isinstance(organiser, dict):
            first = organiser.get("firstName") or organiser.get("firstname")
            last = organiser.get("lastName") or organiser.get("lastname")
            if first or last:
                full_name = " ".join(part for part in [first, last] if part).strip()
                return _strip_name_suffix(full_name)

        first = _get_item_value(organiser, "firstName", "firstname")
        last = _get_item_value(organiser, "lastName", "lastname")
        if first or last:
            full_name = " ".join(part for part in [first, last] if part).strip()
            return _strip_name_suffix(full_name)

    return None


def _item_to_event(item):
    """Convert a Smartschool planner item into an HA CalendarEvent."""
    start_value = _get_item_start(item)
    end_value = _get_item_end(item)
    if start_value is None:
        return None

    start_dt = _parse_date(start_value)
    end_dt = _parse_date(end_value) if end_value is not None else start_dt + timedelta(minutes=60)

    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(minutes=60)

    title = _get_item_title(item)
    planned_type = _get_planned_element_type(item)

    if _is_lesson_item(item):
        teacher = _get_lesson_teacher(item)
        summary = title
        description = ""
        location = teacher if teacher else ""

        if planned_type == "planned-lessons":
            name = _get_item_value(item, "name", "title")
            if name:
                description = str(name)
    else:
        summary = title
        type_label = _get_assignment_type_label(item)
        if type_label:
            summary = f"{type_label}: {title}"
        description = _get_assignment_description(item)
        location = ""

    return CalendarEvent(
        start=start_dt,
        end=end_dt,
        summary=summary,
        description=description,
        location=location,
    )


_CALENDAR_CACHE_TTL = timedelta(minutes=10)


def _fetch_raw_elements_for_session(session, days=120):
    """Fetch raw planner items for the whole week plus a fixed look-ahead period.

    Cached per (session, days): the planner and timetable calendar entities each poll
    independently, so without a cache every poll cycle would trigger two full API fetches
    per child.
    """
    now = dt_util.utcnow()
    cache = getattr(session, "_smartschool_calendar_cache", None)
    if cache is None:
        cache = {}
        session._smartschool_calendar_cache = cache
    cached = cache.get(days)
    if cached and now - cached[0] < _CALENDAR_CACHE_TTL:
        return cached[1]

    try:
        user_id = session.authenticated_user["id"]
        from_dt, to_dt = _fetch_window(dt_value=dt_util.now(), days=max(days, 30))
        raw = session.json(
            f"/planner/api/v1/planned-elements/user/{user_id}",
            data={
                "from": from_dt.isoformat(),
                "to": to_dt.isoformat(),
            },
        )
        if not isinstance(raw, list):
            _LOGGER.warning("Calendar planner raw response was not a list: %s", type(raw))
            raw = []
        else:
            _LOGGER.info("Calendar raw planner payload returned %s items from %s to %s", len(raw), from_dt, to_dt)
        cache[days] = (now, raw)
        return raw
    except Exception as err:
        _LOGGER.error("Calendar raw planner fetch failed: %s", err, exc_info=True)
        return []


def _preferred_entity_id(domain, entry_title, suffix):
    """Build a child-specific entity id for the calendar."""
    clean = slugify(entry_title or "smartschool")
    return f"{domain}.{clean}_{suffix}"


def _entity_suffix_from_unique_id(entry_id, unique_id):
    """Extract the fixed entity suffix from the unique id, not from a legacy entity id."""
    prefix = f"{entry_id}_smartschool_"
    if unique_id.startswith(prefix):
        return unique_id[len(prefix):]
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Set up the Smartschool calendar entities."""
    session = hass.data[DOMAIN][entry.entry_id]
    child_name = entry.title or "Smartschool"

    planner_entity = SmartschoolCalendarEntity(hass, session, entry.entry_id, child_name)
    lessons_entity = SmartschoolLessonsCalendarEntity(hass, session, entry.entry_id, child_name)
    async_add_entities([planner_entity, lessons_entity], True)

    entity_registry = er.async_get(hass)
    for entity in (planner_entity, lessons_entity):
        unique_id = getattr(entity, "unique_id", None)
        if not unique_id:
            continue
        old_entity_id = entity_registry.async_get_entity_id("calendar", DOMAIN, unique_id)
        if old_entity_id:
            suffix = _entity_suffix_from_unique_id(entry.entry_id, unique_id)
            if not suffix:
                continue
            desired_id = _preferred_entity_id("calendar", child_name, suffix)
            if old_entity_id != desired_id:
                try:
                    entity_registry.async_update_entity(old_entity_id, new_entity_id=desired_id)
                except Exception:
                    _LOGGER.debug("Could not change calendar entity id for %s to %s", old_entity_id, desired_id)


class SmartschoolCalendarEntity(CalendarEntity):
    """Home Assistant calendar entity for Smartschool planner items."""

    _attr_icon = "mdi:calendar"
    _attr_should_poll = True

    def __init__(self, hass: HomeAssistant, session, entry_id, child_name):
        self.hass = hass
        self._session = session
        self._entry_id = entry_id
        self._attr_name = f"{child_name} Planner"
        self._attr_unique_id = f"{entry_id}_smartschool_planner_calendar"
        self._events = []
        self.entity_id = _preferred_entity_id("calendar", child_name, "planner")
        _LOGGER.info("SmartschoolCalendarEntity initialized with session: %s", session)

    def _fetch_raw_elements(self):
        """Fetch the raw planner items for the planner calendar."""
        return _fetch_raw_elements_for_session(self._session, days=120)

    def _filter_events(self, elements):
        """Filter out actual lesson items from the regular planner."""
        return [item for item in elements if not _is_lesson_item(item)]

    async def async_update(self):
        """Load planner events for the entire current week and the upcoming period."""
        _LOGGER.info("SmartschoolCalendarEntity.async_update() called")
        try:
            now = dt_util.utcnow()
            window_start = _week_start(now)
            future_limit = window_start + timedelta(weeks=12)
            _LOGGER.info("Fetching PlannedElements from SmartSchool API")
            elements = await self.hass.async_add_executor_job(self._fetch_raw_elements)
            elements = self._filter_events(elements)
            _log_planner_items(self.entity_id, elements)
            _LOGGER.info("SmartSchool API returned %s planner elements after filtering", len(elements))

            events = []
            for idx, item in enumerate(elements):
                _LOGGER.info("Processing calendar item[%s]: %s", idx, item)
                event = _item_to_event(item)
                if event is None:
                    _LOGGER.info("  -> Skipped (invalid event)")
                    continue
                event_start = event.start
                event_end = event.end
                _LOGGER.info("  -> Event: %s to %s (window_start=%s, future=%s)", event_start, event_end, window_start, future_limit)
                if event_start <= future_limit and event_end >= window_start:
                    events.append(event)
                    _LOGGER.info("  -> Added to calendar")
                else:
                    _LOGGER.info("  -> Skipped (out of range)")

            self._events = sorted(events, key=lambda e: e.start)
            _LOGGER.info("Smartschool planner calendar update: %s events loaded", len(self._events))

        except Exception as e:
            _LOGGER.error("Error fetching Smartschool planner data: %s", e, exc_info=True)
            self._events = []

    @property
    def event(self):
        """Return the next upcoming event."""
        if not self._events:
            return None
        now = dt_util.utcnow()
        for event in self._events:
            if event.end >= now:
                return event
        return self._events[-1]

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime):
        """Return all planner events within the requested window."""
        return [
            event for event in self._events
            if event.end > start_date and event.start < end_date
        ]


class SmartschoolLessonsCalendarEntity(CalendarEntity):
    """Home Assistant calendar entity for the Smartschool timetable."""

    _attr_icon = "mdi:calendar-clock"
    _attr_should_poll = True

    def __init__(self, hass: HomeAssistant, session, entry_id, child_name):
        self.hass = hass
        self._session = session
        self._entry_id = entry_id
        self._attr_name = f"{child_name} Timetable"
        self._attr_unique_id = f"{entry_id}_smartschool_lessons_calendar"
        self._events = []
        self.entity_id = _preferred_entity_id("calendar", child_name, "timetable")

    async def async_update(self):
        """Load only timetable events for the entire current week and the upcoming period."""
        try:
            now = dt_util.utcnow()
            window_start = _week_start(now)
            future_limit = window_start + timedelta(weeks=16)
            elements = await self.hass.async_add_executor_job(self._fetch_raw_elements)
            items = [
                item for item in elements
                if _get_planned_element_type(item) in _LESSON_TYPES
            ]
            _log_planner_items(self.entity_id, items)
            events = []
            for item in items:
                event = _item_to_event(item)
                if event is None:
                    continue
                if event.start <= future_limit and event.end >= window_start:
                    events.append(event)
            self._events = sorted(events, key=lambda e: e.start)
        except Exception as e:
            _LOGGER.error("Error fetching Smartschool timetable data: %s", e, exc_info=True)
            self._events = []

    def _fetch_raw_elements(self):
        """Fetch raw planner items for the timetable."""
        return _fetch_raw_elements_for_session(self._session, days=180)

    @property
    def event(self):
        """Return the next upcoming event."""
        if not self._events:
            _LOGGER.debug("event property: no events available")
            return None
        now = dt_util.utcnow()
        for event in self._events:
            if event.end >= now:
                _LOGGER.debug("event property: returning event %s", event.summary)
                return event
        _LOGGER.debug("event property: returning last event %s", self._events[-1].summary)
        return self._events[-1]

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime):
        """Return all events within the requested window."""
        _LOGGER.debug("async_get_events called: start=%s, end=%s", start_date, end_date)
        result = [
            event for event in self._events
            if event.end > start_date and event.start < end_date
        ]
        _LOGGER.debug("async_get_events returning %s events", len(result))
        return result
