
import csv
import logging
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util, slugify
from smartschool import Attachments, BoxType, MarkMessageUnread, Message, MessageHeaders
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_RESULT_CACHE_TTL = timedelta(minutes=10)
_RESULT_LOG_DIR = "/config/custom_components/smartschool/logging"
_MESSAGE_DOWNLOAD_DIR = "/config/www/smartschool_messages"
_MESSAGE_CACHE_TTL = timedelta(minutes=10)


def _fetch_planned_elements(session):
    """Fetch all planner items via unfiltered raw JSON; the library filters too strictly by default."""
    try:
        user_id = session.authenticated_user["id"]
        from_dt = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        to_dt = from_dt + timedelta(days=45)
        raw = session.json(
            f"/planner/api/v1/planned-elements/user/{user_id}",
            data={
                "from": from_dt.isoformat(),
                "to": to_dt.isoformat(),
            },
        )
        if not isinstance(raw, list):
            _LOGGER.warning("Planner raw JSON response was not a list: %s", type(raw))
            return []
        _LOGGER.info("Raw planner payload returned %s items", len(raw))
        return raw
    except Exception as err:
        _LOGGER.error("Raw planner fetch failed: %s", err, exc_info=True)
        return []


def _message_value(message, *keys):
    """Read a field from a Smartschool message object or dictionary."""
    return _get_item_value(message, *keys)


_RELATIVE_IMG_SRC_RE = re.compile(r'src=(["\'])(?!https?://|data:)([^"\']*)\1', re.IGNORECASE)


def _fix_relative_image_urls(body, session):
    """Rewrite relative <img src="..."> paths to absolute Smartschool URLs.

    Message content sometimes contains img tags with a relative path (e.g. src="/foo.jpg").
    If that HTML is shown outside of Smartschool (e.g. in a Lovelace card), the browser
    resolves that path against its own host instead of against the Smartschool platform.
    """
    if not body:
        return body
    main_url = getattr(getattr(session, "creds", None), "main_url", None)
    if not main_url:
        return body
    base = f"https://{main_url}"

    def _replace(match):
        quote, path = match.group(1), match.group(2)
        if not path:
            return match.group(0)
        absolute = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
        return f"src={quote}{absolute}{quote}"

    return _RELATIVE_IMG_SRC_RE.sub(_replace, body)


