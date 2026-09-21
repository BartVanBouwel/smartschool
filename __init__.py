import logging
from pathlib import Path
from xml.sax.saxutils import quoteattr

import voluptuous as vol
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from .const import DOMAIN
from smartschool import Smartschool, AppCredentials
from smartschool import BoxType, MarkMessageUnread

_LOGGER = logging.getLogger(__name__)
_WWW_DIR = Path(__file__).parent / "www"
_STATIC_URL_BASE = "/smartschool_static"


def _asset_version(filename: str) -> str:
    """Cache-busting query value derived from the file's mtime.

    Browsers cache `type="module"` scripts very aggressively on the exact URL --
    a plain reload (F5) can keep serving a stale (possibly older/broken) cached
    copy indefinitely, only a hard reload (Ctrl+F5) bypasses it. Tying the URL to
    the file's last-modified time means any future edit to these files changes
    the URL automatically on the next Home Assistant start, forcing a fresh fetch
    without anyone having to remember bumping a version number by hand.
    """
    try:
        return str(int((_WWW_DIR / filename).stat().st_mtime))
    except OSError:
        return "0"


async def _async_register_lovelace_resource(hass: HomeAssistant, url: str, res_type: str) -> bool:
    """Register a Lovelace resource the same way the "Add resource" UI does.

    This is the *only* reliable way to load our own card scripts -- see the
    detailed comment at the call site in async_setup() for why
    `add_extra_js_url()` alone actively causes the "Custom element doesn't
    exist" bug rather than just being an unnecessary extra step.

    Best-effort and idempotent: skipped/logged, never allowed to break setup,
    since dashboards in YAML mode don't have a writable resource collection.
    Returns whether registration succeeded, so the caller can fall back to
    `add_extra_js_url()` (better than nothing) when it didn't.
    """
    try:
        lovelace_data = hass.data.get("lovelace")
        resources = getattr(lovelace_data, "resources", None)
        if resources is None:
            return False
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        base_url = url.split("?", 1)[0]
        for item in resources.async_items():
            if item.get("url", "").split("?", 1)[0] == base_url:
                if item.get("url") != url:
                    await resources.async_update_item(item["id"], {"url": url})
                return True
        await resources.async_create_item({"res_type": res_type, "url": url})
        return True
    except Exception as err:
        _LOGGER.warning(
            "Could not auto-register %s as a Lovelace resource (%s); if the card shows "
            "'Custom element doesn't exist', add it manually via Settings -> Dashboards -> "
            "Resources instead.",
            url, err,
        )
        return False


SERVICE_MARK_MESSAGE_READ = "mark_message_read"
SERVICE_MARK_MESSAGE_UNREAD = "mark_message_unread"
SERVICE_MARK_RESULT_READ = "mark_result_read"
SERVICE_REFRESH = "refresh"
MARK_MESSAGE_READ_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
    vol.Required("message_id"): vol.Coerce(int),
})
MARK_RESULT_READ_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
})
REFRESH_SCHEMA = vol.Schema({
    vol.Optional("entity_id"): cv.entity_ids,
})


def _redact_sensitive_value(value):
    """Hide sensitive values in logs."""
    if value is None:
        return "<none>"
    text = str(value)
    if len(text) <= 4:
        return "***"
    return text[:2] + "***" + text[-2:]


