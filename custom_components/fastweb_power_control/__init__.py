"""Fastweb Power Control integration."""

from __future__ import annotations

from homeassistant.const import CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import FastwebConfigEntry, FastwebCoordinator
from .services import async_setup_services

PLATFORMS = (
    Platform.BINARY_SENSOR,
    Platform.DATE,
    Platform.EVENT,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FastwebConfigEntry) -> bool:
    if entry.unique_id is None:
        # Entries created before 0.5 have no account identifier.
        hass.config_entries.async_update_entry(
            entry, unique_id=entry.data[CONF_USERNAME].strip().lower()
        )
    coordinator = FastwebCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FastwebConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
