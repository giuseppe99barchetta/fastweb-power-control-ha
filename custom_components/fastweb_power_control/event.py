"""Portal notification events for Fastweb Power Control."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData

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


@dataclass
class _SeenNotifications(ExtraStoredData):
    """Newest notification already handled, to catch up after a restart."""

    last_created_at: str | None

    def as_dict(self) -> dict:
        return {"last_created_at": self.last_created_at}


class FastwebNotificationEvent(FastwebEntity, EventEntity):
    """Fires once for every notification that appears on the portal."""

    _attr_event_types = [*NOTIFICATION_TYPES, EVENT_OTHER]
    _attr_translation_key = "portal_notification"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "portal_notification")
        self._seen: set[str] | None = None
        self._last_created_at: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if extra := await self.async_get_last_extra_data():
            self._last_created_at = extra.as_dict().get("last_created_at")
        self._fire(self._remember((self.coordinator.data or {}).get("notifications")))

    @property
    def extra_restore_state_data(self) -> _SeenNotifications:
        return _SeenNotifications(self._last_created_at)

    def _remember(self, notifications: list[dict] | None) -> list[dict]:
        """Record notification ids and return the ones not seen before."""
        if notifications is None:
            return []
        ids = {item["id"] for item in notifications}
        previous = self._last_created_at
        self._last_created_at = max(
            (item["created_at"] for item in notifications),
            default=previous,
            key=lambda value: value or "",
        )
        if self._seen is None:
            self._seen = ids
            if previous is None:
                # Nothing stored: the first list is only a baseline, not events.
                return []
            # After a restart, notifications newer than the last handled one are new.
            return [item for item in notifications if item["created_at"] > previous]
        new = [item for item in notifications if item["id"] not in self._seen]
        self._seen |= ids
        return new

    def _fire(self, notifications: list[dict]) -> None:
        for item in notifications:
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

    @callback
    def _handle_coordinator_update(self) -> None:
        self._fire(self._remember((self.coordinator.data or {}).get("notifications")))
        super()._handle_coordinator_update()
