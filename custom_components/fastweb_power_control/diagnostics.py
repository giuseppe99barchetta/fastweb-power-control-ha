"""Diagnostics for Fastweb Power Control."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "data": coordinator.data,
    }
