"""Data loader data coordinator."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .models.anomaly_config import AnomalyConfig

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=1)


class AnomalyDetectorUpdateCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator for Data Loader stats."""

    def __init__(
        self,
        hass: HomeAssistant,
        anomaly_config: AnomalyConfig,
    ) -> None:
        """Initialize DataUpdateCoordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # name of the data for logging purposes
            name="Anomaly Detector",
            update_interval=UPDATE_INTERVAL,
            # even when the state has not changed, we want to update
        )
        self._anomaly_config = anomaly_config

    async def _async_update_data(self):
        """Fetch update the data loader state."""
        # Step 1: Load the data from hostory module.  Timeframe or event count based
        # get_last_state_changes(hass: HomeAssistant, number_of_states: int, entity_id: str)
        # state_changes_during_period(hass: HomeAssistant,start_time: datetime,end_time: datetime | None = None,entity_id: str | None = None)

        # Step 2: Send data to the anomaly detector service
        # Step 3: Update the "data" collection with anomaly results and call async_updates
        try:
            # my coordinator is stateful so it needs to update its dataclass
            _LOGGER.debug("AnomalyDetectorUpdateCoordinator updating data")
            # when returning, ends up being stored in self.data

        except (TypeError, ValueError) as ex:
            raise UpdateFailed(ex) from ex
        else:
            return