def _enable_api_debug_logging(session):
    """Log all Smartschool HTTP requests/responses with safe redaction."""
    original_request = session.request

    def logged_request(method, url, **kwargs):
        method_name = str(method).upper()
        # Without a timeout, a single hanging call can permanently occupy an executor
        # thread, meaning the entity waiting on it never gets rescheduled again.
        kwargs.setdefault("timeout", 30)
        _LOGGER.debug("Smartschool API REQUEST %s %s", method_name, url)

        if "data" in kwargs and kwargs["data"] is not None:
            data = kwargs["data"]
            if isinstance(data, dict):
                redacted = {}
                for key, value in data.items():
                    if "pass" in key.lower() or "secret" in key.lower() or "token" in key.lower():
                        redacted[key] = _redact_sensitive_value(value)
                    else:
                        redacted[key] = value
                _LOGGER.debug("Smartschool API REQUEST DATA %s", redacted)
            else:
                _LOGGER.debug("Smartschool API REQUEST DATA %s", "<non-dict payload>")

        response = original_request(method, url, **kwargs)

        try:
            status = response.status_code
            body = getattr(response, "text", "")
            body_preview = (body[:500].replace("\n", " ") if isinstance(body, str) else str(body))
            _LOGGER.debug("Smartschool API RESPONSE %s %s status=%s body=%s", method_name, url, status, body_preview)
        except Exception:
            _LOGGER.debug("Smartschool API RESPONSE %s %s", method_name, url)

        return response

    session.request = logged_request
    _LOGGER.debug("Smartschool API request logging enabled")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Setup Smartschool integration from a config entry."""
    _LOGGER.debug("Starting Smartschool integration setup")
    try:
        # Retrieve and validate credentials
        creds = AppCredentials(
            username=entry.data["username"],
            password=entry.data["password"],
            main_url=entry.data["main_url"],
            mfa=entry.data.get("mfa", "")
        )
        creds.validate()

        # Create Smartschool session
        session = Smartschool(creds)
        _enable_api_debug_logging(session)
        # Off by default: CSV/debug-log export under custom_components/smartschool/logging/
        # grows without bound (confirmed live: multi-hundred-MB debug logs after a few
        # weeks) and contains real message/result content, so it should be an explicit
        # opt-in via the integration's "Configure" options, not always-on.
        session._smartschool_logging_enabled = entry.options.get("enable_logging", False)
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = session
        hass.data[DOMAIN].setdefault("message_entities", {})
        _LOGGER.info("Smartschool session created for user: %s", creds.username)

        entry.async_on_unload(entry.add_update_listener(_async_update_listener))

        # Load sensor and calendar platforms (new HA API)
        await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "calendar"])
        _LOGGER.debug("Sensor and calendar platforms loaded successfully")
        return True

    except Exception as e:
        _LOGGER.error("Error setting up Smartschool integration: %s", e, exc_info=True)
        return False


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Reload the entry when its options change (e.g. the logging toggle)."""
    await hass.config_entries.async_reload(entry.entry_id)


def _invalidate_message_cache(session, message_id):
    """Force a fresh fetch on the next update instead of using the 10-minute cache."""
    session._smartschool_messages_cache_at = None
    content_cache = getattr(session, "_smartschool_message_content_cache", None)
    if content_cache is not None:
        content_cache.pop(message_id, None)


def _mark_message_read_serverside(session, message_id, box_type=BoxType.INBOX):
    """Explicitly mark a message read via Smartschool's XML dispatcher.

    Fetching the message content ("show message") does NOT flip the server-side
    unread flag on its own, despite that being the assumption baked into the
    smartschool library's docs -- confirmed live: the flag stayed unread even
    10 seconds after fetching. The `smartschool` library only exposes the
    opposite action (`MarkMessageUnread`, subsystem "postboxes", action
    "mark message unread"); its exact counterpart "mark message read" isn't
    wrapped by the library but is accepted by the server (confirmed live,
    returns <status>1</status> and actually flips the flag), so we call it
    directly here using the same XML dispatcher the library itself posts to.
    """
    command = (
        "<request><command>"
        "<subsystem>postboxes</subsystem>"
        "<action>mark message read</action>"
        "<params>"
        f"<param name={quoteattr('boxType')}><![CDATA[{box_type.value}]]></param>"
        f"<param name={quoteattr('boxID')}><![CDATA[0]]></param>"
        f"<param name={quoteattr('msgID')}><![CDATA[{message_id}]]></param>"
        f"<param name={quoteattr('clAction')}><![CDATA[status]]></param>"
        "</params></command></request>"
    )
    session.post(
        "/?module=Messages&file=dispatcher",
        data={"command": command},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )


async def _async_mark_message_read(hass: HomeAssistant, call):
    """Mark a Smartschool message as read."""
    entity_id = call.data["entity_id"]
    message_id = call.data["message_id"]
    message_info = hass.data.get(DOMAIN, {}).get("message_entities", {}).get(entity_id)
    if not message_info or int(message_info["message_id"]) != message_id:
        raise ValueError(f"Unknown Smartschool message entity or message ID: {entity_id}/{message_id}")

    session = message_info["session"]

    def mark_read():
        session.ensure_authenticated()
        _mark_message_read_serverside(session, message_id)

    await hass.async_add_executor_job(mark_read)
    _invalidate_message_cache(session, message_id)
    _LOGGER.info("Smartschool message %s opened as read via %s", message_id, entity_id)
    await hass.services.async_call("homeassistant", "update_entity", {"entity_id": entity_id}, blocking=True)


