"""Data loader to batch data coming from a source sensor."""

from __future__ import annotations

from abc import abstractmethod
from datetime import UTC, datetime, timedelta
import logging
from typing import Any, Final

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_METHOD,
    CONF_NAME,
    CONF_STATE,
    CONF_UNIQUE_ID,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    AddEntitiesCallback,
)
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DataLoaderConfigEntry
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
    PLATFORMS,
)
from .coordinator import DataLoaderUpdateCoordinator
from .DataLoader import DataLoader

UNITS: dict[str, str] = {
    METHOD_TIMEDURATION: UnitOfTime.HOURS,
    METHOD_NUMSAMPLES: "",
    METHOD_CHANGEPOINT: "",
}
ICON = "mdi:chart-line"

_LOGGER = logging.getLogger(__name__)

ATTR_SOURCE_ID: Final = "source"

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
    entry: DataLoaderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Initialize config entry."""

    coordinator = entry.runtime_data
    source_entity = entry.options[CONF_SOURCE_SENSOR]
    async_add_entities(
        [
            DataLoaderSensor(
                hass,
                coordinator,
                entry.title,
                entry.entry_id,
                source_entity,
            )
        ]
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the data loader sensor."""
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    batch_method: str = config[CONF_METHOD]
    count_condition: int | None = config[CONF_CONDITION]
    source_entity: str = config[CONF_SOURCE_SENSOR]
    entity_states: list[str] = config[CONF_STATE]
    # start: Template = Template("{{ now() }}")
    # end: Template | None = None
    duration: timedelta | None = config.get(CONF_DURATION)
    name: str | None = config.get(CONF_NAME)
    unique_id: str | None = config.get(CONF_UNIQUE_ID)

    history_stats = DataLoader(
        hass,
        source_entity,
        entity_states,
        duration,
        batch_method,
        count_condition,
    )
    if name is None:
        name = f"{source_entity} model"
    coordinator = DataLoaderUpdateCoordinator(hass, history_stats, None, name)
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        raise PlatformNotReady from coordinator.last_exception
    dataloader = DataLoaderSensor(
        hass,
        coordinator,
        name,
        source_entity,
        unique_id,
    )

    async_add_entities([dataloader])


class DataLoaderSensorBase(
    CoordinatorEntity[DataLoaderUpdateCoordinator], SensorEntity
):
    """Base class for a DataLoader sensor."""

    _attr_icon = ICON

    def __init__(
        self,
        coordinator: DataLoaderUpdateCoordinator,
        name: str,
    ) -> None:
        """Initialize the DataLoader sensor base class."""
        super().__init__(coordinator)
        self._attr_name = name

    async def async_added_to_hass(self) -> None:
        """Entity has been added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_setup_state_listener())

    def _handle_coordinator_update(self) -> None:
        """Set attrs from value and count."""
        self._process_update()
        super()._handle_coordinator_update()

    @callback
    @abstractmethod
    def _process_update(self) -> None:
        """Process an update from the coordinator."""


class DataLoaderSensor(DataLoaderSensorBase):
    """Representation of a data loader sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    # _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataLoaderUpdateCoordinator,
        name: str,
        source_entity_id: str,
        unique_id: str | None,
    ) -> None:
        """Initialize the data loader sensor."""
        super().__init__(coordinator, name)
        # self._attr_native_unit_of_measurement = UNITS[sensor_type]
        # self._type = sensor_type
        # self._attr_device_info = async_device_info_to_link_from_entity(
        #     hass,
        #     source_entity_id,
        # )
        self._attr_unique_id = unique_id
        self._sensor_source_id: str = source_entity_id
        self._attr_name = name if name is not None else f"{source_entity_id} model"
        self._attr_icon = "mdi:chart-histogram"
        self._last_data_load_time: datetime = datetime.now(tz=UTC)
        self._process_update()  # determines the attr native value of dataloader itself, which is a boolean

    def _derive_and_set_attributes_from_state(self, source_state: State) -> None:
        # If the source has no defined unit we cannot derive a unit
        # self._unit_of_measurement = None

        self._attr_device_class = None
        if self._attr_device_class:
            self._attr_icon = None  # Remove this sensors icon default and allow to fallback to the device class default
        else:
            self._attr_icon = "mdi:chart-histogram"

    @callback
    def _process_update(self) -> None:
        """Process an update from the coordinator and store in sensor native value."""
        state = (
            self.coordinator.data
        )  # setting native value of data loader based off the state of the coordinator
        # _LOGGER.debug("Printing state of coordinator: %s", state)
        if state is None or state.ready is False:
            self._attr_native_value = False
            return

        # if count condition is met, set native value to True
        # eventually set to False when the model receives the new data
        if state.ready is not None and state.ready:
            self._attr_native_value = True
            return
