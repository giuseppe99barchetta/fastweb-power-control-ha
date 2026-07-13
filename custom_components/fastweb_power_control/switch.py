"""Portal switches for Fastweb Power Control."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import FastwebSettingEntity

SWITCHES = (
    ("led", "led_all"),
    ("led", "led_meter"),
    ("led", "led_internet"),
    ("led", "buzzer"),
    ("notifications", "power_limit"),
    ("notifications", "provider_disconnection"),
    ("notifications", "monthly_budget"),
    ("notifications", "holiday_mode"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [FastwebSettingSwitch(coordinator, entry, group, key) for group, key in SWITCHES]
    )


class FastwebSettingSwitch(FastwebSettingEntity, SwitchEntity):
    """A writable boolean setting from the Fastweb portal."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        return bool(self.setting_value)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_setting(self.group, self.key, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_setting(self.group, self.key, False)
