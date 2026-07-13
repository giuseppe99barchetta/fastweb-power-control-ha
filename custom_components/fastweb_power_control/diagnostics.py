"""Diagnostics for Fastweb Power Control."""

from __future__ import annotations

from time import monotonic

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import AUTH_COOKIE_NAMES
from .const import DOMAIN

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    samples = coordinator.latest_samples
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "data": coordinator.data,
        "runtime": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": coordinator.update_interval.total_seconds(),
            "settings_cache_age_seconds": (
                round(monotonic() - coordinator._last_settings_update)
                if coordinator._last_settings_update
                else None
            ),
            "recent_samples_count": len(samples),
            "recent_samples_first": samples[0]["time"] if samples else None,
            "recent_samples_last": samples[-1]["time"] if samples else None,
            "authenticated_cookie_names": sorted(
                {
                    cookie.name
                    for cookie in coordinator.client.jar
                    if cookie.name in AUTH_COOKIE_NAMES
                }
            ),
            "security_token_available": coordinator.client._token is not None,
        },
    }
