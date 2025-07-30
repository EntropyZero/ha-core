"""Data loader data coordinator."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_start
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .data.data_loader_state import DataLoaderState
from .data_loader import DataLoader

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=1)


class DataLoaderUpdateCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator for Data Loader stats."""

    def __init__(
        self,
        hass: HomeAssistant,
        data_loader: DataLoader,
        config_entry: ConfigEntry | None,
        name: str,
    ) -> None:
        """Initialize DataUpdateCoordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            # name of the data for logging purposes
            name="Data Loader",
            update_interval=UPDATE_INTERVAL,
            # even when the state has not changed, we want to update
            always_update=True,
        )
        self._data_loader = data_loader
        self._subscriber_count = 0
        self._at_start_listener: CALLBACK_TYPE | None = None
        self._track_events_listener: CALLBACK_TYPE | None = None

    # @callback
    # def async_setup_state_listener(self) -> CALLBACK_TYPE:
    #     """Set up listeners and return a callback to cancel them."""

    #     @callback
    #     def remove_listener() -> None:
    #         """Remove update listener."""
    #         self._subscriber_count -= 1
    #         if self._subscriber_count == 0:
    #             self._async_remove_listener()

    #     if self._subscriber_count == 0:
    #         self._async_add_listener()
    #     self._subscriber_count += 1

    #     return remove_listener

    # @callback
    # def _async_remove_listener(self) -> None:
    #     """Remove state change listener."""
    #     if self._track_events_listener:
    #         self._track_events_listener()
    #         self._track_events_listener = None
    #     if self._at_start_listener:
    #         self._at_start_listener()
    #         self._at_start_listener = None

    # @callback
    # def _async_add_listener(self) -> None:
    #     """Add a listener to start tracking state changes after start."""
    #     self._at_start_listener = async_at_start(
    #         self.hass, self._async_add_events_listener
    #     )

    # @callback
    # def _async_add_events_listener(self, *_: Any) -> None:
    #     """Handle hass starting and start tracking events."""
    #     self._at_start_listener = None
    #     self._track_events_listener = async_track_state_change_event(
    #         self.hass, [self._data_loader.entity_id], self._async_update_from_event
    #     )

    # async def _async_update_from_event(
    #     self, event: Event[EventStateChangedData]
    # ) -> None:
    #     """Process an update from an event."""
    #     # self.data['mySamples'] += 1
    #     # if self.data['mySamples'] > 100:
    #     #   self.data['mySamples'] = 0
    #     #   await self._async_update_data(self)

    #     self.async_set_updated_data(
    #         await self._data_loader.async_update(event)
    #     )  # from superclass

    async def _async_update_data(self):
        """Fetch update the data loader state."""
        # Step 1: Load the data from hostory module.  Timeframe or event count based
        # get_last_state_changes(hass: HomeAssistant, number_of_states: int, entity_id: str)
        # state_changes_during_period(hass: HomeAssistant,start_time: datetime,end_time: datetime | None = None,entity_id: str | None = None)

        # Step 2: Send data to the anomaly detector service
        # Step 3: Update the "data" collection with anomaly results and call async_updates
        try:
            # my coordinator is stateful so it needs to update its dataclass
            _LOGGER.debug("DataLoaderUpdateCoordinator updating data")
            # when returning, ends up being stored in self.data
            state = True  # await self._data_loader.async_update(None)

        except (TemplateError, TypeError, ValueError) as ex:
            raise UpdateFailed(ex) from ex
        else:
            return state
