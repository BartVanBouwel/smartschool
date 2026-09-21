
import voluptuous as vol
import logging
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from .const import DOMAIN
from smartschool import Smartschool, AppCredentials

_LOGGER = logging.getLogger(__name__)

CONF_MAIN_URL = "main_url"
CONF_MFA = "mfa"
CONF_NAME = "name"
CONF_ENABLE_LOGGING = "enable_logging"
CONF_CREATE_PERSON = "create_person"


class SmartschoolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for the Smartschool integration."""
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        return SmartschoolOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}

        print("DEBUG: Config flow started")

        if user_input is not None:
            try:
                _LOGGER.debug("Smartschool config flow started with input: %s",
                              {k: v for k, v in user_input.items() if k != CONF_PASSWORD})
                print("DEBUG: Smartschool config flow started with input: %s",
                              {k: v for k, v in user_input.items() if k != CONF_PASSWORD})

                # Build and validate credentials
                creds = AppCredentials(
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    main_url=user_input[CONF_MAIN_URL],
                    mfa=user_input.get(CONF_MFA, "")
                )
                creds.validate()  # IMPORTANT: check that all fields are correct

                # Create Smartschool session
                session = Smartschool(creds)

                # Force login in a thread-safe way
                await self.hass.async_add_executor_job(session.get, "/")
                authenticated_user = session.authenticated_user

                candidate_name = (
                    user_input.get(CONF_NAME)
                    or authenticated_user.get("name")
                    or authenticated_user.get("username")
                    or "Smartschool"
                ).strip()
                if not candidate_name:
                    candidate_name = "Smartschool"

                user_input[CONF_NAME] = candidate_name

                print("DEBUG: Smartschool login succeeded for user: %s", authenticated_user.get("username", "unknown"))

                _LOGGER.debug("Smartschool login succeeded for user: %s", authenticated_user.get("username", "unknown"))

                return self.async_create_entry(title=candidate_name, data=user_input)

            except Exception as e:
                _LOGGER.error("Smartschool login failed: %s", e, exc_info=True)
                print(f"DEBUG: Smartschool login failed: {e}")
                errors["base"] = "auth_failed"

        default_name = "Smartschool"
        schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_MAIN_URL): str,
            vol.Optional(CONF_MFA): str,
            vol.Optional(CONF_NAME, default=default_name): str
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "mfa_hint": "Use YYYY-MM-DD (date of birth) or a Google Authenticator secret"
            }
        )


class SmartschoolOptionsFlow(config_entries.OptionsFlow):
    """Per-child options, reachable via the integration's "Configure" button."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_logging = self.config_entry.options.get(CONF_ENABLE_LOGGING, False)
        current_person = self.config_entry.options.get(CONF_CREATE_PERSON, False)
        schema = vol.Schema({
            vol.Optional(CONF_ENABLE_LOGGING, default=current_logging): bool,
            vol.Optional(CONF_CREATE_PERSON, default=current_person): bool,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