def _message_date(value):
    """Normalize a message date to a timezone-aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=dt_util.DEFAULT_TIME_ZONE)
    if isinstance(value, str):
        return _parse_date(value)
    return datetime.min.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)


def _message_recipients(message):
    """Make recipients suitable for HA attributes."""
    recipients = _message_value(message, "receivers", "to") or []
    return _to_plain_value(recipients if isinstance(recipients, (list, tuple)) else [recipients])


def _message_is_unread(message):
    """Read an unread flag correctly, even when the API returns a text value.

    The field the smartschool library calls "unread"/"isUnread" behaves in practice as
    "has been opened/read" (False = never opened = truly unread, True = already opened =
    read) rather than what the name suggests. Hence the inversion.
    """
    value = _message_value(message, "unread", "isUnread")
    if value is None:
        read_value = _message_value(message, "read", "isRead")
        if read_value is not None:
            if isinstance(read_value, str):
                return read_value.strip().lower() not in {"1", "true", "yes", "on"}
            return not bool(read_value)
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"1", "true", "yes", "on"}
    return not bool(value)


def _write_messages_csv(child_name, records):
    """Write the selected Smartschool messages per child to CSV."""
    try:
        os.makedirs(_RESULT_LOG_DIR, exist_ok=True)
        path = os.path.join(_RESULT_LOG_DIR, f"{slugify(child_name)}_messages.csv")
        fieldnames = [
            "logged_at",
            "message_id",
            "from",
            "subject",
            "body",
            "receivers",
            "cc_receivers",
            "bcc_receivers",
            "date",
            "send_date",
            "unread",
            "attachments",
        ]
        with open(path, "w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                message = record["message"]
                header = record["header"]
                writer.writerow({
                    "logged_at": dt_util.utcnow().isoformat(),
                    "message_id": _message_value(message, "id"),
                    "from": _to_plain_value(_message_value(message, "from_", "from")),
                    "subject": _message_value(message, "subject"),
                    "body": _message_value(message, "body") or "",
                    "receivers": _message_recipients(message),
                    "cc_receivers": _to_plain_value(_message_value(message, "ccreceivers") or []),
                    "bcc_receivers": _to_plain_value(_message_value(message, "bccreceivers") or []),
                    "date": _to_plain_value(_message_value(message, "date")),
                    "send_date": _to_plain_value(_message_value(message, "send_date", "sendDate")),
                    "unread": _message_is_unread(header),
                    "attachments": record["attachments"],
                })
    except OSError as err:
        _LOGGER.warning("Could not write Smartschool messages CSV: %s", err)


def _unread_debug_log_path(child_name):
    """Determine the path of the per-instance debug log file for unread status."""
    return os.path.join(_RESULT_LOG_DIR, f"{slugify(child_name)}_unread_debug.log")


def _log_unread_debug(child_name, message):
    """Write a debug line to the per-instance unread log file."""
    try:
        os.makedirs(_RESULT_LOG_DIR, exist_ok=True)
        with open(_unread_debug_log_path(child_name), "a", encoding="utf-8") as log_file:
            log_file.write(f"{dt_util.utcnow().isoformat()} {message}\n")
    except OSError as err:
        _LOGGER.warning("Could not write Smartschool unread debug log: %s", err)


def _dump_header_fields(header):
    """Show all relevant header fields for debugging the unread status."""
    raw = _to_plain_value(header)
    keys = ("id", "subject", "unread", "isUnread", "read", "isRead", "status", "date", "send_date", "sendDate")
    if isinstance(raw, dict):
        return {key: raw.get(key) for key in keys if key in raw}
    return {key: getattr(header, key, "<missing>") for key in keys}


def _fetch_message_records(session, child_name):
    """Fetch unread messages and messages read within the last two weeks."""
    now = dt_util.utcnow()
    cached_at = getattr(session, "_smartschool_messages_cache_at", None)
    if cached_at and now - cached_at < _MESSAGE_CACHE_TTL:
        return getattr(session, "_smartschool_messages_cache", [])

    cutoff = dt_util.now() - timedelta(days=14)
    session.ensure_authenticated()
    headers = list(MessageHeaders(session, box_type=BoxType.INBOX))
    _log_unread_debug(child_name, f"--- fetch cycle: {len(headers)} headers received ---")
    selected = []
    for header in headers:
        message_date = _message_date(_message_value(header, "date", "send_date", "sendDate"))
        is_unread = _message_is_unread(header)
        _log_unread_debug(
            child_name,
            f"header id={_message_value(header, 'id')} is_unread={is_unread} fields={_dump_header_fields(header)}",
        )
        if is_unread or cutoff <= message_date <= dt_util.now():
            message_id = _message_value(header, "id")
            if message_id is not None:
                selected.append((int(message_id), header))

    content_cache = getattr(session, "_smartschool_message_content_cache", None)
    if content_cache is None:
        content_cache = {}
        session._smartschool_message_content_cache = content_cache

    records = []
    for message_id, header in selected:
        try:
            was_unread = _message_is_unread(header)

            if message_id in content_cache:
                _log_unread_debug(child_name, f"id={message_id}: using cached content")
                full_message, attachment_rows = content_cache[message_id]
            else:
                _log_unread_debug(child_name, f"id={message_id}: fetching Message() now (was_unread={was_unread})")
                full_message = next(iter(Message(session, message_id, box_type=BoxType.INBOX)))
                try:
                    full_message.body = _fix_relative_image_urls(_message_value(full_message, "body"), session)
                except Exception as err:
                    _LOGGER.warning("Could not rewrite relative image URLs for message %s: %s", message_id, err)
                attachment_rows = []
                if _message_value(full_message, "attachment"):
                    for attachment in Attachments(session, message_id, box_type=BoxType.INBOX):
                        attachment_name = str(_message_value(attachment, "name") or "attachment")
                        attachment_path = os.path.join(
                            _MESSAGE_DOWNLOAD_DIR,
                            slugify(child_name),
                            str(message_id),
                            slugify(attachment_name),
                        )
                        downloaded = False
                        try:
                            os.makedirs(os.path.dirname(attachment_path), exist_ok=True)
                            with open(attachment_path, "wb") as attachment_file:
                                attachment_file.write(attachment.download())
                            downloaded = True
                        except Exception as err:
                            _LOGGER.warning("Could not save attachment for message %s: %s", message_id, err)
                        attachment_rows.append({
                            "file_id": _message_value(attachment, "file_id", "fileID"),
                            "name": attachment_name,
                            "mime": _message_value(attachment, "mime"),
                            "size": _message_value(attachment, "size"),
                            "downloaded": downloaded,
                            "download_url": f"/local/smartschool_messages/{slugify(child_name)}/{message_id}/{slugify(attachment_name)}",
                        })
                content_cache[message_id] = (full_message, attachment_rows)

                if was_unread:
                    # We had to open the message to read its content, which Smartschool
                    # registers as "read". Immediately restore the status to unread: only
                    # the user themselves (in the app) or the "mark_message_read" service
                    # is allowed to change this.
                    try:
                        list(MarkMessageUnread(session, message_id, box_type=BoxType.INBOX))
                        _log_unread_debug(child_name, f"id={message_id}: read status restored to unread")
                    except Exception as err:
                        _LOGGER.warning("Could not restore unread status for message %s: %s", message_id, err)

            records.append({"header": header, "message": full_message, "attachments": attachment_rows})
        except Exception as err:
            _LOGGER.warning("Could not read Smartschool message %s: %s", message_id, err, exc_info=True)

    _write_messages_csv(child_name, records)
    session._smartschool_messages_cache = records
    session._smartschool_messages_cache_at = now
    _LOGGER.info("Smartschool selected %s messages for %s", len(records), child_name)
    return records


def _add_new_message_entities(hass, session, entry_id, child_name, records):
    """Register messages that have appeared since the last platform setup."""
    async_add_entities = getattr(session, "_smartschool_add_entities", None)
    known_ids = getattr(session, "_smartschool_message_ids", set())
    new_sensors = []
    for record in records:
        message_id = _message_value(record["message"], "id")
        if message_id is None:
            continue
        message_id = int(message_id)
        if message_id in known_ids:
            continue
        known_ids.add(message_id)
        new_sensors.append(
            SmartschoolMessageSensor(hass, session, entry_id, child_name, record)
        )

    if not new_sensors or async_add_entities is None:
        return

    async_add_entities(new_sensors, True)
    message_entities = hass.data[DOMAIN].setdefault("message_entities", {})
    for sensor in new_sensors:
        message_entities[sensor.entity_id] = {
            "entry_id": entry_id,
            "session": session,
            "message_id": sensor._message_id,
        }


class SmartschoolMessageSensor(SensorEntity):
    """Sensor for a Smartschool message."""

    _attr_icon = "mdi:email-outline"

    def __init__(self, hass, session, entry_id, child_name, record):
        self.hass = hass
        self._session = session
        self._entry_id = entry_id
        self._child_name = child_name
        self._record = record
        message = record["message"]
        self._message_id = int(_message_value(message, "id"))
        self.entity_id = _preferred_entity_id("sensor", child_name, f"message_{self._message_id}")
        self._attr_name = f"{child_name} Message {self._message_id}"
        self._attr_unique_id = f"{entry_id}_smartschool_message_{self._message_id}"
        self._state = str(_message_value(message, "subject") or "(No subject)")
        self._attributes = self._build_attributes(
            message, record["attachments"], _message_is_unread(record["header"])
        )

    def _build_attributes(self, message, attachments, unread):
        return {
            "message_id": self._message_id,
            "from": _to_plain_value(_message_value(message, "from_", "from")),
            "body": str(_message_value(message, "body") or ""),
            "receivers": _message_recipients(message),
            "cc_receivers": _to_plain_value(_message_value(message, "ccreceivers") or []),
            "bcc_receivers": _to_plain_value(_message_value(message, "bccreceivers") or []),
            "date": _to_plain_value(_message_value(message, "date")),
            "send_date": _to_plain_value(_message_value(message, "send_date", "sendDate")),
            "unread": unread,
            "attachments": attachments,
        }

    async def async_update(self):
        records = await self.hass.async_add_executor_job(
            _fetch_message_records, self._session, self._child_name
        )
        _add_new_message_entities(
            self.hass, self._session, self._entry_id, self._child_name, records
        )
        for record in records:
            message = record["message"]
            if int(_message_value(message, "id")) == self._message_id:
                self._record = record
                self._state = str(_message_value(message, "subject") or "(No subject)")
                self._attributes = self._build_attributes(
                    message, record["attachments"], _message_is_unread(record["header"])
                )
                return

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes


def _result_value(result, *keys):
    """Read a field from a Smartschool result object or dictionary."""
    return _get_item_value(result, *keys)


def _result_courses(result):
    """Return the courses a result is linked to."""
    courses = _result_value(result, "courses") or []
    if isinstance(courses, (list, tuple, set)):
        return list(courses)
    return [courses] if courses else []


def _result_graphic(result):
    """Extract the graphic type and readable score from a result."""
    graphic = _result_value(result, "graphic")
    graphic_type = _result_value(graphic, "type") or "unknown"
    description = _result_value(graphic, "description")
    value = _result_value(graphic, "value")
    achieved = _result_value(graphic, "achieved_points")
    total = _result_value(graphic, "total_points")
    percentage = _result_value(graphic, "percentage")
    if description is None:
        description = value
    if description and (achieved is None or total is None):
        try:
            achieved_text, total_text = str(description).split("/", 1)
            achieved = achieved if achieved is not None else float(achieved_text.strip())
            total = total if total is not None else float(total_text.strip())
        except (ValueError, TypeError):
            pass
    if percentage is None and achieved is not None and total:
        percentage = round(float(achieved) / float(total) * 100, 2)
    return {
        "type": str(graphic_type),
        "color": _result_value(graphic, "color"),
        "value": value,
        "description": description,
        "achieved_points": achieved,
        "total_points": total,
        "percentage": percentage,
    }


def _result_feedback(result):
    """Extract feedback text and the name of the feedback giver from a result."""
    feedback = _result_value(result, "feedback", "feedbacks") or []
    if not isinstance(feedback, (list, tuple, set)):
        feedback = [feedback]

    texts = []
    teachers = []
    for item in feedback:
        text = _result_value(item, "text")
        if text:
            texts.append(str(text))
        user = _result_value(item, "user")
        name = _result_value(user, "name")
        teacher = _result_value(name, "startingWithFirstName")
        if teacher:
            teachers.append(str(teacher))

    return "\n\n".join(texts), (teachers[0] if teachers else None)


def _result_to_row(result, course):
    """Build a CSV- and attribute-friendly representation of a result."""
    graphic = _result_graphic(result)
    period = _result_value(result, "period")
    component = _result_value(result, "component")
    feedback, teacher = _result_feedback(result)
    return {
        "logged_at": dt_util.utcnow().isoformat(),
        "result_id": _result_value(result, "identifier", "id"),
        "result_name": _result_value(result, "name"),
        "result_date": _result_value(result, "date"),
        "availability_date": _result_value(result, "availability_date", "availabilityDate"),
        "course_id": _result_value(course, "id", "identifier"),
        "course_name": _result_value(course, "name"),
        "graphic_type": graphic["type"],
        "graphic_color": graphic["color"],
        "graphic_value": graphic["value"],
        "graphic_description": graphic["description"],
        "achieved_points": graphic["achieved_points"],
        "total_points": graphic["total_points"],
        "percentage": graphic["percentage"],
        "period": period,
        "component": component,
        "feedback": feedback,
        "teacher": teacher,
        "is_published": _result_value(result, "is_published", "isPublished"),
        "does_count": _result_value(result, "does_count", "doesCount"),
        "deleted": _result_value(result, "deleted"),
    }


def _write_results_csv(child_name, rows):
    """Write the current results per child to a CSV snapshot."""
    try:
        os.makedirs(_RESULT_LOG_DIR, exist_ok=True)
        path = os.path.join(_RESULT_LOG_DIR, f"{slugify(child_name)}_results.csv")
        fieldnames = list(rows[0]) if rows else ["logged_at", "result_id", "result_name", "course_name"]
        with open(path, "w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows({key: _to_plain_value(value) for key, value in row.items()} for row in rows)
    except OSError as err:
        _LOGGER.warning("Could not write Smartschool results CSV: %s", err)


def _fetch_results(session, child_name):
    """Fetch results and cache the source data for the result sensors."""
    now = dt_util.utcnow()
    cached_at = getattr(session, "_smartschool_results_cache_at", None)
    if cached_at and now - cached_at < _RESULT_CACHE_TTL:
        return getattr(session, "_smartschool_results_cache", [])

    try:
        results = []
        page_number = 1
        while True:
            response = session.json(
                "/results/api/v1/evaluations/",
                data={"pageNumber": page_number, "itemsOnPage": 50},
            )
            if isinstance(response, list):
                page = response
            elif isinstance(response, dict):
                page = response.get(
                    "evaluations",
                    response.get("items", response.get("results", response.get("data", []))),
                )
            else:
                page = []
            if not isinstance(page, list):
                page = []
            results.extend(page)
            if len(page) < 50:
                break
            page_number += 1
        rows = []
        for result in results:
            for course in _result_courses(result):
                rows.append(_result_to_row(result, course))
        _write_results_csv(child_name, rows)
        session._smartschool_results_cache = results
        session._smartschool_results_cache_at = now
        _LOGGER.info("Smartschool returned %s results (%s course rows)", len(results), len(rows))
        return results
    except Exception as err:
        _write_results_csv(child_name, [])
        _LOGGER.error("Could not fetch Smartschool results: %s", err, exc_info=True)
        return []


def _result_sensor_specs(results):
    """Build unique sensor specs per result and per course."""
    specs = []
    seen = set()
    for result in results:
        result_id = str(_result_value(result, "identifier", "id") or "")
        if not result_id:
            continue
        for course in _result_courses(result):
            course_id = str(_result_value(course, "id", "identifier") or _result_value(course, "name") or "")
            key = (result_id, course_id)
            if key in seen:
                continue
            seen.add(key)
            specs.append((result, course))
    return specs


def _add_new_result_entities(hass, session, entry_id, child_name, results):
    """Register results that have appeared since the last platform setup."""
    async_add_entities = getattr(session, "_smartschool_add_result_entities", None)
    known_keys = getattr(session, "_smartschool_result_keys", set())
    new_sensors = []
    for result, course in _result_sensor_specs(results):
        result_id = str(_result_value(result, "identifier", "id") or "")
        course_id = str(_result_value(course, "id", "identifier") or _result_value(course, "name") or "")
        key = (result_id, course_id)
        if key in known_keys:
            continue
        known_keys.add(key)
        new_sensor = SmartschoolResultSensor(hass, session, entry_id, child_name, result, course)
        new_sensor._apply_result(result)
        new_sensors.append(new_sensor)

    session._smartschool_result_keys = known_keys

    if not new_sensors or async_add_entities is None:
        return

    async_add_entities(new_sensors, True)


class SmartschoolResultSensor(SensorEntity):
    """Sensor for a single Smartschool result within a course."""

    _attr_icon = "mdi:school-outline"

    def __init__(self, hass, session, entry_id, child_name, result, course):
        self.hass = hass
        self._session = session
        self._entry_id = entry_id
        self._child_name = child_name
        self._result_id = str(_result_value(result, "identifier", "id"))
        self._course_id = str(_result_value(course, "id", "identifier") or _result_value(course, "name"))
        self._course_name = str(_result_value(course, "name") or "Unknown")
        self._result_name = str(_result_value(result, "name") or "Result")
        self._result = result
        self._course = course
        self._state = None
        self._attributes = {}
        self._attr_name = f"{child_name} Results {self._course_name} {self._result_name}"
        self._attr_unique_id = f"{entry_id}_smartschool_result_{self._result_id}_{self._course_id}"

    def _apply_result(self, result):
        self._result = result
        graphic = _result_graphic(result)
        display_value = graphic["description"] or graphic["value"] or "Unknown"
        self._state = str(display_value)
        row = _result_to_row(result, self._course)
        self._attributes = {
            "result_id": row["result_id"],
            "result_name": row["result_name"],
            "result_date": row["result_date"],
            "availability_date": row["availability_date"],
            "course_id": row["course_id"],
            "course_name": row["course_name"],
            "graphic_type": row["graphic_type"],
            "graphic_color": row["graphic_color"],
            "graphic_value": row["graphic_value"],
            "graphic_description": row["graphic_description"],
            "achieved_points": row["achieved_points"],
            "total_points": row["total_points"],
            "percentage": row["percentage"],
            "period": _to_plain_value(row["period"]),
            "component": _to_plain_value(row["component"]),
            "feedback": _to_plain_value(row["feedback"]),
            "Teacher": _to_plain_value(row["teacher"]),
            "is_published": row["is_published"],
            "does_count": row["does_count"],
            "deleted": row["deleted"],
        }

    async def async_update(self):
        results = await self.hass.async_add_executor_job(_fetch_results, self._session, self._child_name)
        _add_new_result_entities(
            self.hass, self._session, self._entry_id, self._child_name, results
        )
        for result in results:
            if str(_result_value(result, "identifier", "id")) != self._result_id:
                continue
            for course in _result_courses(result):
                course_id = str(_result_value(course, "id", "identifier") or _result_value(course, "name"))
                if course_id == self._course_id:
                    self._course = course
                    self._apply_result(result)
                    return

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes


def _to_plain_value(value):
    """Convert dataclass/object data to JSON-compatible dicts/lists."""
    if is_dataclass(value):
        return {k: _to_plain_value(v) for k, v in asdict(value).items()}

    if isinstance(value, dict):
        return {str(k): _to_plain_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_to_plain_value(v) for v in value]

    if hasattr(value, "__dict__") and not isinstance(value, (str, int, float, bool, type(None))):
        fields = {}
        for key, item in vars(value).items():
            if key.startswith("_"):
                continue
            fields[key] = _to_plain_value(item)
        return fields

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return value


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


def _get_item_start(item):
    """Determine the start time of a Smartschool item in both old and new API structures."""
    period = _get_item_value(item, "period", "period_obj")
    if period is not None:
        start = _get_item_value(period, "date_time_from", "dateTimeFrom")
        if start is not None:
            return start

    value = _get_item_value(item, "start", "dateTimeFrom", "date_time_from")
    return value


def _get_item_title(item):
    """Determine the title of an item in both old and new API structures."""
    value = _get_item_value(item, "title", "name")
    if value is not None:
        return value
    return "Unknown"


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


def _detect_item_type(item):
    """Classify a planner item based on Smartschool's actual planner metadata.

    NOTE: the keyword lists below match against Smartschool's own (Dutch) labels and
    generic-type names, since that's the language the API returns them in — they are
    not user-facing strings and must not be translated.
    """
    planned_type = _get_item_value(item, "plannedElementType", "planned_element_type", "type")
    generic_type = _get_item_value(item, "genericType", "generic_type")
    generic_name = _get_item_value(generic_type, "name") if isinstance(generic_type, dict) else getattr(generic_type, "name", None)
    generic_name = generic_name or _get_item_value(item, "genericTypeName")
    item_name = _get_item_value(item, "name", "title")
    raw_text = " ".join(filter(None, [str(planned_type), str(generic_name), str(item_name)]))
    text = raw_text.lower()

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

    for token in ["toets", "test", "examen", "tentamen", "proef"]:
        if token in text:
            return "test", "📝"
    for token in ["taak", "todo", "task", "opdracht", "huiswerk", "assignment", "workshop", "to-do"]:
        if token in text:
            return "task", "✅"
    for token in ["les", "lesson", "agenda", "moment", "uurrooster", "cursus"]:
        if token in text:
            return "lesson", "🏫"
    return "other", "📌"


def _preferred_entity_id(domain, entry_title, suffix):
    """Build a child-specific entity id based on the entry title."""
    clean = slugify(entry_title or "smartschool")
    return f"{domain}.{clean}_{suffix}"


def _entity_suffix_from_unique_id(entry_id, unique_id):
    """Extract the fixed entity suffix from the unique id, not from a legacy entity id."""
    prefix = f"{entry_id}_smartschool_"
    if unique_id.startswith(prefix):
        return unique_id[len(prefix):]
    return None


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Smartschool sensors (planner + agenda items)."""
    session = hass.data[DOMAIN][entry.entry_id]
    entry_id = entry.entry_id
    child_name = entry.title or "Smartschool"

    sensors = [
        SmartschoolPlannerSensor(hass, session, entry_id, child_name),
        SmartschoolStudentSensor(hass, session, entry_id, child_name),
    ]

    try:
        try:
            message_records = await hass.async_add_executor_job(
                _fetch_message_records, session, child_name
            )
            for record in message_records:
                sensors.append(SmartschoolMessageSensor(hass, session, entry_id, child_name, record))
        except Exception as err:
            _LOGGER.error("Error fetching Smartschool messages: %s", err, exc_info=True)

        results = await hass.async_add_executor_job(_fetch_results, session, child_name)
        for result, course in _result_sensor_specs(results):
            result_sensor = SmartschoolResultSensor(hass, session, entry_id, child_name, result, course)
            result_sensor._apply_result(result)
            sensors.append(result_sensor)

        elements = await hass.async_add_executor_job(_fetch_planned_elements, session)

        now = dt_util.utcnow()
        four_weeks_later = now + timedelta(weeks=4)
        upcoming_items = []
        for item in elements:
            start = _get_item_start(item)
            if start is None:
                continue
            parsed_start = _parse_date(start)
            if parsed_start >= now and parsed_start <= four_weeks_later:
                upcoming_items.append(item)

        for idx, item in enumerate(upcoming_items):
            sensors.append(SmartschoolAgendaItemSensor(hass, session, item, idx, entry.entry_id, child_name))

        _LOGGER.info(
            "Smartschool sensors created: %s (results + planner + %s agenda items)",
            len(sensors),
            len(upcoming_items),
        )

    except Exception as e:
        _LOGGER.error("Error fetching agenda items: %s", e, exc_info=True)

    async_add_entities(sensors, True)

    session._smartschool_add_entities = async_add_entities
    session._smartschool_message_ids = {
        sensor._message_id
        for sensor in sensors
        if isinstance(sensor, SmartschoolMessageSensor)
    }
    session._smartschool_add_result_entities = async_add_entities
    session._smartschool_result_keys = {
        (sensor._result_id, sensor._course_id)
        for sensor in sensors
        if isinstance(sensor, SmartschoolResultSensor)
    }

    message_entities = hass.data[DOMAIN].setdefault("message_entities", {})
    for sensor in sensors:
        if isinstance(sensor, SmartschoolMessageSensor):
            message_entities[sensor.entity_id] = {
                "entry_id": entry_id,
                "session": session,
                "message_id": sensor._message_id,
            }

    entity_registry = er.async_get(hass)
    for sensor in sensors:
        unique_id = getattr(sensor, "unique_id", None)
        if not unique_id:
            continue
        old_entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if not old_entity_id:
            continue
        if sensor.platform is None:
            continue
        suffix = _entity_suffix_from_unique_id(entry_id, unique_id)
        if not suffix:
            continue
        desired_id = _preferred_entity_id("sensor", child_name, suffix)
        if old_entity_id != desired_id:
            try:
                entity_registry.async_update_entity(old_entity_id, new_entity_id=desired_id)
            except Exception:
                _LOGGER.debug("Could not change entity id for %s to %s", old_entity_id, desired_id)


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


