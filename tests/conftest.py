"""Shared fixtures for Fastweb Power Control tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fastweb_power_control.const import CONF_SCAN_INTERVAL, DOMAIN

USERNAME = "User@Example.it"
REALTIME = {
    "errorCode": 0,
    "data": {
        "realtime": 1500,
        "realtimek": "1,5",
        "realtime_max": 3,
        "realtime_color": "green",
    },
}
NOTIFICATION_OLD = {
    "id": "old-1",
    "type": "provider_disconnection",
    "title": "Supply interruption",
    "message": "Old notification",
    "created_at": "2026-07-01T10:00:00Z",
    "read": True,
}
STATUS = {
    "plug_status": "ONLINE",
    "plug_online": True,
    "notifications_unread": 1,
    "notifications": [NOTIFICATION_OLD],
}
SETTINGS = {
    "led": {"led_all": True, "led_meter": True, "led_internet": True, "buzzer": False},
    "notifications": {
        "power_limit": True,
        "provider_disconnection": False,
        "monthly_budget": True,
        "holiday_mode": False,
        "monthly_threshold": 250.0,
        "holiday_from": None,
        "holiday_to": None,
    },
}
HISTORY = {
    "period_energy": 21.0,
    "previous_period_energy": 18.5,
    "days": [{"day": "2026-10-17", "energy": 9.0}, {"day": "2026-10-18", "energy": 12.0}],
    "categories": {"fridge": 1.5, "washing_machine": 2.25, "standby": 7.0},
    "last_day_categories": {"fridge": 0.6, "washing_machine": 1.8, "standby": 5.0},
    "month": {
        "period_energy": 380.0,
        "previous_period_energy": 510.0,
        "days": [{"day": "2026-10-18", "energy": 12.0}],
        "categories": {"fridge": 19.5},
        "last_day_categories": {"fridge": 0.6},
    },
}
LATEST = [
    {"time": "2026-07-13T10:00:00+02:00", "power": 1000.0},
    {"time": "2026-07-13T10:01:00+02:00", "power": 1000.0},
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the integration from custom_components."""
    return


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Fastweb Power Control",
        unique_id=USERNAME.lower(),
        data={"username": USERNAME, "password": "secret", CONF_SCAN_INTERVAL: 30},
    )


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Replace the network client used by the coordinator."""
    with patch(
        "custom_components.fastweb_power_control.coordinator.FastwebClient",
        autospec=True,
    ) as client_class:
        client = client_class.return_value
        client.get_realtime.side_effect = lambda *a: {
            **REALTIME,
            "data": dict(REALTIME["data"]),
        }
        client.get_status.return_value = dict(STATUS)
        client.get_settings.return_value = {
            group: dict(values) for group, values in SETTINGS.items()
        }
        client.get_latest.return_value = list(LATEST)
        client.get_history.return_value = dict(HISTORY)
        client.cookie_header = "FWB_RM=abc"
        client.jar = []
        client._token = "token"
        client.update_notification_settings.side_effect = lambda changes: {
            **SETTINGS["notifications"],
            **{
                key: value.isoformat() if hasattr(value, "isoformat") else value
                for key, value in changes.items()
            },
        }
        client.update_led_settings.side_effect = lambda changes: {
            **SETTINGS["led"],
            **changes,
        }
        yield client
