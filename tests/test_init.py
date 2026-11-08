"""Tests for setup, coordinator, entities and services."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.fastweb_power_control import coordinator as coordinator_module
from custom_components.fastweb_power_control.api import (
    FastwebError,
    InvalidAuth,
    RecaptchaRequired,
)
from custom_components.fastweb_power_control.const import CONF_COOKIE, DOMAIN
from custom_components.fastweb_power_control.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import NOTIFICATION_OLD, USERNAME

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
    last_update = hass.states.get("sensor.fastweb_power_control_last_update").state
    assert datetime.fromisoformat(last_update).tzinfo is not None
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
    # A category missing from the portal response has an unknown value.
    oven = hass.states.get("sensor.fastweb_power_control_oven_7_days")
    assert oven.state == STATE_UNKNOWN


async def test_missing_sensor_data_is_unknown(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.get_status.return_value = {}
    mock_client.get_history.return_value = {}
    await _setup(hass, config_entry)

    for entity_id in (
        "sensor.fastweb_power_control_unread_notifications",
        "sensor.fastweb_power_control_consumption_last_day",
        "sensor.fastweb_power_control_consumption_last_7_days",
        "sensor.fastweb_power_control_consumption_last_30_days",
        "sensor.fastweb_power_control_fridge_7_days",
    ):
        assert hass.states.get(entity_id).state == STATE_UNKNOWN


async def test_missing_monthly_history_is_unknown(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.get_history.return_value = {
        **mock_client.get_history.return_value,
        "month": None,
    }
    await _setup(hass, config_entry)

    assert hass.states.get("sensor.fastweb_power_control_consumption_last_30_days").state == (
        STATE_UNKNOWN
    )
    assert hass.states.get("sensor.fastweb_power_control_consumption_last_7_days").state == "21.0"


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
    clock = iter([0.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: next(clock, 100.0))
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


async def test_unexpected_optional_error_keeps_realtime(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.get_settings.side_effect = ValueError("bad threshold")
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(POWER).state == "1500"


async def test_failed_optional_refresh_is_not_retried_every_cycle(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: clock[0])
    mock_client.get_settings.side_effect = FastwebError("settings down")
    await _setup(hass, config_entry)
    assert mock_client.get_settings.call_count == 1

    clock[0] += 30
    await _tick(hass, freezer, 30)
    assert mock_client.get_settings.call_count == 1
    clock[0] += 31
    await _tick(hass, freezer, 30)
    assert mock_client.get_settings.call_count == 2


async def test_cookie_is_read_outside_the_event_loop(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    loop_thread = threading.get_ident()
    readers: list[int] = []

    def read_cookie() -> str:
        readers.append(threading.get_ident())
        return "FWB_RM=abc"

    type(mock_client).cookie_header = PropertyMock(side_effect=read_cookie)
    await _setup(hass, config_entry)
    assert readers
    assert loop_thread not in readers


STALE = "binary_sensor.fastweb_power_control_stale_consumption_data"
ENERGY = "sensor.fastweb_power_control_cumulative_consumption"


async def test_stale_data_follows_portal_sample_age(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: clock[0])
    mock_client.get_latest.return_value = [
        {"time": datetime.now(UTC).isoformat(), "power": 1000.0}
    ]
    await _setup(hass, config_entry)
    assert hass.states.get(STALE).state == "off"

    # The portal keeps answering with the same sample while polling succeeds.
    clock[0] += 301
    await _tick(hass, freezer, 2000)
    assert hass.states.get(POWER).state == "1500"
    assert hass.states.get(STALE).state == "on"


async def test_energy_baseline_survives_unavailable_shutdown(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(ENERGY, STATE_UNAVAILABLE),
                {
                    "native_value": 5.0,
                    "native_unit_of_measurement": "kWh",
                    "last_sample": "2026-07-13T09:59:00+02:00",
                    "last_power": 1000.0,
                },
            )
        ],
    )
    await _setup(hass, config_entry)
    # 09:59 -> 10:00 -> 10:01 at 1 kW: two minutes on top of the restored total.
    assert float(hass.states.get(ENERGY).state) == pytest.approx(5.033333, abs=1e-6)


async def test_energy_restores_from_old_state_attributes(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(
                    ENERGY,
                    "5.0",
                    {"last_sample": "2026-07-13T09:59:00+02:00", "last_power": 1000.0},
                ),
                {"native_value": 5.0, "native_unit_of_measurement": "kWh"},
            )
        ],
    )
    await _setup(hass, config_entry)
    assert float(hass.states.get(ENERGY).state) == pytest.approx(5.033333, abs=1e-6)


async def test_notifications_arriving_while_offline_fire_after_restart(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_restore_cache_with_extra_data(
        hass,
        [(State(EVENT, STATE_UNKNOWN), {"last_created_at": NOTIFICATION_OLD["created_at"]})],
    )
    missed = {
        "id": "missed-1",
        "type": "provider_disconnection",
        "title": "Supply interruption",
        "message": "While Home Assistant was off",
        "created_at": "2026-07-02T08:00:00Z",
        "read": False,
    }
    mock_client.get_status.return_value = {
        **mock_client.get_status.return_value,
        "notifications": [NOTIFICATION_OLD, missed],
    }
    await _setup(hass, config_entry)
    attributes = hass.states.get(EVENT).attributes
    assert attributes["notification_id"] == "missed-1"


async def test_known_notifications_are_not_replayed_after_restart(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_restore_cache_with_extra_data(
        hass,
        [(State(EVENT, STATE_UNKNOWN), {"last_created_at": NOTIFICATION_OLD["created_at"]})],
    )
    await _setup(hass, config_entry)
    assert hass.states.get(EVENT).state == STATE_UNKNOWN


async def test_recaptcha_issue_removed_with_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.get_realtime.side_effect = RecaptchaRequired("captcha")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "recaptcha_required")

    await hass.config_entries.async_remove(config_entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "recaptcha_required") is None


async def test_diagnostics_redacts_personal_portal_data(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.jar = [SimpleNamespace(name="FWB_RM", domain="fastweb.it")]
    await _setup(hass, config_entry)
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    text = str(result)
    for private in ("secret", USERNAME, NOTIFICATION_OLD["message"], NOTIFICATION_OLD["title"]):
        assert private not in text
    assert result["runtime"]["authenticated_cookies"] == ["FWB_RM@fastweb.it"]


async def test_device_is_a_service(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    assert device.entry_type is dr.DeviceEntryType.SERVICE


async def test_number_and_date_write_settings(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    threshold = "number.fastweb_power_control_monthly_energy_threshold"
    assert float(hass.states.get(threshold).state) == 250.0
    await hass.services.async_call(
        "number", "set_value", {"entity_id": threshold, "value": 300}, blocking=True
    )
    mock_client.update_notification_settings.assert_called_with({"monthly_threshold": 300.0})
    assert float(hass.states.get(threshold).state) == 300.0

    start = "date.fastweb_power_control_holiday_start"
    assert hass.states.get(start).state == STATE_UNKNOWN
    await hass.services.async_call(
        "date", "set_value", {"entity_id": start, "date": "2026-08-01"}, blocking=True
    )
    mock_client.update_notification_settings.assert_called_with({"holiday_from": date(2026, 8, 1)})
    assert hass.states.get(start).state == "2026-08-01"


async def test_led_switch_writes_group_setting(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    all_leds = "switch.fastweb_power_control_all_leds"
    assert hass.states.get(all_leds).state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": all_leds}, blocking=True
    )
    mock_client.update_led_settings.assert_called_with({"led_all": False})
    assert hass.states.get(all_leds).state == "off"


async def test_failed_write_raises_and_keeps_state(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    mock_client.update_led_settings.side_effect = FastwebError("portal said no")
    with pytest.raises(HomeAssistantError, match="portal said no"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": BUZZER}, blocking=True
        )
    assert hass.states.get(BUZZER).state == "off"


async def test_write_with_rejected_login_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    mock_client.update_led_settings.side_effect = InvalidAuth("bad credentials")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": BUZZER}, blocking=True
        )
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_event_keeps_last_event_when_state_is_saved(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: clock[0])
    await _setup(hass, config_entry)
    new = {
        "id": "new-1",
        "type": "provider_disconnection",
        "title": "T",
        "message": "M",
        "created_at": "2026-10-17T10:51:07.5+00:00",
        "read": False,
    }
    mock_client.get_status.return_value = {
        **mock_client.get_status.return_value,
        "notifications": [NOTIFICATION_OLD, new],
    }
    clock[0] += 61
    await _tick(hass, freezer, 30)

    saved = hass.data["event"].get_entity(EVENT).extra_restore_state_data.as_dict()
    # The entity's own last event survives next to the catch-up marker.
    assert saved["last_event_type"] == "provider_disconnection"
    assert saved["last_event_attributes"]["notification_id"] == "new-1"
    assert saved["last_created_at"] == new["created_at"]