class SmartschoolPlannerSensor(SensorEntity):
    """Original sensor showing the number of planned elements."""

    def __init__(self, hass, session, entry_id, child_name):
        self.hass = hass
        self._session = session
        self._entry_id = entry_id
        self._child_name = child_name
        self._attr_name = f"{child_name} Planner Count"
        self._attr_unique_id = f"{entry_id}_smartschool_planner_count"
        self._state = None

    async def async_update(self):
        try:
            _LOGGER.info("Planner sensor update started")
            elements = await self.hass.async_add_executor_job(_fetch_planned_elements, self._session)
            message_records = await self.hass.async_add_executor_job(
                _fetch_message_records, self._session, self._child_name
            )
            _add_new_message_entities(
                self.hass,
                self._session,
                self._entry_id,
                self._child_name,
                message_records,
            )
            results = await self.hass.async_add_executor_job(
                _fetch_results, self._session, self._child_name
            )
            _add_new_result_entities(
                self.hass,
                self._session,
                self._entry_id,
                self._child_name,
                results,
            )
            _LOGGER.info("Planner sensor raw element count: %s", len(elements))
            for idx, item in enumerate(elements[:10]):
                _LOGGER.info("Planner item[%s]: %s", idx, item)
            self._state = len(elements)
            _LOGGER.info("Planner sensor update succeeded: %s items", self._state)
        except Exception as e:
            _LOGGER.error("Error fetching planner data: %s", e, exc_info=True)
            self._state = None

    @property
    def native_value(self):
        return self._state


