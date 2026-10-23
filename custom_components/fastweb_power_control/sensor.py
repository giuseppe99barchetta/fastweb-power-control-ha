"""Sensors for Fastweb Power Control."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import trapezoid_kwh
from .coordinator import FastwebConfigEntry
from .entity import FastwebEntity

MAX_SAMPLE_GAP_SECONDS = 600
PARALLEL_UPDATES = 0
# Appliance categories estimated by the portal from the consumption profile.
APPLIANCE_CATEGORIES = (
    "air_conditioner",
    "dishwasher",
    "fridge",
    "oven",
    "washing_machine",
    "small_appliances",
    "consumer_electronics_illumination",
    "standby",
    "other",
)

SENSORS = (
    SensorEntityDescription(
        key="contracted_power",
        translation_key="contracted_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
    ),
    SensorEntityDescription(
        key="load_percentage",
        translation_key="load_percentage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="power_headroom",
        translation_key="power_headroom",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="notifications_unread",
        translation_key="notifications_unread",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="api_latency_ms",
        translation_key="api_latency",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FastwebConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            FastwebPowerSensor(coordinator, entry),
            FastwebEnergySensor(coordinator, entry),
            FastwebPeakPowerSensor(coordinator, entry),
            FastwebHistorySensor(coordinator, entry, "energy_last_day"),
            FastwebHistorySensor(coordinator, entry, "energy_last_7_days"),
            FastwebHistorySensor(coordinator, entry, "energy_last_30_days"),
        ]
        + [FastwebDataSensor(coordinator, entry, description) for description in SENSORS]
        + [
            FastwebHistorySensor(coordinator, entry, f"appliance_{category}", category)
            for category in APPLIANCE_CATEGORIES
        ]
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


class FastwebDataSensor(FastwebEntity, SensorEntity):
    """One value returned or calculated by the coordinator."""

    def __init__(
        self, coordinator, entry: ConfigEntry, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        value = self.coordinator.data.get(self.entity_description.key)
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP and value:
            return datetime.fromisoformat(value)
        return value


class FastwebEnergySensor(FastwebEntity, RestoreSensor):
    """Energy accumulated from Fastweb's timestamped recent samples."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3
    _attr_translation_key = "energy_total"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "energy_total")
        self._energy = 0.0
        self._last_power: float | None = None
        self._last_sample: datetime | None = None

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
        if last_state := await self.async_get_last_state():
            try:
                self._last_sample = datetime.fromisoformat(
                    last_state.attributes["last_sample"]
                )
                self._last_power = max(
                    0.0, float(last_state.attributes["last_power"])
                )
            except (KeyError, TypeError, ValueError):
                pass
        if self._last_sample is None and self.coordinator.latest_samples:
            latest = self.coordinator.latest_samples[-1]
            self._last_sample = datetime.fromisoformat(latest["time"])
            self._last_power = float(latest["power"])
        else:
            self._process_samples()

    def _process_samples(self) -> None:
        for sample in self.coordinator.latest_samples:
            timestamp = datetime.fromisoformat(sample["time"])
            power = max(0.0, float(sample["power"]))
            if self._last_sample is None or self._last_power is None:
                self._last_sample, self._last_power = timestamp, power
                continue
            elapsed = (timestamp - self._last_sample).total_seconds()
            if elapsed <= 0:
                continue
            if elapsed <= MAX_SAMPLE_GAP_SECONDS:
                self._energy += trapezoid_kwh(self._last_power, power, elapsed)
            # ponytail: gaps over ten minutes reset the baseline instead of inventing data.
            self._last_sample, self._last_power = timestamp, power

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.last_update_success:
            self._process_samples()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float:
        return round(self._energy, 6)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "last_sample": self._last_sample.isoformat() if self._last_sample else None,
            "last_power": self._last_power,
        }


class FastwebPeakPowerSensor(FastwebEntity, RestoreSensor):
    """Highest realtime power read since local midnight."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "peak_power_today"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "peak_power_today")
        self._peak: float | None = None
        self._peak_time: datetime | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        last_data = await self.async_get_last_sensor_data()
        if last_state and last_data and last_data.native_value is not None:
            try:
                peak_time = datetime.fromisoformat(last_state.attributes["peak_time"])
                peak = float(last_data.native_value)
            except (KeyError, TypeError, ValueError):
                pass
            else:
                if dt_util.as_local(peak_time).date() == dt_util.now().date():
                    self._peak, self._peak_time = peak, peak_time
        self._update_peak()

    def _update_peak(self) -> None:
        now = dt_util.now()
        if self._peak_time and dt_util.as_local(self._peak_time).date() != now.date():
            self._peak = self._peak_time = None
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return
        power = max(0.0, float(self.coordinator.data["realtime"]))
        if self._peak is None or power > self._peak:
            self._peak, self._peak_time = power, now

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_peak()
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float | None:
        return self._peak

    @property
    def extra_state_attributes(self) -> dict:
        return {"peak_time": self._peak_time.isoformat() if self._peak_time else None}


class FastwebHistorySensor(FastwebEntity, SensorEntity):
    """Consumption reported by the portal for the last seven complete days."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(
        self, coordinator, entry: ConfigEntry, key: str, category: str | None = None
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key
        self.key = key
        self.category = category

    @property
    def native_value(self) -> float | None:
        history = self.coordinator.history
        if not history:
            return None
        if self.category:
            return history["categories"].get(self.category)
        if self.key == "energy_last_day":
            return history["days"][-1]["energy"]
        if self.key == "energy_last_30_days":
            month = history.get("month")
            return month["period_energy"] if month else None
        return history["period_energy"]

    @property
    def extra_state_attributes(self) -> dict | None:
        history = self.coordinator.history
        if not history:
            return None
        if self.category:
            return {"last_day": history["last_day_categories"].get(self.category)}
        if self.key == "energy_last_day":
            return {
                "day": history["days"][-1]["day"],
                "categories": history["last_day_categories"],
            }
        if self.key == "energy_last_30_days":
            month = history.get("month") or {}
            return {
                "previous_period": month.get("previous_period_energy"),
                "categories": month.get("categories"),
                "days": month.get("days"),
            }
        return {
            "previous_period": history["previous_period_energy"],
            "days": history["days"],
        }
