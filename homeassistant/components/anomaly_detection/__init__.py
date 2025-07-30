"""The Unifi Network Poller integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from requests.exceptions import ConnectTimeout

from .const import DOMAIN
from .coordinator import MyCoordinator
from .models import BetterUnifiData

# TODO List the platforms that you want to support.
# For your initial PR, limit it to 1 platform.
PLATFORMS: list[Platform] = [Platform.SENSOR]


def get_hub(data: dict[str, Any]) -> Controller:
    """Return a hub object based on the user input."""
    return Controller(
        data[CONF_HOST],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        version="UDMP-unifiOS",
        ssl_verify=False,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Unifi Network Poller from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    # TODO 1. Create API instance
    # TODO 2. Validate the API connection (and authentication)

    try:
        hub = await hass.async_add_executor_job(get_hub, entry.data)
        aps = await hass.async_add_executor_job(hub.get_aps)
    except APIError as ex:
        raise ConfigEntryAuthFailed from ex
    except ConnectTimeout as ex:
        raise ConfigEntryNotReady from ex

    # TODO 3. Store an API object for your platforms to access
    macs = [ap["mac"] for ap in aps if ap["model"] in ["USPPDUP", "UDMPROSE"]]
    coordinator = MyCoordinator(hass, hub, macs)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = BetterUnifiData(
        api=hub, coordinator=coordinator
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
