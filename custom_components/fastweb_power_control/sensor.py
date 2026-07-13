"""Power sensor for Fastweb Power Control."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FastwebCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([FastwebPowerSensor(hass.data[DOMAIN][entry.entry_id], entry)])


class FastwebPowerSensor(CoordinatorEntity[FastwebCoordinator], SensorEntity):
    """Current household power consumption."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_translation_key = "power"

    def __init__(self, coordinator: FastwebCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Fastweb",
            model="Power Control",
            name="Fastweb Power Control",
        )

    @property
    def native_value(self) -> int | float:
        return self.coordinator.data["realtime"]

    @property
    def extra_state_attributes(self) -> dict:
        return {
            key: self.coordinator.data.get(key)
            for key in ("realtimek", "realtime_max", "realtime_color")
        }