def _extract_people_entries(item):
    """Collect all users from a planner item for profile and avatar data."""
    results = []
    for collection_key in ("organisers", "participants"):
        collection = _get_item_value(item, collection_key)
        if isinstance(collection, dict):
            for user_key in ("users", "persons"):
                users = _get_item_value(collection, user_key)
                if isinstance(users, list):
                    for user in users:
                        results.append(user)
    return results


class SmartschoolStudentSensor(SensorEntity):
    """Sensor with the name and profile picture of the logged-in student."""

    def __init__(self, hass, session, entry_id, child_name):
        self.hass = hass
        self._session = session
        self._entry_id = entry_id
        self._attr_name = f"{child_name} Student"
        self._attr_unique_id = f"{entry_id}_smartschool_student"
        self._attr_icon = "mdi:account"
        self._state = "Unknown"
        self._attributes = {
            "student_id": None,
            "full_name": None,
            "picture_url": None,
            "organiser_picture_urls": [],
            "participant_picture_urls": [],
        }
        self._attr_entity_picture = None

    def _get_first_user_name(self, user):
        if not isinstance(user, dict):
            return None
        name_fields = _get_item_value(user, "name")
        if isinstance(name_fields, dict):
            first_name = _get_item_value(name_fields, "startingWithFirstName") or _get_item_value(name_fields, "firstName")
            last_name = _get_item_value(name_fields, "startingWithLastName") or _get_item_value(name_fields, "lastName")
            if first_name and last_name:
                return f"{first_name} {last_name}"
            if first_name:
                return first_name
            if last_name:
                return last_name
        for key in ("displayName", "fullName", "name"):
            if key in user:
                return user[key]
        return None

    def _extract_student(self, items):
        user_id = None
        auth = self._session.authenticated_user
        if isinstance(auth, dict):
            user_id = auth.get("id") or auth.get("userId")

        for item in items:
            for user in _extract_people_entries(item):
                if not isinstance(user, dict):
                    continue
                user_key = user.get("id") or user.get("userId")
                if user_id and user_key == user_id:
                    return {
                        "id": user_key,
                        "name": self._get_first_user_name(user),
                        "picture_url": user.get("pictureUrl") or user.get("picture_url"),
                    }

        for item in items:
            for user in _extract_people_entries(item):
                if not isinstance(user, dict):
                    continue
                return {
                    "id": user.get("id") or user.get("userId"),
                    "name": self._get_first_user_name(user),
                    "picture_url": user.get("pictureUrl") or user.get("picture_url"),
                }

        return {
            "id": user_id,
            "name": auth.get("name") if isinstance(auth, dict) else None,
            "picture_url": auth.get("pictureUrl") if isinstance(auth, dict) else None,
        }

    async def async_update(self):
        try:
            items = await self.hass.async_add_executor_job(_fetch_planned_elements, self._session)
            student = self._extract_student(items)
            display_name = student.get("name") or "Student"
            picture_url = student.get("picture_url")

            self._state = display_name
            self._attributes = {
                "student_id": student.get("id"),
                "full_name": display_name,
                "picture_url": picture_url,
                "organiser_picture_urls": [],
                "participant_picture_urls": [],
            }
            self._attr_entity_picture = picture_url

            for item in items:
                for user in _extract_people_entries(item):
                    if not isinstance(user, dict):
                        continue
                    user_url = user.get("pictureUrl") or user.get("picture_url")
                    if not user_url:
                        continue
                    if "organisers" in str(item):
                        self._attributes["organiser_picture_urls"].append(
                            {
                                "id": user.get("id") or user.get("userId"),
                                "name": self._get_first_user_name(user),
                                "picture_url": user_url,
                            }
                        )
                    if "participants" in str(item):
                        self._attributes["participant_picture_urls"].append(
                            {
                                "id": user.get("id") or user.get("userId"),
                                "name": self._get_first_user_name(user),
                                "picture_url": user_url,
                            }
                        )

            self._attributes["organiser_picture_urls"] = list(
                {tuple(sorted((k, str(v)) for k, v in entry.items())): entry for entry in self._attributes["organiser_picture_urls"]}.values()
            )
            self._attributes["participant_picture_urls"] = list(
                {tuple(sorted((k, str(v)) for k, v in entry.items())): entry for entry in self._attributes["participant_picture_urls"]}.values()
            )

        except Exception as e:
            _LOGGER.error("Error fetching Smartschool student data: %s", e, exc_info=True)
            self._state = "Unknown"
            self._attributes = {
                "student_id": None,
                "full_name": None,
                "picture_url": None,
                "organiser_picture_urls": [],
                "participant_picture_urls": [],
            }
            self._attr_entity_picture = None

    @property
    def extra_state_attributes(self):
        return self._attributes


