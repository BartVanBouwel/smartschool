import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN
from smartschool import Smartschool, AppCredentials
from smartschool import BoxType, MarkMessageUnread, Message

_LOGGER = logging.getLogger(__name__)
SERVICE_MARK_MESSAGE_READ = "mark_message_read"
SERVICE_MARK_MESSAGE_UNREAD = "mark_message_unread"
MARK_MESSAGE_READ_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
    vol.Required("message_id"): vol.Coerce(int),
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
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = session
        hass.data[DOMAIN].setdefault("message_entities", {})
        _LOGGER.info("Smartschool session created for user: %s", creds.username)

        # Load sensor and calendar platforms (new HA API)
        await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "calendar"])
        _LOGGER.debug("Sensor and calendar platforms loaded successfully")
        return True

    except Exception as e:
        _LOGGER.error("Error setting up Smartschool integration: %s", e, exc_info=True)
        return False


def _invalidate_message_cache(session, message_id):
    """Force a fresh fetch on the next update instead of using the 10-minute cache."""
    session._smartschool_messages_cache_at = None
    content_cache = getattr(session, "_smartschool_message_content_cache", None)
    if content_cache is not None:
        content_cache.pop(message_id, None)


async def _async_mark_message_read(hass: HomeAssistant, call):
    """Open a Smartschool message; Smartschool registers this as read."""
    entity_id = call.data["entity_id"]
    message_id = call.data["message_id"]
    message_info = hass.data.get(DOMAIN, {}).get("message_entities", {}).get(entity_id)
    if not message_info or int(message_info["message_id"]) != message_id:
        raise ValueError(f"Unknown Smartschool message entity or message ID: {entity_id}/{message_id}")

    session = message_info["session"]

    def open_message():
        session.ensure_authenticated()
        list(Message(session, message_id, box_type=BoxType.INBOX))

    await hass.async_add_executor_job(open_message)
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


async def async_setup(hass: HomeAssistant, config):
    """Register integration-wide Smartschool services."""
    if not hass.services.has_service(DOMAIN, SERVICE_MARK_MESSAGE_READ):
        hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_MESSAGE_READ,
            lambda call: _async_mark_message_read(hass, call),
            schema=MARK_MESSAGE_READ_SCHEMA,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_MARK_MESSAGE_UNREAD):
        hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_MESSAGE_UNREAD,
            lambda call: _async_mark_message_unread(hass, call),
            schema=MARK_MESSAGE_READ_SCHEMA,
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
