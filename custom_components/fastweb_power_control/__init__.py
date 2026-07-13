"""Fastweb Power Control integration."""

from __future__ import annotations

from datetime import timedelta
from functools import partial
import logging
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FastwebClient, FastwebError, InvalidAuth
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

PLATFORMS = (Platform.DATE, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH)
SETTINGS_REFRESH_SECONDS = 600
LOGGER = logging.getLogger(__name__)


class FastwebCoordinator(DataUpdateCoordinator[dict]):
    """Poll Fastweb and coordinate configuration writes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_SCAN_INTERVAL,
                    entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                )
            ),
        )
        self.entry = entry
        self.client = FastwebClient(
            entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )
        self.settings: dict = {}
        self._last_settings_update = 0.0

    async def _async_update_data(self) -> dict:
        try:
            payload = await self.hass.async_add_executor_job(self.client.get_realtime)
            if (
                not self.settings
                or monotonic() - self._last_settings_update >= SETTINGS_REFRESH_SECONDS
            ):
                try:
                    self.settings = await self.hass.async_add_executor_job(
                        self.client.get_settings
                    )
                    self._last_settings_update = monotonic()
                except InvalidAuth:
                    raise
                except FastwebError as error:
                    LOGGER.warning("Unable to refresh Fastweb settings: %s", error)
        except InvalidAuth as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except FastwebError as error:
            raise UpdateFailed(str(error)) from error
        return {**payload["data"], "settings": self.settings}

    async def async_set_setting(self, group: str, key: str, value: object) -> None:
        """Write one setting and immediately publish the accepted state."""
        method = {
            "led": self.client.update_led_settings,
            "notifications": self.client.update_notification_settings,
        }.get(group)
        if method is None:
            raise HomeAssistantError(f"Unknown Fastweb settings group: {group}")
        try:
            updated = await self.hass.async_add_executor_job(
                partial(method, {key: value})
            )
        except InvalidAuth as error:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(error)) from error
        except FastwebError as error:
            raise HomeAssistantError(str(error)) from error

        self.settings = {**self.settings, group: updated}
        self._last_settings_update = monotonic()
        self.async_set_updated_data({**(self.data or {}), "settings": self.settings})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = FastwebCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
