"""Binary sensors of ScreenBeam adapters: coax link and coordinator role."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ScreenBeamConfigEntry
from .decode import Status
from .entity import ScreenBeamEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ScreenBeamBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a ScreenBeam binary sensor."""

    is_on_fn: Callable[[Status], bool]


BINARY_SENSORS: tuple[ScreenBeamBinarySensorDescription, ...] = (
    ScreenBeamBinarySensorDescription(
        key="coax_link",
        translation_key="coax_link",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on_fn=lambda s: s.link_up and s.node_count > 1,
    ),
    ScreenBeamBinarySensorDescription(
        key="coax_encryption",
        translation_key="coax_encryption",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda s: s.encrypted,
    ),
    ScreenBeamBinarySensorDescription(
        key="network_coordinator",
        translation_key="network_coordinator",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda s: s.is_network_coordinator,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScreenBeamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors for an adapter."""
    coordinator = entry.runtime_data
    async_add_entities(ScreenBeamBinarySensor(coordinator, d) for d in BINARY_SENSORS)


class ScreenBeamBinarySensor(ScreenBeamEntity, BinarySensorEntity):
    """A ScreenBeam binary sensor."""

    entity_description: ScreenBeamBinarySensorDescription

    @property
    def is_on(self) -> bool:
        """Return the state."""
        return self.entity_description.is_on_fn(self.coordinator.data.status)
