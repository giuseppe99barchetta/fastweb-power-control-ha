"""Shared entities for Fastweb Power Control."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FastwebCoordinator
from .const import DOMAIN


class FastwebEntity(CoordinatorEntity[FastwebCoordinator]):
    """Base entity attached to the Power Control device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: FastwebCoordinator, entry: ConfigEntry, unique_key: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{unique_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Fastweb",
            model="Power Control",
            name="Fastweb Power Control",
        )


class FastwebSettingEntity(FastwebEntity):
    """Base entity backed by one portal setting."""

    def __init__(
        self,
        coordinator: FastwebCoordinator,
        entry: ConfigEntry,
        group: str,
        key: str,
    ) -> None:
        super().__init__(coordinator, entry, key)
        self.group = group
        self.key = key
        self._attr_translation_key = key

    @property
    def available(self) -> bool:
        return super().available and self.key in self.coordinator.settings.get(
            self.group, {}
        )

    @property
    def setting_value(self):
        return self.coordinator.settings.get(self.group, {}).get(self.key)