async def _async_mark_message_unread(hass: HomeAssistant, call):
    """Mark a Smartschool message as unread."""
    entity_id = call.data["entity_id"]
    message_id = call.data["message_id"]
    message_info = hass.data.get(DOMAIN, {}).get("message_entities", {}).get(entity_id)
    if not message_info or int(message_info["message_id"]) != message_id:
        raise ValueError(f"Unknown Smartschool message entity or message ID: {entity_id}/{message_id}")

    session = message_info["session"]

    def mark_unread():
        session.ensure_authenticated()
        list(MarkMessageUnread(session, message_id, box_type=BoxType.INBOX))

    await hass.async_add_executor_job(mark_unread)
    _invalidate_message_cache(session, message_id)
    _LOGGER.info("Smartschool message %s marked as unread via %s", message_id, entity_id)
    await hass.services.async_call("homeassistant", "update_entity", {"entity_id": entity_id}, blocking=True)


async def _async_mark_result_read(hass: HomeAssistant, call):
    """Flag a Smartschool result sensor as read (locally tracked; Smartschool has no server-side concept of this).

    Looked up by matching the current `entity_id` attribute on each known sensor
    instance at call time, rather than a dict keyed by entity_id captured at
    registration time -- `async_add_entities()` is called without awaiting it,
    so `sensor.entity_id` isn't necessarily assigned yet right after that call,
    and a dict keyed on it then can end up with a stale/empty key (confirmed
    live: "Unknown Smartschool result entity" for a real, existing sensor).
    """
    entity_id = call.data["entity_id"]
    result_sensors = hass.data.get(DOMAIN, {}).get("result_sensors", [])
    sensor = next((s for s in result_sensors if s.entity_id == entity_id), None)
    if sensor is None:
        raise ValueError(f"Unknown Smartschool result entity: {entity_id}")

    sensor.mark_read()
    sensor.async_write_ha_state()
    _LOGGER.info("Smartschool result %s marked as read via %s", sensor._result_id, entity_id)


async def _async_refresh(hass: HomeAssistant, call):
    """Force an immediate re-fetch from Smartschool, bypassing the normal 10/15-minute cache.

    `homeassistant.update_entity` alone isn't enough for this: it forces
    `async_update()` to run, but `_fetch_results`/`_fetch_message_records` still
    return their cached data as long as it's within the TTL, since the cache is
    keyed on elapsed time, not on whether the caller explicitly asked to bypass it.
    So this first clears each session's cache timestamps, then calls update_entity.

    `entity_id` may name specific children's entities to scope the refresh to just
    those Smartschool logins; omitted, every configured child is refreshed.
    """
    domain_data = hass.data.get(DOMAIN, {})
    entity_ids = call.data.get("entity_id")

    if entity_ids:
        registry = er.async_get(hass)
        entry_ids = set()
        for entity_id in entity_ids:
            entry = registry.async_get(entity_id)
            if entry and entry.config_entry_id:
                entry_ids.add(entry.config_entry_id)
        if not entry_ids:
            raise ValueError(f"Could not resolve a Smartschool config entry for: {entity_ids}")
    else:
        entry_ids = {key for key in domain_data if key not in ("message_entities", "result_sensors")}

    message_entities = domain_data.get("message_entities", {})
    result_sensors = domain_data.get("result_sensors", [])
    to_update = []

    for entry_id in entry_ids:
        session = domain_data.get(entry_id)
        if session is None:
            continue
        session._smartschool_results_cache_at = None
        session._smartschool_messages_cache_at = None
        to_update.extend(eid for eid, info in message_entities.items() if info.get("entry_id") == entry_id)
        to_update.extend(sensor.entity_id for sensor in result_sensors if sensor._entry_id == entry_id)

    if to_update:
        await hass.services.async_call("homeassistant", "update_entity", {"entity_id": to_update}, blocking=True)
    _LOGGER.info("Smartschool refresh triggered for entries=%s (%s entities)", entry_ids, len(to_update))


