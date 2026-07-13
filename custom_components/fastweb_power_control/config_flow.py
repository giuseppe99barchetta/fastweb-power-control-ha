"""UI setup for Fastweb Power Control."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import FastwebClient, FastwebError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN


async def _validate(hass: HomeAssistant, data: dict) -> None:
    client = FastwebClient(data[CONF_USERNAME], data[CONF_PASSWORD])
    await hass.async_add_executor_job(client.get_realtime)


class FastwebPowerControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one Fastweb Power Control account."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate(self.hass, user_input)
            except FastwebError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="Fastweb Power Control", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): TextSelector(TextSelectorConfig()),
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=10, max=300, step=5, mode=NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
