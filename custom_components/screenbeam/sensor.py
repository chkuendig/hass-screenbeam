"""Sensors of ScreenBeam adapters: PHY rates, channels and Ethernet counters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfDataRate, UnitOfFrequency
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import ScreenBeamConfigEntry
from .decode import Status
from .entity import ScreenBeamEntity

PARALLEL_UPDATES = 0  # the coordinator does the polling

PACKETS = "packets"


@dataclass(frozen=True, kw_only=True)
class ScreenBeamSensorDescription(SensorEntityDescription):
    """Describes a ScreenBeam sensor."""

    value_fn: Callable[[Status], StateType]
    attrs_fn: Callable[[Status], dict[str, Any]] | None = None


def _counter(key: str, value_fn: Callable[[Status], int], *, diagnostic: bool) -> ScreenBeamSensorDescription:
    return ScreenBeamSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=PACKETS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
        value_fn=value_fn,
    )


SENSORS: tuple[ScreenBeamSensorDescription, ...] = (
    ScreenBeamSensorDescription(
        key="tx_phy_rate",
        translation_key="tx_phy_rate",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.tx_rate,
        attrs_fn=lambda s: {"peers": s.tx_rates},
    ),
    ScreenBeamSensorDescription(
        key="rx_phy_rate",
        translation_key="rx_phy_rate",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.rx_rate,
        attrs_fn=lambda s: {"peers": s.rx_rates},
    ),
    ScreenBeamSensorDescription(
        key="moca_nodes",
        translation_key="moca_nodes",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.node_count,
        attrs_fn=lambda s: {"macs": sorted(s.node_macs.values())},
    ),
    _counter("tx_packets", lambda s: s.frames.tx_good, diagnostic=False),
    _counter("rx_packets", lambda s: s.frames.rx_good, diagnostic=False),
    _counter("tx_errors", lambda s: s.frames.tx_bad, diagnostic=True),
    _counter("rx_errors", lambda s: s.frames.rx_bad, diagnostic=True),
    _counter("tx_dropped", lambda s: s.frames.tx_dropped, diagnostic=True),
    _counter("rx_dropped", lambda s: s.frames.rx_dropped, diagnostic=True),
    ScreenBeamSensorDescription(
        key="moca_version",
        translation_key="moca_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.network_version,
    ),
    ScreenBeamSensorDescription(
        key="beacon_channel",
        translation_key="beacon_channel",
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.beacon_channel_mhz,
    ),
    ScreenBeamSensorDescription(
        key="primary_channel",
        translation_key="primary_channel",
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.primary_channel_mhz,
    ),
    ScreenBeamSensorDescription(
        key="bonded_channels",
        translation_key="bonded_channels",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.bonded_channels,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScreenBeamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for an adapter."""
    coordinator = entry.runtime_data
    async_add_entities(ScreenBeamSensor(coordinator, d) for d in SENSORS)


class ScreenBeamSensor(ScreenBeamEntity, SensorEntity):
    """A ScreenBeam sensor."""

    entity_description: ScreenBeamSensorDescription

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return per-peer details where there are any."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
