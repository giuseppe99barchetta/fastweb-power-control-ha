"""Numeric settings for Fastweb Power Control."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import FastwebSettingEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [
            FastwebMonthlyThreshold(
                hass.data[DOMAIN][entry.entry_id], entry, "notifications", "monthly_threshold"
            )
        ]
    )


class FastwebMonthlyThreshold(FastwebSettingEntity, NumberEntity):
    """Monthly energy notification threshold."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 100000
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self) -> float | None:
        value = self.setting_value
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_setting(self.group, self.key, value)
