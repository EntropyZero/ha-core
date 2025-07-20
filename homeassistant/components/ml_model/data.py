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
    period: tuple[datetime.datetime, datetime.datetime]
    ready: bool


@dataclass
class DataLoaderState:
    """A minimal state to avoid holding on to State objects."""

    source_sensor_state: str
    last_changed: float  # used for


class DataLoaderStats:
    """Manage data loader stats."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        entity_states: list[str],
        duration: datetime.timedelta | None,
        start: Template,
        end: Template | None,
        batch_method: str,
        count_condition: int | datetime.timedelta,
    ) -> None:
        """Init the Data Loader stats manager."""
        self.hass = hass
        self.entity_id = entity_id
        self._period = (MIN_TIME_UTC, MIN_TIME_UTC)  # from start
        if type(count_condition) is datetime.timedelta:
            self._period = async_calculate_period(duration, start, None)
            self._method = _BatchMethod.from_name(
                batch_method, type(count_condition).__name__
            )  # count condition is passed here temp to get the type
            self._count_condition = int(count_condition.total_seconds())
        else:
            end = Template("{{ now() }}", hass=self.hass)
            self._period = async_calculate_period(None, start, end)
            self._method = _BatchMethod.from_name(
                batch_method, type(count_condition).__name__
            )  # count condition is passed here temp to get the type
            if type(count_condition) is int:
                self._count_condition = count_condition
            else:
                raise ValueError(
                    f"Invalid count condition type: {type(count_condition)}. "
                    "Expected int or timedelta."
                )
        self._state: DataLoaderStatsState = DataLoaderStatsState(
            0, 0, self._period, False
        )
        self._history_current_period: list[DataLoaderState] = []
        self._history_previous_period: list[DataLoaderState] = []
        self._has_recorder_data = False
        self._entity_states = set(entity_states)  # ??
        self._duration = duration
        self._start = start
        self._end = end

    async def async_update(
        self, event: Event[EventStateChangedData] | None
    ) -> DataLoaderStatsState:
        """Update the stats at a given time- the elapsed time or count based off the batch method."""
        # Get values of start and end
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
            _LOGGER.debug("No event provided, skipping update")
            event_timestamp = floored_timestamp(dt_util.utcnow())
        elif event and (new_state := event.data["new_state"]) is not None:
            event_timestamp = floored_timestamp(new_state.last_changed)
            _LOGGER.debug("event timestamp is %s", event_timestamp)
        else:
            event_timestamp = floored_timestamp(dt_util.utcnow())
            _LOGGER.debug(
                "No new state in event, using current time as bandaid CHANGE THIS LATER %s, also event.data[new_state] is %s to check",
                event_timestamp,
                event.data["new_state"],
            )

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

        # Appending data to batch only if state has changed
        new_data = False
        if event and (new_state := event.data["new_state"]) is not None:
            if period_start_timestamp <= floored_timestamp(new_state.last_changed):
                _LOGGER.debug("New state is %s", new_state.state)
                self._history_current_period.append(
                    DataLoaderState(new_state.state, new_state.last_changed_timestamp)
                )
                new_data = True

        # Calculate elapsed time to pass to batch methods
        if event_timestamp < period_start_timestamp:
            # If the event timestamp is before the period start, we cannot process
            _LOGGER.debug(
                "Skipping event timestamp %s (period start %s)",
                event_timestamp,
                period_start_timestamp,
            )
            return self._state

        elapsed_seconds = event_timestamp - period_start_timestamp

        # Check if ready to send batch
        new_state_of_data_loader: DataLoaderStatsState = self._method.check_batch_ready(
            int(elapsed_seconds), new_data, self._state, self._count_condition
        )
        send_batch = new_state_of_data_loader.ready
        # if send_batch is True, set a new period
        if send_batch:
            # Set new period if batch is ready
            self._period = async_calculate_period(self._duration, self._end, None)
            # Convert times to UTC
            self._period = (
                dt_util.as_utc(self._period[0]),
                dt_util.as_utc(self._period[1]),
            )
            # Reset history for the new period
            self._history_previous_period = self._history_current_period.copy()
            self._history_current_period = []

        # set the state of the data loader and return it
        _LOGGER.debug("send batch is %s", send_batch)
        self._state = DataLoaderStatsState(
            new_state_of_data_loader.seconds_matched,
            new_state_of_data_loader.match_count,
            self._period,
            send_batch,
        )
        return self._state


class _BatchMethod(ABC):
    def __init__(self, count_condition_type: str) -> None:
        """Initialize the batch method."""
        self._seconds_match: int = 0
        self._matched_count: int = 0
        # if count_condition is 'timedelta':
        # count_condition = count_condition.total_seconds()
        # if count_condition is None:
        # count_condition = 1
        # else it is a maximum number for number of samples algorithm
        self._count_condition_type = count_condition_type

    @abstractmethod
    def _increment_counter(
        self,
        elapsed_time: int,
        new_data: bool,
        current_match_count: int,
        current_seconds_match: int,
    ) -> tuple[int, int]:
        """Return the current batch size."""

    @staticmethod
    def from_name(method_name: str, count_condition_type: str) -> _BatchMethod:
        return _NAME_TO_BATCH_METHOD[method_name](
            count_condition_type
        )  # accessing a dictionary

    # def current_batch_size(self) -> int:
    #     """Return the current batch size."""
    #     return self._counter

    def check_batch_ready(
        self,
        elapsed_time: int,
        new_data: bool,
        current_state: DataLoaderStatsState,
        count_condition: int,
    ) -> DataLoaderStatsState:
        """Check if the batch is ready to be sent."""

        # initialize a new state
        updated_state = DataLoaderStatsState(
            seconds_matched=0,
            match_count=0,
            period=(MIN_TIME_UTC, MIN_TIME_UTC),
            ready=False,
        )

        current_ready = current_state.ready
        if current_ready:
            _LOGGER.debug("Batch is already ready, skipping check")
        current_seconds_matched = current_state.seconds_matched
        current_match_count = current_state.match_count
        # current_period = current_state.period

        seconds_matched, match_count = self._increment_counter(
            elapsed_time, new_data, current_match_count, current_seconds_matched
        )

        _LOGGER.debug(
            "The count condition is %s and the type is %s",
            count_condition,
            self._count_condition_type,
        )
        if self._count_condition_type == "timedelta":
            if seconds_matched >= count_condition:
                _LOGGER.debug(
                    "Batch ready with size %s, elapsed time %s, duration condition %s",
                    match_count,
                    seconds_matched,
                    count_condition,
                )
                # prepare the updated state
                updated_state = DataLoaderStatsState(
                    seconds_matched=seconds_matched,
                    match_count=match_count,
                    period=(
                        MIN_TIME_UTC,
                        MIN_TIME_UTC,
                    ),  # period is not set here, it is set in the DataLoaderStats class
                    ready=True,
                )
                # reset counters
                self._seconds_match = 0
                self._matched_count = 0
                return updated_state
        if self._count_condition_type == "int":
            if match_count >= count_condition:
                _LOGGER.debug(
                    "Batch ready with match count %s, count condition %s, elapsed time %s",
                    match_count,
                    count_condition,
                    seconds_matched,
                )
                # prepare the updated state
                updated_state = DataLoaderStatsState(
                    seconds_matched=seconds_matched,
                    match_count=match_count,
                    period=(
                        MIN_TIME_UTC,
                        MIN_TIME_UTC,
                    ),  # period is not set here, it is set in the DataLoaderStats class
                    ready=True,
                )

                # reset counters
                self._seconds_match = 0
                self._matched_count = 0
                return updated_state
        return updated_state


class _ChangePoint(_BatchMethod):
    def _increment_counter(
        self,
        elapsed_time: int,
        new_data: bool,
        current_match_count: int,
        current_seconds_match: int,
    ) -> tuple[int, int]:
        self._matched_count = current_match_count + 1
        self._seconds_match = current_seconds_match + (
            elapsed_time if elapsed_time is not None else 0
        )
        return self._seconds_match, self._matched_count


class _NumSamples(_BatchMethod):
    """Prepares batch of source sensor data with equal number of samples."""

    def _increment_counter(
        self,
        elapsed_time: int,
        new_data: bool,
        current_match_count: int,
        current_seconds_match: int,
    ) -> tuple[int, int]:
        if new_data:
            self._matched_count = current_match_count + 1
        self._seconds_match = current_seconds_match + (
            elapsed_time if elapsed_time is not None else 0
        )
        return self._seconds_match, self._matched_count


class _TimeDuration(_BatchMethod):
    """Prepares batch of source sensor data with equal time duration."""

    def _increment_counter(
        self,
        elapsed_time: int,
        new_data: bool,
        current_match_count: int,
        current_seconds_match: int,
    ) -> tuple[int, int]:
        # if elapsed_time is None:
        # _LOGGER.error("No elapsed time provided for time duration method")
        # return self._seconds_match, self._matched_count
        # check if elapsed time is greater than count condition
        self._seconds_match = current_seconds_match + (
            elapsed_time if elapsed_time is not None else 0
        )
        return self._seconds_match, 0


_NAME_TO_BATCH_METHOD: dict[str, type[_BatchMethod]] = {
    METHOD_NUMSAMPLES: _NumSamples,
    METHOD_TIMEDURATION: _TimeDuration,
    METHOD_CHANGEPOINT: _ChangePoint,
}

# def _async_compute_seconds_and_changes(
#     self, now_timestamp: float, start_timestamp: float, end_timestamp: float
# ) -> tuple[float, int]:
#     """Compute the seconds matched and changes from the history list and first state."""
#     # state_changes_during_period is called with include_start_time_state=True
#     # which is the default and always provides the state at the start
#     # of the period
#     previous_state_matches = False
#     last_state_change_timestamp = 0.0
#     elapsed = 0.0
#     match_count = 0

#     # Make calculations
#     for history_state in self._history_current_period:
#         current_state_matches = history_state.state in self._entity_states
#         state_change_timestamp = history_state.last_changed

#         if math.floor(state_change_timestamp) > end_timestamp:
#             break

#         if math.floor(state_change_timestamp) > now_timestamp:
#             # Shouldn't count states that are in the future
#             _LOGGER.debug(
#                 "Skipping future timestamp %s (now %s)",
#                 state_change_timestamp,
#                 now_timestamp,
#             )
#             break

#         if previous_state_matches:
#             elapsed += state_change_timestamp - last_state_change_timestamp
#         elif current_state_matches:
#             match_count += 1

#         previous_state_matches = current_state_matches
#         last_state_change_timestamp = max(start_timestamp, state_change_timestamp)

#     # Count time elapsed between last history state and end of measure
#     if previous_state_matches:
#         measure_end = min(end_timestamp, now_timestamp)
#         elapsed += measure_end - last_state_change_timestamp

#     # Save value in seconds
#     seconds_matched = elapsed
#     return seconds_matched, match_count
