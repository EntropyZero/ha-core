"""Manage the data loader data."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import datetime
import logging

from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util

from .const import METHOD_CHANGEPOINT, METHOD_NUMSAMPLES, METHOD_TIMEDURATION
from .helpers import async_calculate_period, floored_timestamp

MIN_TIME_UTC = datetime.datetime.min.replace(tzinfo=dt_util.UTC)

_LOGGER = logging.getLogger(__name__)


@dataclass
class DataLoaderStatsState:
    """The current stats of the data loader."""

    seconds_matched: int
    match_count: int
    period: tuple[datetime.datetime, datetime.datetime] | None
    ready: bool


@dataclass
class DataLoaderState:
    """A minimal state to avoid holding on to State objects."""

    source_sensor_state: str
    last_changed: float  # used for


class DataLoader:
    """Manage data loader stats."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        entity_states: list[str],
        duration: datetime.timedelta | None,
        batch_method: str,
        count_condition: int | None,
    ) -> None:
        """Init the Data Loader stats manager."""
        self.hass = hass
        self.entity_id = entity_id
        self._duration = duration
        self._method = _BatchMethod.from_name(batch_method)
        self._count_condition = count_condition
        # derived attributes
        self._period: tuple[datetime.datetime, datetime.datetime] | None = None
        self._start: Template | None = None
        self._end: Template | None = None
        self._init_time = dt_util.utcnow()
        # if method is time duration
        if batch_method in [METHOD_TIMEDURATION]:
            # duration cannot be None
            if type(duration) is not datetime.timedelta:
                raise ValueError(
                    f"Invalid duration type: {type(duration)}. Expected timedelta."
                )
            self._start = Template("{{ now() }}", hass=hass)
            self._end = None
            self._duration = duration
            self._period = async_calculate_period(duration, self._start, self._end)

        # if method is num samples and right now changepoint is implemented the same
        elif batch_method in [METHOD_NUMSAMPLES, METHOD_CHANGEPOINT]:
            if type(count_condition) is int:
                self._count_condition = count_condition
            else:
                raise ValueError(
                    f"Invalid count condition type: {type(count_condition)}. "
                    "Expected int."
                )

        self._state: DataLoaderStatsState = DataLoaderStatsState(
            seconds_matched=0, match_count=0, period=self._period, ready=False
        )
        self._history_current_period: list[DataLoaderState] = []
        self._history_previous_period: list[DataLoaderState] = []
        self._has_recorder_data = False  # use this?
        self._entity_states = set(entity_states)  # ??

        _LOGGER.debug(
            "Upon init of dataloader, the count condition is %s and the duration is %s",
            self._count_condition,
            self._duration,
        )

    async def async_update(
        self, event: Event[EventStateChangedData] | None
    ) -> DataLoaderStatsState:
        """Update the stats at a given time- the elapsed time or count based off the batch method."""
        # Get values of start and end if period not none
        if self._period is None:
            period_start = self._init_time
            period_end = None
        else:
            period_start, period_end = self._period

            # Convert times to UTC
            period_start = dt_util.as_utc(period_start)
            period_end = dt_util.as_utc(period_end)

        # Compute integer timestamps
        period_start_timestamp = floored_timestamp(period_start)
        # period_end_timestamp = floored_timestamp(period_end)

        utc_now = dt_util.utcnow()
        now_timestamp = floored_timestamp(utc_now)

        if event is None:
            # If no event is provided, we cannot process it yet
            _LOGGER.debug("No event provided, returning current state")
            # event_timestamp = floored_timestamp(dt_util.utcnow())
            return self._state

        if event and (new_state := event.data["new_state"]) is not None:
            event_timestamp = floored_timestamp(dt_util.as_utc(new_state.last_changed))
            _LOGGER.debug("event timestamp is %s", event_timestamp)
        else:
            event_timestamp = floored_timestamp(
                dt_util.utcnow()
            )  # get last state instead??? CALL DataLoaderState.last_changed which is of type float
            _LOGGER.debug(
                "No new state in event, using current time as bandaid CHANGE THIS LATER %s, also event.data[new_state] is %s to check",
                event_timestamp,
                event.data["new_state"],
            )
            # can't just return self._state here because might need to let time duration method store state
            return self._state  # for now

        # If we end up querying data from the recorder when we get triggered by a new state
        # change event, it is possible this function could be reentered a second time before
        # the first recorder query returns. In that case a second recorder query will be done
        # and we need to hold the new event so that we can append it after the second query.
        # Otherwise the event will be dropped.
        # if event:
        # self._pending_events.append(event)

        if event_timestamp > now_timestamp:
            # If the event timestamp is in the future, we cannot process it yet
            _LOGGER.debug(
                "Skipping future timestamp %s (now %s)",
                event_timestamp,
                now_timestamp,
            )
            return self._state

        if event_timestamp < period_start_timestamp:
            # If the event timestamp is before the period start, we cannot process
            _LOGGER.debug(
                "Skipping event timestamp %s (period start %s)",
                event_timestamp,
                period_start_timestamp,
            )
            return self._state

        # Appending data to batch only if state has changed
        new_data = False
        # if event and (new_state := event.data["new_state"]) is not None:
        if period_start_timestamp <= floored_timestamp(
            dt_util.as_utc(new_state.last_changed)
        ):
            _LOGGER.debug("New state is %s", new_state.state)
            self._history_current_period.append(
                DataLoaderState(new_state.state, new_state.last_changed_timestamp)
            )
            new_data = True

        # Calculate elapsed time to pass to batch methods
        elapsed_seconds = int(event_timestamp - period_start_timestamp)

        # Check if ready to send batch
        if new_data is True:
            _LOGGER.debug("New data received")
        else:
            _LOGGER.debug("No new data received")

        new_state_of_data_loader: DataLoaderStatsState = self._method.check_batch_ready(
            elapsed_seconds,
            new_data,
            self._state,
            self._count_condition,
            self._duration,
            self._period,
        )
        send_batch = new_state_of_data_loader.ready

        # if send_batch is True, set a new period
        if send_batch:
            # Reset history for the new period
            self._history_previous_period = self._history_current_period.copy()
            self._history_current_period = []

        # set the state of the data loader and return it
        _LOGGER.debug("send batch is %s", send_batch)
        self._state = DataLoaderStatsState(
            new_state_of_data_loader.seconds_matched,
            new_state_of_data_loader.match_count,
            new_state_of_data_loader.period,
            send_batch,
        )
        return self._state


class _BatchMethod(ABC):
    def __init__(self) -> None:
        """Initialize the batch method."""
        self._seconds_match: int = 0
        self._matched_count: int = 0

    def _increment_counter(
        self,
        elapsed_time: int,
        new_data: bool,
        current_match_count: int,
        current_seconds_match: int,
    ) -> tuple[int, int]:
        if new_data:
            self._matched_count = current_match_count + 1
        self._seconds_match = elapsed_time if elapsed_time is not None else 0
        return self._seconds_match, self._matched_count

    @staticmethod
    def from_name(method_name: str) -> _BatchMethod:
        return _NAME_TO_BATCH_METHOD[method_name]()

    @abstractmethod
    def check_batch_ready(
        self,
        elapsed_time: int,
        new_data: bool,
        current_state: DataLoaderStatsState,
        count_condition: int | None,
        duration: datetime.timedelta | None,
        period: tuple[datetime.datetime, datetime.datetime] | None,
    ) -> DataLoaderStatsState:
        """Check if the batch is ready to be sent."""


class _ChangePoint(_BatchMethod):
    def check_batch_ready(
        self,
        elapsed_time: int,
        new_data: bool,
        current_state: DataLoaderStatsState,
        count_condition: int | None,
        duration: datetime.timedelta | None,
        period: tuple[datetime.datetime, datetime.datetime] | None,
    ) -> DataLoaderStatsState:
        """Check if the batch is ready to be sent."""

        return DataLoaderStatsState(
            seconds_matched=0,
            match_count=0,
            period=period,
            ready=False,
        )


class _NumSamples(_BatchMethod):
    """Prepares batch of source sensor data with equal number of samples."""

    def check_batch_ready(
        self,
        elapsed_time: int,
        new_data: bool,
        current_state: DataLoaderStatsState,
        count_condition: int | None,
        duration: datetime.timedelta | None,
        period: tuple[datetime.datetime, datetime.datetime] | None,
    ) -> DataLoaderStatsState:
        """Check if the batch is ready to be sent."""

        _LOGGER.debug(
            "The count condition is %s and the batch method is NumSamples",
            count_condition,
        )

        current_ready = current_state.ready
        if current_ready:
            _LOGGER.debug("Batch is already ready")
        current_seconds_matched = current_state.seconds_matched
        current_match_count = current_state.match_count
        # Add a queue here potentially to hold the new data that can't be processed yet

        new_seconds_matched, new_match_count = self._increment_counter(
            elapsed_time, new_data, current_match_count, current_seconds_matched
        )

        update_state = DataLoaderStatsState(
            seconds_matched=new_seconds_matched,
            match_count=new_match_count,
            period=period,
            ready=False,
        )

        if count_condition is not None and new_match_count >= count_condition:
            _LOGGER.debug(
                "Batch ready with match count %s, count condition %s, elapsed time %s",
                new_match_count,
                count_condition,
                new_seconds_matched,
            )
            # prepare the updated state
            update_state = DataLoaderStatsState(
                seconds_matched=new_seconds_matched,
                match_count=new_match_count,
                period=(
                    MIN_TIME_UTC,
                    MIN_TIME_UTC,
                ),  # period is not updated here, it is updated in the DataLoader class
                ready=True,
            )
        return update_state


class _TimeDuration(_BatchMethod):
    """Prepares batch of source sensor data with equal time duration."""

    def check_batch_ready(
        self,
        elapsed_time: int,
        new_data: bool,
        current_state: DataLoaderStatsState,
        count_condition: int | None,
        duration: datetime.timedelta | None,
        period: tuple[datetime.datetime, datetime.datetime] | None,
    ) -> DataLoaderStatsState:
        """Check if the batch is ready to be sent."""

        # check if period is None, error
        if period is None:
            _LOGGER.error("Period is None, cannot process batch")
            return DataLoaderStatsState(
                seconds_matched=0,
                match_count=0,
                period=None,
                ready=False,
            )

        _LOGGER.debug(
            "The duration is %s and the batch method is TimeDuration", duration
        )

        current_ready = current_state.ready
        if current_ready:
            _LOGGER.debug("Batch is already ready")
        current_seconds_matched = current_state.seconds_matched
        current_match_count = current_state.match_count
        # current_period = current_state.period
        # Add a queue here potentially to hold the new data that can't be processed yet

        new_seconds_matched, new_match_count = self._increment_counter(
            elapsed_time, new_data, current_match_count, current_seconds_matched
        )

        # initialize a new state
        update_state = DataLoaderStatsState(
            seconds_matched=new_seconds_matched,
            match_count=new_match_count,
            period=period,
            ready=False,
        )

        if duration is not None and new_seconds_matched >= int(
            duration.total_seconds()
        ):
            _LOGGER.debug(
                "Batch ready with seconds matched %s, duration %s, elapsed time %s",
                new_seconds_matched,
                duration,
                elapsed_time,
            )

            _, end = period
            new_period = (end, end + duration)
            # prepare the updated state
            update_state = DataLoaderStatsState(
                seconds_matched=new_seconds_matched,
                match_count=new_match_count,
                period=new_period,
                ready=True,
            )
        return update_state


_NAME_TO_BATCH_METHOD: dict[str, type[_BatchMethod]] = {
    METHOD_NUMSAMPLES: _NumSamples,
    METHOD_TIMEDURATION: _TimeDuration,
    METHOD_CHANGEPOINT: _ChangePoint,
}
