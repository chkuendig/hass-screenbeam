"""The ScreenBeam MoCA integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ScreenBeamClient
from .const import DOMAIN
from .coordinator import ScreenBeamConfigEntry, ScreenBeamCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

# Entities that need ethInfo (firmware 1.18+), by platform and key.
_ETHERNET_ENTITIES = ((Platform.BINARY_SENSOR, "ethernet_link"), (Platform.SENSOR, "ethernet_speed"))


async def async_setup_entry(hass: HomeAssistant, entry: ScreenBeamConfigEntry) -> bool:
    """Set up an adapter from a config entry."""
    client = ScreenBeamClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = ScreenBeamCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    if coordinator.data.status.eth_ports is None:
        _remove_ethernet_entities(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _remove_ethernet_entities(hass: HomeAssistant, entry: ScreenBeamConfigEntry) -> None:
    """Drop the Ethernet entities after a downgrade to firmware without ethInfo."""
    registry = er.async_get(hass)
    for platform, key in _ETHERNET_ENTITIES:
        if entity_id := registry.async_get_entity_id(platform, DOMAIN, f"{entry.unique_id}_{key}"):
            registry.async_remove(entity_id)


async def _async_reload_on_options(hass: HomeAssistant, entry: ScreenBeamConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ScreenBeamConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
