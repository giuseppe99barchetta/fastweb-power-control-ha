"""Diagnostics for Fastweb Power Control."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import AUTH_COOKIE_NAMES
from .const import CONF_COOKIE
from .coordinator import FastwebConfigEntry

TO_REDACT = {CONF_COOKIE, CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FastwebConfigEntry
) -> dict:
    coordinator = entry.runtime_data
    samples = coordinator.latest_samples
    settings_age = coordinator.settings_age
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "data": coordinator.data,
        "runtime": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": coordinator.update_interval.total_seconds(),
            "settings_cache_age_seconds": (
                round(settings_age) if settings_age is not None else None
            ),
            "recent_samples_count": len(samples),
            "recent_samples_first": samples[0]["time"] if samples else None,
            "recent_samples_last": samples[-1]["time"] if samples else None,
            # Names and domains only: shows which host issued each session cookie.
            "authenticated_cookies": sorted(
                f"{cookie.name}@{cookie.domain}"
                for cookie in coordinator.client.jar
                if cookie.name in AUTH_COOKIE_NAMES
            ),
            "persisted_cookie_names": sorted(
                part.split("=", 1)[0]
                for part in coordinator.client.cookie_header.split("; ")
                if part
            ),
            "security_token_available": coordinator.client._token is not None,
        },
    }
