"""Portal notification events for Fastweb Power Control."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FastwebConfigEntry
from .entity import FastwebEntity

PARALLEL_UPDATES = 0
# Types seen on the portal; the last two match the notification settings names.
NOTIFICATION_TYPES = (
    "contracted_power_limit_exceeded",
    "provider_disconnection",
    "monthly_energy_budget",
    "holiday_mode",
)
EVENT_OTHER = "other"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FastwebConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([FastwebNotificationEvent(entry.runtime_data, entry)])


class FastwebNotificationEvent(FastwebEntity, EventEntity):
    """Fires once for every notification that appears on the portal."""

    _attr_event_types = [*NOTIFICATION_TYPES, EVENT_OTHER]
    _attr_translation_key = "portal_notification"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "portal_notification")
        self._seen: set[str] | None = None
        self._remember(coordinator.data.get("notifications"))

    def _remember(self, notifications: list[dict] | None) -> list[dict]:
        """Record notification ids and return the ones not seen before."""
        if notifications is None:
            return []
        ids = {item["id"] for item in notifications}
        if self._seen is None:
            # The first list is only a baseline: old notifications are not events.
            self._seen = ids
            return []
        new = [item for item in notifications if item["id"] not in self._seen]
        self._seen |= ids
        return new

    @callback
    def _handle_coordinator_update(self) -> None:
        for item in self._remember((self.coordinator.data or {}).get("notifications")):
            event_type = item["type"] if item["type"] in NOTIFICATION_TYPES else EVENT_OTHER
            self._trigger_event(
                event_type,
                {
                    "notification_id": item["id"],
                    "notification_type": item["type"],
                    "title": item["title"],
                    "message": item["message"],
                    "created_at": item["created_at"],
                },
            )
            # Write each event, so automations see every notification of a batch.
            self.async_write_ha_state()
        super()._handle_coordinator_update()
