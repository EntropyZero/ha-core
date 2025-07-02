"""Data loader to batch data coming from a source sensor."""

from __future__ import annotations

from abc import abstractmethod
from datetime import UTC, datetime, timedelta
import logging
from typing import Final

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_MAXIMUM,
    CONF_METHOD,
    CONF_NAME,
    CONF_STATE,
    CONF_UNIQUE_ID,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device import async_device_info_to_link_from_entity
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    AddEntitiesCallback,
)
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.template import Template
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DataLoaderConfigEntry
from .const import (
    BATCH_METHODS,
    CONF_DURATION,
    CONF_END,
    CONF_SOURCE_SENSOR,
    CONF_START,
    CONF_UNIT_TIME,
    DEFAULT_NAME,
    DOMAIN,
    METHOD_CHANGEPOINT,
    METHOD_NUMSAMPLES,
    METHOD_TIMEDURATION,
    PLATFORMS,
)
from .coordinator import DataLoaderUpdateCoordinator
from .data import DataLoaderStats

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

# def exactly_two_period_keys[_T: dict[str, Any]](conf: _T) -> _T:
#     """Ensure exactly 2 of CONF_PERIOD_KEYS are provided."""
#     if sum(param in conf for param in CONF_PERIOD_KEYS) != 2:
#         raise vol.Invalid(
#             "You must provide exactly 2 of the following: start, end, duration"
#         )
#     return conf

PLATFORM_SCHEMA = vol.All(
    SENSOR_PLATFORM_SCHEMA.extend(
        {
            vol.Required(CONF_DURATION): cv.time_period,
            vol.Optional(CONF_END): cv.template,
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
            vol.Required(CONF_SOURCE_SENSOR): cv.entity_id,
            vol.Required(CONF_STATE): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(CONF_START): cv.template,
            vol.Optional(CONF_UNIT_TIME, default=UnitOfTime.HOURS): vol.In(UNIT_TIME),
            vol.Optional(CONF_MAXIMUM, default=1): vol.Any(None, vol.Coerce(int)),
            vol.Required(CONF_METHOD, default=METHOD_CHANGEPOINT): vol.In(
                BATCH_METHODS
            ),
            vol.Optional(CONF_UNIQUE_ID): cv.string,
        }
    ),
    # exactly_two_period_keys,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DataLoaderConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Initialize config entry."""

    coordinator = entry.runtime_data
    source_entity: str = entry.options[CONF_SOURCE_SENSOR]
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

    batch_method = config[CONF_METHOD]
    count_condition = config[CONF_MAXIMUM]
    source_entity: str = config[CONF_SOURCE_SENSOR]
    entity_states: list[str] = config[CONF_STATE]
    start: Template | None = config.get(CONF_START)
    end: Template | None = config.get(CONF_END)
    duration: timedelta | None = config.get(CONF_DURATION)
    name: str = config[CONF_NAME]
    unique_id: str | None = config.get(CONF_UNIQUE_ID)

    history_stats = DataLoaderStats(
        hass,
        source_entity,
        entity_states,
        start,
        end,
        duration,
        batch_method,
        count_condition,
    )
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
        self._attr_device_info = async_device_info_to_link_from_entity(
            hass,
            source_entity_id,
        )
        self._attr_unique_id = unique_id
        self._sensor_source_id: str = source_entity_id
        self._attr_name = (
            name if name is not None else f"{source_entity_id} data loader"
        )
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
        if state is None or state.seconds_matched is None:
            self._attr_native_value = None
            return

        # if count condition is met, set native value to True
        # eventually set to False when the model receives the new data
        if state.ready is not None and state.ready:
            self._attr_native_value = True
            return

    # def _update_data_loader_state(self, send_batch: bool) -> None:
    #     if isinstance(self._state, bool):
    #         self._state = send_batch
    #     else:
    #         self._state = False
    #     _LOGGER.debug("send batch = %s, new state = %s", send_batch, self._state)

    # async def async_added_to_hass(self) -> None:
    #     """Handle entity which will be added."""
    #     await super().async_added_to_hass()

    # handle_state_change = self._check_batch_on_state_change_callback
    # handle_state_report = self._check_batch_on_state_report_callback

    # if (
    #     state := self.hass.states.get(self._source_entity)
    # ) and state.state != STATE_UNAVAILABLE:
    #     self._derive_and_set_attributes_from_state(state)

    # self.async_on_remove(
    #     async_track_state_change_event(
    #         self.hass,
    #         self._sensor_source_id,
    #         handle_state_change,
    #     )
    # )
    # self.async_on_remove(
    #     async_track_state_report_event(
    #         self.hass,
    #         self._sensor_source_id,
    #         handle_state_report,
    #     )
    # )

    # @callback
    # def _check_batch_on_state_change_callback(
    #     self, event: Event[EventStateChangedData]
    # ) -> None:
    #     """Handle sensor state change."""
    #     return self._check_batch_on_state_change(
    #         None, event.data["old_state"], event.data["new_state"]
    #     )

    # @callback
    # def _check_batch_on_state_report_callback(
    #     self, event: Event[EventStateReportedData]
    # ) -> None:
    #     """Handle sensor state report."""
    #     return self._check_batch_on_state_change(
    #         event.data["old_last_reported"], None, event.data["new_state"]
    #     )

    # def _check_batch_on_state_change(
    #     self,
    #     old_last_reported: datetime | None,
    #     old_state: State | None,
    #     new_state: State | None,
    # ) -> None:
    #     if new_state is None:
    #         return

    #     if new_state.state == STATE_UNAVAILABLE:
    #         self._attr_available = False
    #         self.async_write_ha_state()
    #         return

    #     if old_state:
    #         # state has changed, we recover old_state from the event
    #         # old_state_state = old_state.state
    #         old_last_reported = old_state.last_reported
    #     # else:
    #     # event state reported without any state change
    #     # old_state_state = new_state.state

    #     self._attr_available = True
    #     self._derive_and_set_attributes_from_state(new_state)

    #     if old_last_reported is None and old_state is None:
    #         self.async_write_ha_state()
    #         return

    #     if TYPE_CHECKING:
    #         assert old_last_reported is not None
    #     elapsed_seconds = Decimal(
    #         (new_state.last_reported - old_last_reported).total_seconds()
    #         if self._last_data_load_trigger == _DataLoadTrigger.StateEvent
    #         else (new_state.last_reported - self._last_data_load_time).total_seconds()
    #     )

    #     send_batch = self._method.check_batch_ready(elapsed_seconds)

    #     self._update_data_loader_state(send_batch)
    #     self.async_write_ha_state()

    # @property
    # def native_value(self) -> bool | None:
    #     """Return the state of the data loader \"sensor\"."""

    #     return self._state
