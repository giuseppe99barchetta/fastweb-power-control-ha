"""Power sensor for Fastweb Power Control."""

from __future__ import annotations

from time import monotonic

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, trapezoid_kwh
from .entity import FastwebEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [FastwebPowerSensor(coordinator, entry), FastwebEnergySensor(coordinator, entry)]
    )


class FastwebPowerSensor(FastwebEntity, SensorEntity):
    """Current household power consumption."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "power"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "power")

    @property
    def native_value(self) -> int | float:
        return self.coordinator.data["realtime"]

    @property
    def extra_state_attributes(self) -> dict:
        return {
            key: self.coordinator.data.get(key)
            for key in ("realtimek", "realtime_max", "realtime_color")
        }


class FastwebEnergySensor(FastwebEntity, RestoreSensor):
    """Energy accumulated from the real-time power samples."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3
    _attr_translation_key = "energy_total"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "energy_total")
        self._energy = 0.0
        self._last_power: float | None = None
        self._last_sample: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (
            (last_data := await self.async_get_last_sensor_data()) is not None
            and last_data.native_value is not None
        ):
            try:
                self._energy = max(0.0, float(last_data.native_value))
            except (TypeError, ValueError):
                pass
        self._set_baseline()

    def _set_baseline(self) -> None:
        self._last_power = max(0.0, float(self.coordinator.data["realtime"]))
        self._last_sample = monotonic()

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.last_update_success:
            # ponytail: skip unknown gaps instead of inventing offline consumption.
            self._last_power = self._last_sample = None
        elif self._last_power is None or self._last_sample is None:
            self._set_baseline()
        else:
            now = monotonic()
            current_power = max(0.0, float(self.coordinator.data["realtime"]))
            self._energy += trapezoid_kwh(
                self._last_power, current_power, now - self._last_sample
            )
            self._last_power = current_power
            self._last_sample = now
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float:
        return round(self._energy, 6)
