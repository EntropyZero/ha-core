"""NumSamples Batch Method for Data Loader."""

from __future__ import annotations

import datetime
import logging

from homeassistant.util import dt as dt_util

from ..data.DataLoaderState import DataLoaderState
from .BatchMethod import BatchMethod

MIN_TIME_UTC = datetime.datetime.min.replace(tzinfo=dt_util.UTC)

_LOGGER = logging.getLogger(__name__)


class NumSamples(BatchMethod):
    """Prepares batch of source sensor data with equal number of samples."""

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
            elapsed_time,
            source_data_changed,
            current_match_count,
            current_seconds_matched,
        )

        update_state = DataLoaderState(
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
            update_state = DataLoaderState(
                seconds_matched=new_seconds_matched,
                match_count=new_match_count,
                period=None,
                ready=True,
            )
        return update_state