class SmartschoolAgendaItemSensor(SensorEntity):
    """Sensor for a single Smartschool agenda item."""

    def __init__(self, hass, session, item, idx, entry_id, child_name):
        self.hass = hass
        self._session = session
        self._item_key = _get_item_value(item, "id") or idx
        self._apply_item(item, entry_id, child_name)

    def _apply_item(self, item, entry_id=None, child_name=None):
        self._item = item
        if entry_id is not None:
            self._entry_id = entry_id
        if child_name is not None:
            self._child_name = child_name
        title = _get_item_title(item)
        item_type, icon = _detect_item_type(item)
        self._attr_name = f"{self._child_name} Agenda {title}"
        self._attr_unique_id = f"{self._entry_id}_smartschool_agenda_{self._item_key}"
        self._attr_icon = icon
        self._state = title
        self._attributes = self._build_attributes()
        self._attributes["item_type"] = item_type
        self._attributes["category"] = item_type
        self._attributes["icon"] = icon

    def _build_attributes(self):
        """Put all item details into attributes."""
        attrs = _to_plain_value(self._item)
        attrs["title"] = _get_item_title(self._item)
        return attrs

    async def async_update(self):
        elements = await self.hass.async_add_executor_job(_fetch_planned_elements, self._session)
        for item in elements:
            if (_get_item_value(item, "id") or None) == self._item_key:
                self._apply_item(item)
                return

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes
