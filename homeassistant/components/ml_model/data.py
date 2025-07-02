"""Manage the data loader data."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import datetime
import logging
import math

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

    seconds_matched: float | None
    match_count: int | None
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
        start: Template | None,
        end: Template | None,
        duration: datetime.timedelta | None,
        batch_method: str,
        count_condition: int,
    ) -> None:
        """Init the Data Loader stats manager."""
        self.hass = hass
        self.entity_id = entity_id
        self._period = (MIN_TIME_UTC, MIN_TIME_UTC)
        self._state: DataLoaderStatsState = DataLoaderStatsState(
            None, None, self._period, False
        )
        self._history_current_period: list[DataLoaderState] = []
        self._history_previous_period: list[DataLoaderState] = []
        self._has_recorder_data = False
        self._entity_states = set(entity_states)
        self._duration = duration
        self._start = start
        self._end = end
        self._count_condition: int = count_condition
        self._method = _BatchMethod.from_name(batch_method, count_condition)

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

        if event and (new_state := event.data["new_state"]) is not None:
            event_timestamp = math.floor(new_state.last_changed.timestamp())
        else:
            event_timestamp = math.floor(utc_now.timestamp())
            _LOGGER.debug(
                "No new state in event, using current time as bandaid CHANGE THIS LATER %s",
                dt_util.as_local(utc_now),
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
        send_batch, seconds_matched, match_count = self._method.check_batch_ready(
            elapsed_seconds, new_data
        )

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

        # returning the stats state
        self._state = DataLoaderStatsState(
            seconds_matched, match_count, self._period, send_batch
        )
        return self._state


class _BatchMethod(ABC):
    def __init__(self, count_condition: int) -> None:
        """Initialize the batch method."""
        self._count_condition = count_condition
        self._seconds_match: float = 0.0
        self._matched_count: int = 0
        if count_condition is None:
            count_condition = 1

    @abstractmethod
    def _increment_counter(
        self, elapsed_time: float | None, new_data: bool
    ) -> tuple[float, int]:
        """Return the current batch size."""

    @staticmethod
    def from_name(method_name: str, count_condition: int) -> _BatchMethod:
        return _NAME_TO_BATCH_METHOD[method_name](count_condition)

    # def current_batch_size(self) -> int:
    #     """Return the current batch size."""
    #     return self._counter

    def check_batch_ready(
        self, elapsed_time: float | None, new_data: bool
    ) -> tuple[bool, float | None, int | None]:
        seconds_matched, match_count = self._increment_counter(elapsed_time, new_data)
        if seconds_matched >= self._count_condition:
            _LOGGER.debug(
                "Batch ready with size %s, elapsed time %s, duration condition %s",
                match_count,
                seconds_matched,
                self._count_condition,
            )
            # reset counters
            self._seconds_match = 0.0
            self._matched_count = 0
            return True, seconds_matched, match_count
        if match_count >= self._count_condition:
            _LOGGER.debug(
                "Batch ready with match count %s, count condition %s, elapsed time %s",
                match_count,
                self._count_condition,
                seconds_matched,
            )
            # reset counters
            self._seconds_match = 0.0
            self._matched_count = 0
            return True, seconds_matched, match_count
        return False, seconds_matched, match_count


class _ChangePoint(_BatchMethod):
    def _increment_counter(
        self, elapsed_time: float | None, new_data: bool
    ) -> tuple[float, int]:
        self._matched_count += 1
        self._seconds_match += elapsed_time if elapsed_time is not None else 0.0
        return self._seconds_match, self._matched_count


class _NumSamples(_BatchMethod):
    """Prepares batch of source sensor data with equal number of samples."""

    def _increment_counter(
        self, elapsed_time: float | None, new_data: bool
    ) -> tuple[float, int]:
        if new_data:
            self._matched_count += 1
        self._seconds_match += elapsed_time if elapsed_time is not None else 0.0
        return self._seconds_match, self._matched_count


class _TimeDuration(_BatchMethod):
    """Prepares batch of source sensor data with equal time duration."""

    def _increment_counter(
        self, elapsed_time: float | None, new_data: bool
    ) -> tuple[float, int]:
        if elapsed_time is None:
            _LOGGER.error("No elapsed time provided for time duration method")
            return self._seconds_match, self._matched_count
        # check if elapsed time is greater than count condition
        if elapsed_time >= self._count_condition:
            self._seconds_match += elapsed_time
        return self._seconds_match, self._matched_count


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
