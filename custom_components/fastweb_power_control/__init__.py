"""Fastweb Power Control integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FastwebClient, FastwebError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

PLATFORMS = (Platform.SENSOR,)
LOGGER = logging.getLogger(__name__)


class FastwebCoordinator(DataUpdateCoordinator[dict]):
    """Poll Fastweb once and share the result with entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = FastwebClient(
            entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )

    async def _async_update_data(self) -> dict:
        try:
            payload = await self.hass.async_add_executor_job(self.client.get_realtime)
        except FastwebError as error:
            raise UpdateFailed(str(error)) from error
        return payload["data"]


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
