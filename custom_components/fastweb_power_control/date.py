"""Holiday dates for Fastweb Power Control."""

from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import FastwebSettingEntity

DATES = ("holiday_from", "holiday_to")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [FastwebHolidayDate(coordinator, entry, "notifications", key) for key in DATES]
    )


class FastwebHolidayDate(FastwebSettingEntity, DateEntity):
    """One boundary of the holiday notification period."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> date | None:
        value = self.setting_value
        return date.fromisoformat(value) if value else None

    async def async_set_value(self, value: date) -> None:
        await self.coordinator.async_set_setting(self.group, self.key, value)
