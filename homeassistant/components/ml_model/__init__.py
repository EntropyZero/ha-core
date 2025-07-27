"""The ML Model integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_STATE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device import (
    async_entity_id_to_device_id,
    async_remove_stale_devices_links_keep_entity_device,
)
from homeassistant.helpers.helper_integration import async_handle_source_entity_changes

from .const import (
    CONF_CONDITION,
    CONF_DURATION,
    CONF_METHOD,
    CONF_SOURCE_SENSOR,
    PLATFORMS,
)
from .coordinator import DataLoaderUpdateCoordinator
from .data_loader import DataLoader

type DataLoaderConfigEntry = ConfigEntry[DataLoaderUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: DataLoaderConfigEntry) -> bool:
    """Set up ML Model from a config entry."""
    entity_id: str = entry.options[CONF_SOURCE_SENSOR]
    entity_states: list[str] = entry.options[CONF_STATE]

    duration: timedelta | None = None
    if duration_dict := entry.options.get(CONF_DURATION):
        duration = timedelta(**duration_dict)

    batch_method: str = entry.options[CONF_METHOD]

    count_condition: int | None = entry.options[CONF_CONDITION]
    if type(count_condition) is float:
        count_condition = int(count_condition)

    data_loader = DataLoader(
        hass,
        entity_id,
        entity_states,
        duration,
        batch_method,
        count_condition,
    )
    coordinator = DataLoaderUpdateCoordinator(hass, data_loader, entry, entry.title)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    async_remove_stale_devices_links_keep_entity_device(
        hass,
        entry.entry_id,
        entry.options[CONF_SOURCE_SENSOR],
    )

    def set_source_entity_id_or_uuid(source_entity_id: str) -> None:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_SOURCE_SENSOR: source_entity_id},
        )

    async def source_entity_removed() -> None:
        # The source entity has been removed, we need to clean the device links.
        # async_remove_stale_devices_links_keep_entity_device(hass, entry.entry_id, None)
        # history_stats does not allow replacing the input entity.
        await hass.config_entries.async_remove(entry.entry_id)

    entry.async_on_unload(
        async_handle_source_entity_changes(
            hass,
            helper_config_entry_id=entry.entry_id,
            set_source_entity_id_or_uuid=set_source_entity_id_or_uuid,
            source_device_id=async_entity_id_to_device_id(
                hass, entry.options[CONF_SOURCE_SENSOR]
            ),
            source_entity_id_or_uuid=entry.options[CONF_SOURCE_SENSOR],
            source_entity_removed=source_entity_removed,
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(config_entry_update_listener))
    return True


async def config_entry_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener, called when the config entry options are changed."""
    # Remove device link for entry, the source device may have changed.
    # The link will be recreated after load.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
