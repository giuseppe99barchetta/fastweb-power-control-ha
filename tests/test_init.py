"""Tests for setup, coordinator, entities and services."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.fastweb_power_control import coordinator as coordinator_module
from custom_components.fastweb_power_control.api import FastwebError, RecaptchaRequired
from custom_components.fastweb_power_control.const import CONF_COOKIE, DOMAIN
from custom_components.fastweb_power_control.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import NOTIFICATION_OLD

POWER = "sensor.fastweb_power_control_current_consumption"
PEAK = "sensor.fastweb_power_control_peak_power_today"
CONNECTIVITY = "binary_sensor.fastweb_power_control_plug_connectivity"
BUZZER = "switch.fastweb_power_control_power_limit_buzzer"
EVENT = "event.fastweb_power_control_portal_notification"
HOLIDAY_SWITCH = "switch.fastweb_power_control_holiday_mode_warning"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_setup_creates_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(POWER).state == "1500"
    assert hass.states.get(PEAK).state == "1500.0"
    assert hass.states.get("sensor.fastweb_power_control_contracted_power_usage").state == "50.0"
    assert hass.states.get(CONNECTIVITY).state == "on"
    assert hass.states.get(BUZZER).state == "off"
    assert hass.states.get("sensor.fastweb_power_control_last_update").state != STATE_UNAVAILABLE
    assert config_entry.data[CONF_COOKIE] == "FWB_RM=abc"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_history_sensors(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    last_day = hass.states.get("sensor.fastweb_power_control_consumption_last_day")
    assert last_day.state == "12.0"
    assert last_day.attributes["day"] == "2026-10-18"
    week = hass.states.get("sensor.fastweb_power_control_consumption_last_7_days")
    assert week.state == "21.0"
    assert week.attributes["previous_period"] == 18.5
    month = hass.states.get("sensor.fastweb_power_control_consumption_last_30_days")
    assert month.state == "380.0"
    assert month.attributes["previous_period"] == 510.0
    assert month.attributes["categories"] == {"fridge": 19.5}
    fridge = hass.states.get("sensor.fastweb_power_control_fridge_7_days")
    assert fridge.state == "1.5"
    assert fridge.attributes["last_day"] == 0.6
    # A category missing from the portal response is unavailable, not zero.
    oven = hass.states.get("sensor.fastweb_power_control_oven_7_days")
    assert oven.state == STATE_UNAVAILABLE


async def test_unique_id_migrated(hass: HomeAssistant, mock_client: MagicMock) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"username": " Old@User.it ", "password": "x"}
    )
    await _setup(hass, entry)
    assert entry.unique_id == "old@user.it"


async def test_recaptcha_creates_repair_issue(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.get_realtime.side_effect = RecaptchaRequired("captcha")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert ir.async_get(hass).async_get_issue(DOMAIN, "recaptcha_required")
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_stale_status_expires(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: clock[0])
    await _setup(hass, config_entry)
    assert hass.states.get(CONNECTIVITY).state == "on"

    mock_client.get_status.side_effect = FastwebError("status down")
    # Still within the expiry window: the last known value is kept.
    clock[0] += 120
    await _tick(hass, freezer, 30)
    assert hass.states.get(CONNECTIVITY).state == "on"
    # Past three status periods the cached value is dropped.
    clock[0] += 120
    await _tick(hass, freezer, 30)
    assert hass.states.get(CONNECTIVITY).state == STATE_UNAVAILABLE
    assert hass.states.get(POWER).state == "1500"


async def test_optional_refresh_skipped_after_slow_realtime(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([0.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0])
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: next(clock, 25.0))
    await _setup(hass, config_entry)
    mock_client.get_settings.assert_not_called()
    mock_client.get_status.assert_not_called()
    mock_client.get_history.assert_not_called()
    assert hass.states.get(POWER).state == "1500"


async def test_switch_writes_setting(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": BUZZER}, blocking=True
    )
    mock_client.update_led_settings.assert_called_once_with({"buzzer": True})
    assert hass.states.get(BUZZER).state == "on"


async def test_peak_power_tracks_maximum(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, config_entry)
    readings = iter([2500, 900])
    mock_client.get_realtime.side_effect = lambda *a: {
        "data": {"realtime": next(readings), "realtime_max": 3}
    }
    await _tick(hass, freezer, 30)
    assert hass.states.get(PEAK).state == "2500.0"
    await _tick(hass, freezer, 30)
    assert hass.states.get(PEAK).state == "2500.0"
    assert hass.states.get(POWER).state == "900"


async def test_notification_event(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: clock[0])
    await _setup(hass, config_entry)
    # Notifications already on the portal are only a baseline.
    assert hass.states.get(EVENT).state == "unknown"

    fired: list[dict] = []
    hass.bus.async_listen(
        "state_changed",
        lambda event: fired.append(event.data["new_state"].attributes)
        if event.data["entity_id"] == EVENT
        else None,
    )
    new = [
        {
            "id": "new-1",
            "type": "contracted_power_limit_exceeded",
            "title": "Contracted power exceeded",
            "message": "4.3 kW",
            "created_at": "2026-10-17T10:51:07Z",
            "read": False,
        },
        {
            "id": "new-2",
            "type": "brand_new_type",
            "title": "Something else",
            "message": "Unknown type",
            "created_at": "2026-10-18T10:00:00Z",
            "read": False,
        },
    ]
    mock_client.get_status.return_value = {
        "plug_status": "ONLINE",
        "plug_online": True,
        "notifications_unread": 2,
        "notifications": [NOTIFICATION_OLD, *new],
    }
    clock[0] += 61
    await _tick(hass, freezer, 30)
    events = [attrs for attrs in fired if "notification_id" in attrs]
    assert [attrs["notification_id"] for attrs in events] == ["new-1", "new-2"]
    assert events[0]["event_type"] == "contracted_power_limit_exceeded"
    assert events[0]["message"] == "4.3 kW"
    assert events[1]["event_type"] == "other"
    assert events[1]["notification_type"] == "brand_new_type"

    # The same notifications on the next poll do not fire again.
    fired.clear()
    clock[0] += 61
    await _tick(hass, freezer, 30)
    assert not [attrs for attrs in fired if "notification_id" in attrs]


async def test_set_holiday_period_service(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    await hass.services.async_call(
        DOMAIN,
        "set_holiday_period",
        {"start": "2026-08-01", "end": "2026-08-21"},
        blocking=True,
    )
    mock_client.update_notification_settings.assert_called_once_with(
        {"holiday_from": date(2026, 8, 1), "holiday_to": date(2026, 8, 21), "holiday_mode": True}
    )
    assert hass.states.get(HOLIDAY_SWITCH).state == "on"
    assert hass.states.get("date.fastweb_power_control_holiday_start").state == "2026-08-01"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_holiday_period",
            {"start": "2026-08-21", "end": "2026-08-01"},
            blocking=True,
        )


async def test_service_without_loaded_entry(hass: HomeAssistant) -> None:
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_holiday_period",
            {"start": "2026-08-01", "end": "2026-08-21"},
            blocking=True,
        )


async def test_diagnostics_redacts_secrets(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["config_entry"]["password"] == "**REDACTED**"
    assert result["config_entry"]["username"] == "**REDACTED**"
    assert result["config_entry"][CONF_COOKIE] == "**REDACTED**"
    assert result["runtime"]["persisted_cookie_names"] == ["FWB_RM"]
    assert "abc" not in str(result)
