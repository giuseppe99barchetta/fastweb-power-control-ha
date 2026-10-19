"""UI setup for Fastweb Power Control."""

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import FastwebClient, FastwebError, InvalidAuth, RecaptchaRequired
from .const import (
    CONF_COOKIE,
    CONF_SCAN_INTERVAL,
    CONF_WARNING_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_WARNING_THRESHOLD,
    DOMAIN,
)

LOGGER = logging.getLogger(__name__)


async def _validate(hass: HomeAssistant, data: dict) -> str:
    """Validate credentials and return the renewable Fastweb cookies."""
    client = FastwebClient(
        data[CONF_USERNAME], data[CONF_PASSWORD], data.get(CONF_COOKIE, "")
    )
    await hass.async_add_executor_job(client.get_realtime)
    return client.cookie_header


async def _async_try_validate(
    hass: HomeAssistant, data: dict, step: str, errors: dict[str, str]
) -> str | None:
    """Validate and fill ``errors``; return the cookies on success."""
    try:
        return await _validate(hass, data)
    except RecaptchaRequired as error:
        LOGGER.warning("Fastweb requires reCAPTCHA during %s: %s", step, error)
        errors["base"] = "recaptcha_required"
    except InvalidAuth as error:
        LOGGER.warning("Fastweb authentication failed during %s: %s", step, error)
        errors["base"] = "invalid_auth"
    except FastwebError as error:
        LOGGER.warning("Unable to connect to Fastweb during %s: %s", step, error)
        errors["base"] = "cannot_connect"
    return None


def _account_id(username: str) -> str:
    return username.strip().lower()


def _credentials_schema(username: str = "", include_interval: bool = False) -> vol.Schema:
    fields: dict = {
        vol.Required(CONF_USERNAME, default=username): TextSelector(TextSelectorConfig()),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_COOKIE): TextSelector(
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
            await self.async_set_unique_id(_account_id(user_input[CONF_USERNAME]))
            self._abort_if_unique_id_configured()
            cookie = await _async_try_validate(self.hass, user_input, "setup", errors)
            if not errors:
                data = {
                    key: value
                    for key, value in user_input.items()
                    if key != CONF_COOKIE
                }
                if cookie:
                    data[CONF_COOKIE] = cookie
                return self.async_create_entry(title="Fastweb Power Control", data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=_credentials_schema(include_interval=True),
            errors=errors,
        )

    async def _async_update_credentials(
        self,
        entry: config_entries.ConfigEntry,
        user_input: dict,
        step: str,
        errors: dict[str, str],
    ) -> ConfigFlowResult | None:
        """Shared reauth/reconfigure logic: same account, new credentials."""
        await self.async_set_unique_id(_account_id(user_input[CONF_USERNAME]))
        self._abort_if_unique_id_mismatch(reason="wrong_account")
        updated = {**entry.data, **user_input}
        cookie = await _async_try_validate(self.hass, updated, step, errors)
        if errors:
            return None
        if cookie:
            updated[CONF_COOKIE] = cookie
        elif CONF_COOKIE in user_input:
            updated.pop(CONF_COOKIE, None)
        return self.async_update_reload_and_abort(entry, data_updates=updated)

    async def async_step_reauth(self, entry_data: dict) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None and (
            result := await self._async_update_credentials(
                entry, user_input, "reauthentication", errors
            )
        ):
            return result
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_credentials_schema(entry.data[CONF_USERNAME]),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None and (
            result := await self._async_update_credentials(
                entry, user_input, "reconfiguration", errors
            )
        ):
            return result
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_credentials_schema(entry.data[CONF_USERNAME]),
            errors=errors,
        )


class FastwebOptionsFlow(config_entries.OptionsFlowWithReload):
    """Edit runtime options without recreating the integration."""

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        warning_threshold = self.config_entry.options.get(
            CONF_WARNING_THRESHOLD, DEFAULT_WARNING_THRESHOLD
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=10, max=300, step=5, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_WARNING_THRESHOLD, default=warning_threshold
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=50, max=100, step=1, mode=NumberSelectorMode.SLIDER
                        )
                    ),
                }
            ),
        )
