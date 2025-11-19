"""Config flow for ClassCharts integration."""

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from pyclasscharts import ParentClient
from pyclasscharts.exceptions import AuthenticationError, ValidationError

from .const import DOMAIN


class ClassChartsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ClassCharts."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                # Validate credentials by attempting to login
                client = ParentClient(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
                await self.hass.async_add_executor_job(client.login)
                
                # Get pupils to verify account has pupils
                pupils = await self.hass.async_add_executor_job(client.get_pupils)
                
                if not pupils:
                    errors["base"] = "no_pupils"
                else:
                    # Create entry with email as unique_id
                    await self.async_set_unique_id(user_input[CONF_EMAIL])
                    self._abort_if_unique_id_configured()
                    
                    return self.async_create_entry(
                        title=user_input[CONF_EMAIL],
                        data=user_input,
                    )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ValidationError as err:
                errors["base"] = "validation_error"
                if "no pupils" in str(err).lower():
                    errors["base"] = "no_pupils"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

