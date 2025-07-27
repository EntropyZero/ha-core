"""TimeDuration Batch Method for Data Loader."""

from __future__ import annotations

import datetime
import logging

from homeassistant.util import dt as dt_util

from ..data.DataLoaderState import DataLoaderState
from .BatchMethod import BatchMethod

MIN_TIME_UTC = datetime.datetime.min.replace(tzinfo=dt_util.UTC)

_LOGGER = logging.getLogger(__name__)


class TimeDuration(BatchMethod):
    """Prepares batch of source sensor data with equal time duration."""

    def check_batch_ready(
        self,
        elapsed_time: int,
        source_data_changed: bool,
        current_state: DataLoaderState,
        count_condition: int | None,
        duration: datetime.timedelta | None,
        period: tuple[datetime.datetime, datetime.datetime] | None,
    ) -> DataLoaderState:
        """Check if the batch is ready to be sent."""

        # check if period is None, error
        if period is None:
            _LOGGER.error("Period is None, cannot process batch")
            return DataLoaderState(
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
        # Add a queue here potentially to hold the new data that can't be processed yet

        new_seconds_matched, new_match_count = self._increment_counter(
            elapsed_time,
            source_data_changed,
            current_match_count,
            current_seconds_matched,
        )

        # initialize a new state
        update_state = DataLoaderState(
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
            update_state = DataLoaderState(
                seconds_matched=new_seconds_matched,
                match_count=new_match_count,
                period=new_period,
                ready=True,
            )
        return update_state
