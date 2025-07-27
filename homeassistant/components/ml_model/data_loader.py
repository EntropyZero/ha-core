"""Manages the coordinator data."""

from __future__ import annotations

import datetime
import logging

from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util

from .batch_methods import BatchMethod
from .const import METHOD_CHANGEPOINT, METHOD_NUMSAMPLES, METHOD_TIMEDURATION
from .data.batch_data import BatchData
from .data.data_loader_state import DataLoaderState
from .helpers import async_calculate_period, floored_timestamp

MIN_TIME_UTC = datetime.datetime.min.replace(tzinfo=dt_util.UTC)

_LOGGER = logging.getLogger(__name__)


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
        self._method = BatchMethod.from_name(batch_method)
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

        self._state: DataLoaderState = DataLoaderState(
            seconds_matched=0, match_count=0, period=self._period, ready=False
        )
        self._history_current_period: list[BatchData] = []
        self._history_previous_period: list[BatchData] = []
        self._has_recorder_data = False  # use this?
        self._entity_states = set(entity_states)  # ??

        _LOGGER.debug(
            "Upon init of dataloader, the count condition is %s and the duration is %s",
            self._count_condition,
            self._duration,
        )

    async def async_update(
        self, event: Event[EventStateChangedData] | None
    ) -> DataLoaderState:
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

        source_data_changed = False
        if event and (new_src_state := event.data["new_state"]) is not None:
            event_timestamp = floored_timestamp(
                dt_util.as_utc(new_src_state.last_changed)
            )
            _LOGGER.debug("event timestamp is %s", event_timestamp)
            source_data_changed = True
        else:
            event_timestamp = (
                self._history_current_period[-1].last_changed
                if self._history_current_period
                else floored_timestamp(dt_util.utcnow())
            )

            _LOGGER.debug(
                "No NEW source sensor state in event, last changed was %s, also event.data[new_state] is %s",
                event_timestamp,
                event.data["new_state"] if event else "None",
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
                "Skipping- either future timestamp %s (now %s), or event_timestamp not calculated",
                event_timestamp,
                now_timestamp,
            )
            return self._state

        if event_timestamp < period_start_timestamp:
            # If the event timestamp is before the period start, we cannot process
            _LOGGER.debug(
                "Skipping- event timestamp %s is before period start %s",
                event_timestamp,
                period_start_timestamp,
            )
            return self._state

        # Calculate elapsed time to pass to batch methods
        elapsed_seconds = int(event_timestamp - period_start_timestamp)
        new_state_of_data_loader: DataLoaderState = self._method.check_batch_ready(
            elapsed_seconds,
            source_data_changed,
            self._state,
            self._count_condition,
            self._duration,
            self._period,
        )
        send_batch = new_state_of_data_loader.ready

        # update the data stored in a batch
        if source_data_changed is True:
            _LOGGER.debug("New state is %s", new_src_state)

            self._history_current_period.append(
                BatchData(str(new_src_state), event_timestamp)
            )

        else:
            curr_src_data = (
                self._history_current_period[-1].source_sensor_state
                if self._history_current_period
                else None
            )

            if curr_src_data is not None:
                _LOGGER.debug("Current state is %s", curr_src_data)
                self._history_current_period.append(
                    BatchData(curr_src_data, now_timestamp)
                )

        # if send_batch is True, set a new period
        if send_batch:
            # Reset history for the new period
            self._history_previous_period = self._history_current_period.copy()
            self._history_current_period = []

        # set the state of the data loader and return it
        _LOGGER.debug("send batch is %s", send_batch)
        self._state = DataLoaderState(
            new_state_of_data_loader.seconds_matched,
            new_state_of_data_loader.match_count,
            new_state_of_data_loader.period,
            send_batch,
        )
        return self._state
