"""Data loader to batch data coming from a source sensor."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
import logging
from typing import TYPE_CHECKING, Final

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_MAXIMUM,
    CONF_METHOD,
    CONF_NAME,
    CONF_UNIQUE_ID,
    STATE_UNAVAILABLE,
    UnitOfTime,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    EventStateReportedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.device import async_device_info_to_link_from_entity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    AddEntitiesCallback,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_state_report_event,
)
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    BATCH_METHODS,
    CONF_MAX_SUB_INTERVAL,
    CONF_SOURCE_SENSOR,
    CONF_UNIT_TIME,
    METHOD_CHANGEPOINT,
    METHOD_NUMSAMPLES,
    METHOD_TIMEDURATION,
)

_LOGGER = logging.getLogger(__name__)

ATTR_SOURCE_ID: Final = "source"

# SI Time prefixes
UNIT_TIME = {
    UnitOfTime.SECONDS: 1,
    UnitOfTime.MINUTES: 60,
    UnitOfTime.HOURS: 60 * 60,
    UnitOfTime.DAYS: 24 * 60 * 60,
}

PLATFORM_SCHEMA = vol.All(
    SENSOR_PLATFORM_SCHEMA.extend(
        {
            vol.Optional(CONF_NAME): cv.string,
            vol.Optional(CONF_UNIQUE_ID): cv.string,
            vol.Required(CONF_SOURCE_SENSOR): cv.entity_id,
            vol.Optional(CONF_UNIT_TIME, default=UnitOfTime.HOURS): vol.In(UNIT_TIME),
            vol.Optional(CONF_MAX_SUB_INTERVAL): cv.positive_time_period,
            vol.Required(CONF_METHOD, default=METHOD_CHANGEPOINT): vol.In(
                BATCH_METHODS
            ),
            vol.Optional(CONF_MAXIMUM, default=1): vol.Any(None, vol.Coerce(int)),
        }
    ),
)


class _BatchMethod(ABC):
    def __init__(self, count_condition: int) -> None:
        """Initialize the batch method."""
        self._count_condition = count_condition
        self._counter: int = 0
        if count_condition is None:
            count_condition = 1

    @abstractmethod
    def _increment_counter(self, elapsed_time: Decimal | None) -> int:
        """Return the current batch size."""

    @staticmethod
    def from_name(method_name: str, count_condition: int) -> _BatchMethod:
        return _NAME_TO_BATCH_METHOD[method_name](count_condition)

    def current_batch_size(self) -> int:
        """Return the current batch size."""
        return self._counter

    def check_batch_ready(self, elapsed_time: Decimal | None) -> bool:
        batch_size_curr = self._increment_counter(elapsed_time)
        if batch_size_curr >= self._count_condition:
            _LOGGER.debug(
                "Batch ready with size %s, count condition %s",
                batch_size_curr,
                self._count_condition,
            )
            # reset counter
            self._counter = 0
            return True
        return False


class _ChangePoint(_BatchMethod):
    def _increment_counter(self, elapsed_time: Decimal | None) -> int:
        self._counter += 1
        return self._counter


class _NumSamples(_BatchMethod):
    """Prepares batch of source sensor data with equal number of samples."""

    def _increment_counter(self, elapsed_time: Decimal | None) -> int:
        self._counter += 1
        return self._counter


class _TimeDuration(_BatchMethod):
    """Prepares batch of source sensor data with equal time duration."""

    def _increment_counter(self, elapsed_time: Decimal | None) -> int:
        if elapsed_time is None:
            _LOGGER.error("No elapsed time provided for time duration method")
            return self._counter
        # check if elapsed time is greater than count condition
        if elapsed_time >= self._count_condition:
            self._counter += 1
        return self._counter


_NAME_TO_BATCH_METHOD: dict[str, type[_BatchMethod]] = {
    METHOD_NUMSAMPLES: _NumSamples,
    METHOD_TIMEDURATION: _TimeDuration,
    METHOD_CHANGEPOINT: _ChangePoint,
}


class _DataLoadTrigger(Enum):
    StateEvent = "state_event"
    TimeElapsed = "time_elapsed"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Initialize config entry."""
    registry = er.async_get(hass)
    # Validate + resolve entity registry id to entity_id
    source_entity_id = er.async_validate_entity_id(
        registry, config_entry.options[CONF_SOURCE_SENSOR]
    )

    device_info = async_device_info_to_link_from_entity(
        hass,
        source_entity_id,
    )

    if max_sub_interval_dict := config_entry.options.get(CONF_MAX_SUB_INTERVAL, None):
        max_sub_interval = cv.time_period(max_sub_interval_dict)
    else:
        max_sub_interval = None

    dataloader = DataLoaderSensor(
        batch_method=config_entry.options[CONF_METHOD],
        count_condition=config_entry.options[CONF_MAXIMUM],
        name=config_entry.title,
        source_entity=source_entity_id,
        unique_id=config_entry.entry_id,
        unit_time=config_entry.options[CONF_UNIT_TIME],
        device_info=device_info,
        max_sub_interval=max_sub_interval,
    )

    async_add_entities([dataloader])


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the data loader sensor."""
    dataloader = DataLoaderSensor(
        batch_method=config[CONF_METHOD],
        count_condition=config[CONF_MAXIMUM],
        name=config.get(CONF_NAME),
        source_entity=config[CONF_SOURCE_SENSOR],
        unique_id=config.get(CONF_UNIQUE_ID),
        unit_time=config[CONF_UNIT_TIME],
        max_sub_interval=config.get(CONF_MAX_SUB_INTERVAL),
    )

    async_add_entities([dataloader])


class DataLoaderSensor(SensorEntity):
    """Representation of a data loader sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False

    def __init__(
        self,
        *,
        batch_method: str,
        count_condition: int,
        name: str | None,
        source_entity: str,
        unique_id: str | None,
        unit_time: UnitOfTime,
        max_sub_interval: timedelta | None,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize the data loader sensor."""
        self._attr_unique_id = unique_id
        self._sensor_source_id = source_entity
        self._state: bool | None = False
        self._count: int = 0
        self._count_condition: int = count_condition
        self._method = _BatchMethod.from_name(batch_method, count_condition)

        self._attr_name = name if name is not None else f"{source_entity} data loader"
        self._unit_of_measurement: str | None = None
        self._unit_time = UNIT_TIME[unit_time]
        self._unit_time_str = unit_time
        self._attr_icon = "mdi:chart-histogram"
        self._source_entity: str = source_entity
        self._attr_device_info = device_info
        self._max_sub_interval: timedelta | None = (
            None  # disable time based batching
            if max_sub_interval is None or max_sub_interval.total_seconds() == 0
            else max_sub_interval
        )
        self._max_sub_interval_exceeded_callback: CALLBACK_TYPE = lambda *args: None
        self._last_data_load_time: datetime = datetime.now(tz=UTC)
        self._last_data_load_trigger = _DataLoadTrigger.StateEvent

    def _derive_and_set_attributes_from_state(self, source_state: State) -> None:
        # If the source has no defined unit we cannot derive a unit
        self._unit_of_measurement = None

        self._attr_device_class = None
        if self._attr_device_class:
            self._attr_icon = None  # Remove this sensors icon default and allow to fallback to the device class default
        else:
            self._attr_icon = "mdi:chart-histogram"

    def _update_data_loader_state(self, send_batch: bool) -> None:
        if isinstance(self._state, bool):
            self._state = send_batch
        else:
            self._state = False
        _LOGGER.debug("send batch = %s, new state = %s", send_batch, self._state)

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        if self._max_sub_interval is not None:
            source_state = self.hass.states.get(self._sensor_source_id)
            self._schedule_max_sub_interval_exceeded_if_state_is_numeric(source_state)
            self.async_on_remove(self._cancel_max_sub_interval_exceeded_callback)
            handle_state_change = (
                self._check_batch_on_state_change_with_max_sub_interval
            )
            handle_state_report = (
                self._check_batch_on_state_report_with_max_sub_interval
            )
        else:
            handle_state_change = self._check_batch_on_state_change_callback
            handle_state_report = self._check_batch_on_state_report_callback

        if (
            state := self.hass.states.get(self._source_entity)
        ) and state.state != STATE_UNAVAILABLE:
            self._derive_and_set_attributes_from_state(state)

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                self._sensor_source_id,
                handle_state_change,
            )
        )
        self.async_on_remove(
            async_track_state_report_event(
                self.hass,
                self._sensor_source_id,
                handle_state_report,
            )
        )

    @callback
    def _check_batch_on_state_change_with_max_sub_interval(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle sensor state update when sub interval is configured."""
        self._check_batch_on_state_update_with_max_sub_interval(
            None, event.data["old_state"], event.data["new_state"]
        )

    @callback
    def _check_batch_on_state_report_with_max_sub_interval(
        self, event: Event[EventStateReportedData]
    ) -> None:
        """Handle sensor state report when sub interval is configured."""
        self._check_batch_on_state_update_with_max_sub_interval(
            event.data["old_last_reported"], None, event.data["new_state"]
        )

    @callback
    def _check_batch_on_state_update_with_max_sub_interval(
        self,
        old_last_reported: datetime | None,
        old_state: State | None,
        new_state: State | None,
    ) -> None:
        """Integrate based on state change and time.

        Next to doing the integration based on state change this method cancels and
        reschedules time based integration.
        """
        self._cancel_max_sub_interval_exceeded_callback()
        try:
            self._check_batch_on_state_change(old_last_reported, old_state, new_state)
            self._last_data_load_trigger = _DataLoadTrigger.StateEvent
            self._last_data_load_time = datetime.now(tz=UTC)
        finally:
            # When max_sub_interval exceeds without state change the source is assumed
            # constant with the last known state (new_state).
            self._schedule_max_sub_interval_exceeded_if_state_is_numeric(new_state)

    @callback
    def _check_batch_on_state_change_callback(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle sensor state change."""
        return self._check_batch_on_state_change(
            None, event.data["old_state"], event.data["new_state"]
        )

    @callback
    def _check_batch_on_state_report_callback(
        self, event: Event[EventStateReportedData]
    ) -> None:
        """Handle sensor state report."""
        return self._check_batch_on_state_change(
            event.data["old_last_reported"], None, event.data["new_state"]
        )

    def _check_batch_on_state_change(
        self,
        old_last_reported: datetime | None,
        old_state: State | None,
        new_state: State | None,
    ) -> None:
        if new_state is None:
            return

        if new_state.state == STATE_UNAVAILABLE:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if old_state:
            # state has changed, we recover old_state from the event
            # old_state_state = old_state.state
            old_last_reported = old_state.last_reported
        # else:
        # event state reported without any state change
        # old_state_state = new_state.state

        self._attr_available = True
        self._derive_and_set_attributes_from_state(new_state)

        if old_last_reported is None and old_state is None:
            self.async_write_ha_state()
            return

        if TYPE_CHECKING:
            assert old_last_reported is not None
        elapsed_seconds = Decimal(
            (new_state.last_reported - old_last_reported).total_seconds()
            if self._last_data_load_trigger == _DataLoadTrigger.StateEvent
            else (new_state.last_reported - self._last_data_load_time).total_seconds()
        )

        send_batch = self._method.check_batch_ready(elapsed_seconds)

        self._update_data_loader_state(send_batch)
        self.async_write_ha_state()

    def _schedule_max_sub_interval_exceeded_if_state_is_numeric(
        self, source_state: State | None
    ) -> None:
        """Schedule possible integration using the source state and max_sub_interval.

        The callback reference is stored for possible cancellation if the source state
        reports a change before max_sub_interval has passed.

        If the callback is executed, meaning there was no state change reported, the
        source_state is assumed constant and a .
        """
        if self._max_sub_interval is not None and source_state is not None:

            @callback
            def _check_batch_on_max_sub_interval_exceeded_callback(
                now: datetime,
            ) -> None:
                """Integrate based on time and reschedule."""
                elapsed_seconds = Decimal(
                    (now - self._last_data_load_time).total_seconds()
                )
                self._derive_and_set_attributes_from_state(source_state)
                send_batch = self._method.check_batch_ready(elapsed_seconds)
                self._update_data_loader_state(send_batch)
                self.async_write_ha_state()

                self._last_data_load_time = datetime.now(tz=UTC)
                self._last_data_load_trigger = _DataLoadTrigger.TimeElapsed

                self._schedule_max_sub_interval_exceeded_if_state_is_numeric(
                    source_state
                )

            self._max_sub_interval_exceeded_callback = async_call_later(
                self.hass,
                self._max_sub_interval,
                _check_batch_on_max_sub_interval_exceeded_callback,
            )

    def _cancel_max_sub_interval_exceeded_callback(self) -> None:
        self._max_sub_interval_exceeded_callback()

    @property
    def native_value(self) -> bool | None:
        """Return the state of the data loader \"sensor\"."""  # noqa: D301

        return self._state

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit the value is expressed in."""
        return self._unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return the state attributes of the sensor."""
        return {
            ATTR_SOURCE_ID: self._source_entity,
        }
