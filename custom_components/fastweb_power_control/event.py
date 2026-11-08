"""Portal notification events for Fastweb Power Control."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from homeassistant.components.event import EventEntity, EventExtraStoredData
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.start import async_at_started

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


def _when(value: str | None) -> datetime:
    """Parse a portal timestamp; unreadable values sort as the oldest."""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass
class _EventStoredData(EventExtraStoredData):
    """Last event plus the newest notification handled, to catch up after a restart."""

    last_created_at: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


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
        missed = self._remember((self.coordinator.data or {}).get("notifications"))
        # Automations attach their triggers late in startup; fire only after that.

        @callback
        def fire_missed(hass: HomeAssistant) -> None:
            self._fire(missed)

        if cancel := async_at_started(self.hass, fire_missed):
            self.async_on_remove(cancel)

    @property
    def extra_restore_state_data(self) -> _EventStoredData:
        last = super().extra_restore_state_data
        return _EventStoredData(
            last.last_event_type, last.last_event_attributes, self._last_created_at
        )

    def _remember(self, notifications: list[dict] | None) -> list[dict]:
        """Record notification ids and return the ones not seen before."""
        if notifications is None:
            return []
        ids = {item["id"] for item in notifications}
        previous = self._last_created_at
        known = [previous, *(item["created_at"] for item in notifications)]
        self._last_created_at = max(filter(None, known), key=_when, default=None)
        if self._seen is None:
            self._seen = ids
            if previous is None:
                # Nothing stored: the first list is only a baseline, not events.
                return []
            # After a restart, notifications newer than the last handled one are new.
            return [item for item in notifications if _when(item["created_at"]) > _when(previous)]
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
