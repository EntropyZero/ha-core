"""Data loader data coordinator."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import (
    get_last_state_changes,
    state_changes_during_period,
)
from .models.anomaly_config import AnomalyConfig
from .services.anomaly_detector import AnomalyDetector

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
            entity_state_batch = await get_instance(self.hass).async_add_executor_job(
                get_last_state_changes, self.hass, 10, self._anomaly_config.entity_id
            )
            model = AnomalyDetector(self._anomaly_config)
            self.data = await self.hass.async_add_executor_job(
                model.detect, entity_state_batch
            )

        except (TypeError, ValueError) as ex:
            raise UpdateFailed(ex) from ex
        except Exception as ex:
            _LOGGER.error("Error updating anomaly detector data: %s", ex)
            raise UpdateFailed(f"Error updating anomaly detector data: {ex}") from ex
        else:
            return self.data
