"""Base class for data loader's batch methods."""

from __future__ import annotations

from abc import ABC, abstractmethod
import datetime

from homeassistant.util import dt as dt_util

from ..data.DataLoaderState import DataLoaderState
from .helpers import _NAME_TO_BATCH_METHOD

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
