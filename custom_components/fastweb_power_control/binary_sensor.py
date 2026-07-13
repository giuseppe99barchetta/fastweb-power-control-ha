"""Binary sensors for Fastweb Power Control."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_WARNING_THRESHOLD,
    DEFAULT_WARNING_THRESHOLD,
    DOMAIN,
)
from .entity import FastwebEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            FastwebConnectivitySensor(coordinator, entry),
            FastwebStaleSensor(coordinator, entry),
            FastwebPowerWarningSensor(coordinator, entry),
            FastwebGreenActiveSensor(coordinator, entry),
        ]
    )


class FastwebConnectivitySensor(FastwebEntity, BinarySensorEntity):
    """Whether Fastweb reports the plug online."""

    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "connectivity")

    @property
    def available(self) -> bool:
        return super().available and "plug_online" in self.coordinator.data

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get("plug_online")


class FastwebStaleSensor(FastwebEntity, BinarySensorEntity):
    """Whether consumption updates are stale."""

    _attr_translation_key = "stale_data"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "stale_data")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return True
        last_update = self.coordinator.data.get("last_update")
        if not last_update:
            return True
        age = (datetime.now(UTC) - datetime.fromisoformat(last_update)).total_seconds()
        return age > self.coordinator.update_interval.total_seconds() * 2.5


class FastwebPowerWarningSensor(FastwebEntity, BinarySensorEntity):
    """Whether consumption is near the contracted power limit."""

    _attr_translation_key = "power_limit_warning"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "power_limit_warning")
        self.entry = entry

    @property
    def available(self) -> bool:
        return super().available and "load_percentage" in self.coordinator.data

    @property
    def is_on(self) -> bool:
        threshold = self.entry.options.get(
            CONF_WARNING_THRESHOLD, DEFAULT_WARNING_THRESHOLD
        )
        return self.coordinator.data["load_percentage"] >= threshold


class FastwebGreenActiveSensor(FastwebEntity, BinarySensorEntity):
    """Whether the current time is in Fastweb's green-energy window."""

    _attr_translation_key = "green_active"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "green_active")

    @property
    def available(self) -> bool:
        return super().available and "green_active" in self.coordinator.data

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get("green_active")
