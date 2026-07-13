"""Fastweb Power Control integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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

PLATFORMS = (
    Platform.BINARY_SENSOR,
    Platform.DATE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
)
SETTINGS_REFRESH_SECONDS = 600
STATUS_REFRESH_SECONDS = 60
GREEN_REFRESH_SECONDS = 900
LATEST_REFRESH_SECONDS = 300
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
        self.latest_samples: list[dict] = []
        self._status: dict = {}
        self._green: dict = {}
        self._last_settings_update = 0.0
        self._last_status_update = 0.0
        self._last_green_update = 0.0
        self._last_latest_update = 0.0

    async def _async_optional(self, label: str, method):
        """Refresh optional portal data without taking realtime power offline."""
        try:
            return await self.hass.async_add_executor_job(method)
        except InvalidAuth:
            raise
        except FastwebError as error:
            LOGGER.warning("Unable to refresh Fastweb %s: %s", label, error)
            return None

    async def _async_update_data(self) -> dict:
        try:
            started = monotonic()
            payload = await self.hass.async_add_executor_job(self.client.get_realtime)
            latency_ms = round((monotonic() - started) * 1000)
            now = monotonic()
            if (
                not self.settings
                or now - self._last_settings_update >= SETTINGS_REFRESH_SECONDS
            ):
                if settings := await self._async_optional(
                    "settings", self.client.get_settings
                ):
                    self.settings = settings
                    self._last_settings_update = now
            if not self._status or now - self._last_status_update >= STATUS_REFRESH_SECONDS:
                if status := await self._async_optional("status", self.client.get_status):
                    self._status = status
                    self._last_status_update = now
            if not self._green or now - self._last_green_update >= GREEN_REFRESH_SECONDS:
                if green := await self._async_optional(
                    "green energy data", self.client.get_green
                ):
                    self._green = green
                    self._last_green_update = now
            if (
                not self.latest_samples
                or now - self._last_latest_update >= LATEST_REFRESH_SECONDS
            ):
                if latest := await self._async_optional(
                    "recent consumption", self.client.get_latest
                ):
                    self.latest_samples = latest
                    self._last_latest_update = now
        except InvalidAuth as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except FastwebError as error:
            raise UpdateFailed(str(error)) from error

        data = {
            **payload["data"],
            **self._status,
            **self._green,
            "api_latency_ms": latency_ms,
            "last_update": datetime.now(UTC).isoformat(),
            "settings": self.settings,
        }
        maximum_w = max(0.0, float(data.get("realtime_max") or 0) * 1000)
        power_w = max(0.0, float(data["realtime"]))
        data["contracted_power"] = maximum_w / 1000
        if maximum_w:
            data["load_percentage"] = round(power_w / maximum_w * 100, 1)
            data["power_headroom"] = round(maximum_w - power_w)
        start = data.get("green_today_start")
        end = data.get("green_today_end")
        if start and end:
            current = datetime.now(UTC)
            data["green_active"] = (
                datetime.fromisoformat(start) <= current <= datetime.fromisoformat(end)
            )
        return data

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
