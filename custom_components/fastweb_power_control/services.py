"""Services for Fastweb Power Control."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN

SERVICE_SET_HOLIDAY_PERIOD = "set_holiday_period"
ATTR_START = "start"
ATTR_END = "end"
ATTR_ENABLE = "enable"

SET_HOLIDAY_PERIOD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_START): cv.date,
        vol.Required(ATTR_END): cv.date,
        vol.Optional(ATTR_ENABLE, default=True): cv.boolean,
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration services once."""

    async def set_holiday_period(call: ServiceCall) -> None:
        start, end = call.data[ATTR_START], call.data[ATTR_END]
        if start > end:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_holiday_period"
            )
        if not (entries := hass.config_entries.async_loaded_entries(DOMAIN)):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_loaded"
            )
        # Dates and the switch are written together so the portal never sees
        # an intermediate, invalid range.
        await entries[0].runtime_data.async_set_settings(
            "notifications",
            {"holiday_from": start, "holiday_to": end, "holiday_mode": call.data[ATTR_ENABLE]},
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_HOLIDAY_PERIOD,
        set_holiday_period,
        schema=SET_HOLIDAY_PERIOD_SCHEMA,
    )
