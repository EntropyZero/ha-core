"""Base class for data loader's batch methods."""

from __future__ import annotations

from abc import ABC, abstractmethod
import datetime
import logging

from homeassistant.util import dt as dt_util

from .const import METHOD_CHANGEPOINT, METHOD_NUMSAMPLES, METHOD_TIMEDURATION
from .data.data_loader_state import DataLoaderState

_LOGGER = logging.getLogger(__name__)

MIN_TIME_UTC = datetime.datetime.min.replace(tzinfo=dt_util.UTC)


class BatchMethod(ABC):
    """Base class for batch methods."""

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
    def from_name(method_name: str) -> BatchMethod:
        """Return the batch method class based on the method name."""

        return _NAME_TO_BATCH_METHOD[method_name]()

    @abstractmethod
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


class ChangePoint(BatchMethod):
    """Prepares batch of source sensor data with change point detection."""

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

        return DataLoaderState(
            seconds_matched=0,
            match_count=0,
            period=period,
            ready=False,
        )


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


_NAME_TO_BATCH_METHOD: dict[str, type[BatchMethod]] = {
    METHOD_NUMSAMPLES: NumSamples,
    METHOD_TIMEDURATION: TimeDuration,
    METHOD_CHANGEPOINT: ChangePoint,
}
