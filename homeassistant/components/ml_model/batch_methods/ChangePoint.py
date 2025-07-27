"""ChangePoint Batch Method for Data Loader."""

from __future__ import annotations

import datetime
import logging

from homeassistant.util import dt as dt_util

from ..data.DataLoaderState import DataLoaderState
from .BatchMethod import BatchMethod

MIN_TIME_UTC = datetime.datetime.min.replace(tzinfo=dt_util.UTC)

_LOGGER = logging.getLogger(__name__)


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