async def async_setup(hass: HomeAssistant, config):
    """Register integration-wide Smartschool services."""

    await hass.http.async_register_static_paths([
        StaticPathConfig(_STATIC_URL_BASE, str(_WWW_DIR), False)
    ])
    # Auto-loads the card's JS on every frontend page, so it works without the
    # user having to add it as a Lovelace resource by hand. Idempotent: the
    # frontend component keeps these URLs in a set, so a reload never duplicates it.
    # Wrapped defensively: this must never take down service registration below
    # just because the frontend component's internal state isn't there yet.
    # IMPORTANT: these must go through the Lovelace resource loader ONLY, not
    # `add_extra_js_url()`. That function injects an eager <script> that runs
    # concurrently with Home Assistant's own frontend bundle -- and that bundle
    # replaces `window.customElements` with its own scoped registry shim while
    # it boots. If our script's `customElements.define()` runs before that
    # swap (which it usually does, since add_extra_js_url's <script> starts
    # essentially immediately, and a warm cache makes it resolve even faster),
    # it registers on the *old* registry object, while Lovelace later checks
    # the *new* (shimmed) one -- so the element silently "doesn't exist" to it.
    # Confirmed against a known, matching issue in another HA integration that
    # bundles a custom card this same way (aex351/home-assistant-neerslag-card
    # issue #58: "extra_module_url races the frontend's custom element
    # registry"). The Lovelace resource loader itself runs later, after that
    # bundle/shim swap has already happened, so it doesn't hit this race.
    mammoth_url = f"{_STATIC_URL_BASE}/mammoth.browser.min.js?v={_asset_version('mammoth.browser.min.js')}"
    mammoth_registered = await _async_register_lovelace_resource(hass, mammoth_url, "js")
    if not mammoth_registered:
        try:
            add_extra_js_url(hass, mammoth_url, es5=True)
        except Exception as err:
            _LOGGER.error("Could not register mammoth.browser.min.js with the frontend: %s", err, exc_info=True)

    for js_file in ("smartschool-results-card.js", "smartschool-messages-card.js"):
        url = f"{_STATIC_URL_BASE}/{js_file}?v={_asset_version(js_file)}"
        registered = await _async_register_lovelace_resource(hass, url, "module")
        if not registered:
            try:
                add_extra_js_url(hass, url)
            except Exception as err:
                _LOGGER.error("Could not register %s with the frontend: %s", js_file, err, exc_info=True)

    # These must be real `async def` callables, not a `lambda` returning a coroutine:
    # HA decides how to schedule a service handler by inspecting the callable itself
    # with `asyncio.iscoroutinefunction()`. A lambda always fails that check even
    # though calling it produces a coroutine, so HA schedules it as a plain callback,
    # calls it once, and discards the returned (never-awaited) coroutine without
    # ever running its body -- the service call still reports success. Confirmed
    # live: a debug file written as the very first line of _async_mark_message_read
    # never got created after calling the service, despite an HTTP 200 response.
    async def _handle_mark_message_read(call):
        await _async_mark_message_read(hass, call)

    async def _handle_mark_message_unread(call):
        await _async_mark_message_unread(hass, call)

    async def _handle_mark_result_read(call):
        await _async_mark_result_read(hass, call)

    async def _handle_refresh(call):
        await _async_refresh(hass, call)

    if not hass.services.has_service(DOMAIN, SERVICE_MARK_MESSAGE_READ):
        hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_MESSAGE_READ,
            _handle_mark_message_read,
            schema=MARK_MESSAGE_READ_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_MARK_MESSAGE_UNREAD):
        hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_MESSAGE_UNREAD,
            _handle_mark_message_unread,
            schema=MARK_MESSAGE_READ_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_MARK_RESULT_READ):
        hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_RESULT_READ,
            _handle_mark_result_read,
            schema=MARK_RESULT_READ_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH,
            _handle_refresh,
            schema=REFRESH_SCHEMA,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload Smartschool integration."""
    _LOGGER.debug("Unloading Smartschool integration")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor", "calendar"])
    if unload_ok:
        domain_data = hass.data.get(DOMAIN)
        if isinstance(domain_data, dict):
            message_entities = domain_data.get("message_entities", {})
            for entity_id, info in list(message_entities.items()):
                if info.get("entry_id") == entry.entry_id:
                    message_entities.pop(entity_id, None)
            result_sensors = domain_data.get("result_sensors", [])
            domain_data["result_sensors"] = [
                sensor for sensor in result_sensors if sensor._entry_id != entry.entry_id
            ]
            domain_data.pop(entry.entry_id, None)
            if not domain_data:
                hass.data.pop(DOMAIN, None)
        _LOGGER.info("Smartschool session removed")
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Reload Smartschool integration."""
    _LOGGER.debug("Reloading Smartschool integration")
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
