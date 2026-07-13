"""UI setup for Fastweb Power Control."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import FastwebClient, FastwebError, InvalidAuth
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN


async def _validate(hass: HomeAssistant, data: dict) -> None:
    client = FastwebClient(data[CONF_USERNAME], data[CONF_PASSWORD])
    await hass.async_add_executor_job(client.get_realtime)


def _credentials_schema(username: str = "", include_interval: bool = False) -> vol.Schema:
    fields: dict = {
        vol.Required(CONF_USERNAME, default=username): TextSelector(TextSelectorConfig()),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
    if include_interval:
        fields[
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL)
        ] = NumberSelector(
            NumberSelectorConfig(min=10, max=300, step=5, mode=NumberSelectorMode.BOX)
        )
    return vol.Schema(fields)


class FastwebPowerControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one Fastweb Power Control account."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> FastwebOptionsFlow:
        return FastwebOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except FastwebError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="Fastweb Power Control", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_credentials_schema(include_interval=True),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            updated = {**entry.data, **user_input}
            try:
                await _validate(self.hass, updated)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except FastwebError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=updated)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_credentials_schema(entry.data[CONF_USERNAME]),
            errors=errors,
        )


class FastwebOptionsFlow(config_entries.OptionsFlowWithReload):
    """Edit the polling interval without recreating the integration."""

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=10, max=300, step=5, mode=NumberSelectorMode.BOX
                        )
                    )
                }
            ),
        )
