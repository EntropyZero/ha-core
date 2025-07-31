"""Data loader to batch data coming from a source sensor."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_METHOD,
    CONF_NAME,
    CONF_STATE,
    CONF_UNIQUE_ID,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BATCH_METHODS,
    CONF_CHANGEPOINT_KEYS,
    CONF_CONDITION,
    CONF_DURATION,
    CONF_NUMSAMPLES_KEYS,
    CONF_SOURCE_SENSOR,
    CONF_TIMEDURATION_KEYS,
    CONF_UNIT_TIME,
    DEFAULT_NAME,
    DOMAIN,
    METHOD_CHANGEPOINT,
    METHOD_NUMSAMPLES,
    METHOD_TIMEDURATION,
)

UNITS: dict[str, str] = {
    METHOD_TIMEDURATION: UnitOfTime.HOURS,
    METHOD_NUMSAMPLES: "",
    METHOD_CHANGEPOINT: "",
}
ICON = "mdi:chart-line"

_LOGGER = logging.getLogger(__name__)

# SI Time prefixes
UNIT_TIME = {
    UnitOfTime.SECONDS: 1,
    UnitOfTime.MINUTES: 60,
    UnitOfTime.HOURS: 60 * 60,
    UnitOfTime.DAYS: 24 * 60 * 60,
}


def validate_method_keys[_T: dict[str, Any]](conf: _T) -> _T:
    """Ensure correct keys provided for the batch method selected."""

    if (
        sum(param in conf for param in CONF_NUMSAMPLES_KEYS) != 2
        and sum(param in conf for param in CONF_TIMEDURATION_KEYS) != 2
        and sum(param in conf for param in CONF_CHANGEPOINT_KEYS) != 1
    ):
        raise vol.Invalid(
            "You must provide the correct set of keys for the batch method and condition"
        )
    return conf


PLATFORM_SCHEMA = vol.All(
    SENSOR_PLATFORM_SCHEMA.extend(
        {
            vol.Required(CONF_DURATION): cv.time_period,
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
            vol.Required(CONF_SOURCE_SENSOR): cv.entity_id,
            vol.Required(CONF_STATE): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(CONF_UNIT_TIME, default=UnitOfTime.HOURS): vol.In(UNIT_TIME),
            vol.Optional(CONF_CONDITION, default=1): vol.Any(None, vol.Coerce(int)),
            vol.Required(CONF_METHOD, default=METHOD_CHANGEPOINT): vol.In(
                BATCH_METHODS
            ),
            vol.Optional(CONF_UNIQUE_ID): cv.string,
        }
    ),
    validate_method_keys,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Any,
) -> None:
    """Initialize config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AnomalyDetectorView(
                hass,
                coordinator,
                entry.title,
            )
        ]
    )


@callback
def async_device_info_fn(name: str) -> DeviceInfo:
    """Create device registry entry for client."""
    identifier = f"{name}"
    return DeviceInfo(
        identifiers={(DOMAIN, identifier)},
        name=name,
    )


class AnomalyDetectorView(CoordinatorEntity, SensorEntity):
    """The view for the anomaly detector."""

    _attr_available = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: Any,
        name: str,
    ) -> None:
        """Initialize the data loader sensor."""
        super().__init__(
            coordinator, context=name
        )  # for passing data from coordinator's async_update method to specific entity
        self._attr_available = False
        self._attr_device_info = async_device_info_fn(name)
        self._attr_unique_id = name
        self._attr_name = name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        data = self.coordinator.data

        self._attr_native_value = data  # for sensor entity
        self._attr_available = True
        self.async_write_ha_state()
