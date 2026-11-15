"""Base entity for ScreenBeam adapters."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MODEL, DOMAIN, MANUFACTURER
from .coordinator import ScreenBeamCoordinator


class ScreenBeamEntity(CoordinatorEntity[ScreenBeamCoordinator]):
    """An entity of one adapter."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ScreenBeamCoordinator, description: EntityDescription
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        identity = coordinator.identity
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            connections={(CONNECTION_NETWORK_MAC, entry.unique_id)},
            manufacturer=MANUFACTURER,
            # The adapters do not report their model; it is set in the options.
            model=entry.options.get(CONF_MODEL) or f"MoCA {identity.node_version} adapter",
            hw_version=None,  # was the chipset before 0.2.0; it is in diagnostics
            sw_version=identity.firmware,
            name=entry.title,
            configuration_url=f"http://{entry.data[CONF_HOST]}/",
        )
