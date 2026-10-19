"""Data coordinator for Fastweb Power Control."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial
import logging
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FastwebClient, FastwebError, InvalidAuth, RecaptchaRequired
from .const import CONF_COOKIE, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

SETTINGS_REFRESH_SECONDS = 600
STATUS_REFRESH_SECONDS = 60
LATEST_REFRESH_SECONDS = 300
# The portal publishes daily totals once a day; hourly polling is plenty.
HISTORY_REFRESH_SECONDS = 3600
# Cached optional data older than this many refresh periods is dropped, so the
# related entities become unavailable instead of reporting stale values.
CACHE_EXPIRY_FACTOR = 3
# Optional portal pages are skipped when realtime polling already took this long
# (for example after a full sign-in), keeping one cycle close to the interval.
OPTIONAL_BUDGET_SECONDS = 20
_OPTIONAL_REFRESHES = (
    # label, client method, cache attribute, timestamp attribute, interval
    ("settings", "get_settings", "settings", "_last_settings_update", SETTINGS_REFRESH_SECONDS),
    ("status", "get_status", "_status", "_last_status_update", STATUS_REFRESH_SECONDS),
    (
        "recent consumption",
        "get_latest",
        "latest_samples",
        "_last_latest_update",
        LATEST_REFRESH_SECONDS,
    ),
    (
        "consumption history",
        "get_history",
        "history",
        "_last_history_update",
        HISTORY_REFRESH_SECONDS,
    ),
)
_EXPIRING_CACHES = (
    # cache attribute, timestamp attribute, refresh interval
    ("_status", "_last_status_update", STATUS_REFRESH_SECONDS),
    ("settings", "_last_settings_update", SETTINGS_REFRESH_SECONDS),
    ("history", "_last_history_update", HISTORY_REFRESH_SECONDS),
)
RECAPTCHA_ISSUE_ID = "recaptcha_required"
LOGGER = logging.getLogger(__package__)

type FastwebConfigEntry = ConfigEntry[FastwebCoordinator]


class FastwebCoordinator(DataUpdateCoordinator[dict]):
    """Poll Fastweb and coordinate configuration writes."""

    config_entry: FastwebConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FastwebConfigEntry) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_SCAN_INTERVAL,
                    entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                )
            ),
        )
        self.client = FastwebClient(
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            entry.data.get(CONF_COOKIE, ""),
        )
        self.settings: dict = {}
        self.latest_samples: list[dict] = []
        self.history: dict = {}
        self._status: dict = {}
        self._last_history_update = 0.0
        self._last_settings_update = 0.0
        self._last_status_update = 0.0
        self._last_latest_update = 0.0

    @property
    def settings_age(self) -> float | None:
        """Seconds since the portal settings were last read."""
        if not self._last_settings_update:
            return None
        return monotonic() - self._last_settings_update

    def _store_authenticated_cookie(self) -> None:
        """Persist the renewable Fastweb cookies without exposing their values."""
        cookie = self.client.cookie_header
        if not cookie or cookie == self.config_entry.data.get(CONF_COOKIE, ""):
            return
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, CONF_COOKIE: cookie},
        )

    def _expire_cache(self, now: float) -> None:
        for attr, stamp, interval in _EXPIRING_CACHES:
            if getattr(self, attr) and now - getattr(self, stamp) > interval * CACHE_EXPIRY_FACTOR:
                LOGGER.debug("Dropping expired Fastweb cache %s", attr)
                setattr(self, attr, {})

    async def _async_optional(self, label: str, method):
        """Refresh optional portal data without taking realtime power offline."""
        try:
            return await self.hass.async_add_executor_job(method)
        except InvalidAuth:
            raise
        except FastwebError as error:
            LOGGER.warning("Unable to refresh Fastweb %s: %s", label, error)
            return None

    async def _async_refresh_optional(self, started: float) -> None:
        for label, method, attr, stamp, interval in _OPTIONAL_REFRESHES:
            now = monotonic()
            if now - started >= OPTIONAL_BUDGET_SECONDS:
                LOGGER.debug("Skipping Fastweb %s refresh: cycle time budget used", label)
                return
            if getattr(self, attr) and now - getattr(self, stamp) < interval:
                continue
            if result := await self._async_optional(
                label, getattr(self.client, method)
            ):
                setattr(self, attr, result)
                setattr(self, stamp, monotonic())

    async def _async_update_data(self) -> dict:
        try:
            started = monotonic()
            payload = await self.hass.async_add_executor_job(self.client.get_realtime)
            latency_ms = round((monotonic() - started) * 1000)
            await self._async_refresh_optional(started)
        except RecaptchaRequired as error:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                RECAPTCHA_ISSUE_ID,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=RECAPTCHA_ISSUE_ID,
            )
            raise ConfigEntryAuthFailed(str(error)) from error
        except InvalidAuth as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except FastwebError as error:
            raise UpdateFailed(str(error)) from error
        ir.async_delete_issue(self.hass, DOMAIN, RECAPTCHA_ISSUE_ID)
        self._expire_cache(monotonic())

        data = {
            **payload["data"],
            **self._status,
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
        self._store_authenticated_cookie()
        return data

    async def async_set_settings(self, group: str, changes: dict) -> None:
        """Write settings of one group and immediately publish the accepted state."""
        method = {
            "led": self.client.update_led_settings,
            "notifications": self.client.update_notification_settings,
        }.get(group)
        if method is None:
            raise HomeAssistantError(f"Unknown Fastweb settings group: {group}")
        try:
            updated = await self.hass.async_add_executor_job(partial(method, changes))
        except InvalidAuth as error:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(error)) from error
        except FastwebError as error:
            raise HomeAssistantError(str(error)) from error

        self.settings = {**self.settings, group: updated}
        self._last_settings_update = monotonic()
        self._store_authenticated_cookie()
        self.async_set_updated_data({**(self.data or {}), "settings": self.settings})

    async def async_set_setting(self, group: str, key: str, value: object) -> None:
        """Write one setting."""
        await self.async_set_settings(group, {key: value})
