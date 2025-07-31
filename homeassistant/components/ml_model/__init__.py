"""The ML Model integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_STATE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.helper_integration import async_handle_source_entity_changes

from .const import (
    CONF_CONDITION,
    CONF_DURATION,
    CONF_METHOD,
    CONF_SOURCE_SENSOR,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import AnomalyDetectorUpdateCoordinator
from .models.anomaly_config import AnomalyConfig


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ML Model from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    anomaly_configuration = AnomalyConfig()
    anomaly_configuration.entity_id = entry.options[CONF_SOURCE_SENSOR]
    anomaly_configuration.entity_states = entry.options[CONF_STATE]

    anomaly_configuration.duration = None
    if duration_dict := entry.options.get(CONF_DURATION):
        anomaly_configuration.duration = timedelta(**duration_dict)

    anomaly_configuration.batch_method = entry.options[CONF_METHOD]

    count_condition: int | None = entry.options[CONF_CONDITION]
    if type(count_condition) is float:
        count_condition = int(count_condition)

    anomaly_configuration.count_condition = count_condition

    coordinator = AnomalyDetectorUpdateCoordinator(hass, anomaly_configuration)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
