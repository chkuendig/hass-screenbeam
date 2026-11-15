"""Sensors of ScreenBeam adapters: PHY rates, traffic, channels and counters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfDataRate, UnitOfFrequency
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import ScreenBeamConfigEntry, ScreenBeamData
from .entity import ScreenBeamEntity, eth_ports_attr

PARALLEL_UPDATES = 0  # the coordinator does the polling

PACKETS = "packets"
PACKETS_PER_SECOND = "packets/s"


@dataclass(frozen=True, kw_only=True)
class ScreenBeamSensorDescription(SensorEntityDescription):
    """Describes a ScreenBeam sensor."""

    value_fn: Callable[[ScreenBeamData], StateType | datetime]
    attrs_fn: Callable[[ScreenBeamData], dict[str, Any]] | None = None


def _phy_rate(key: str, value_fn, attrs_fn) -> ScreenBeamSensorDescription:
    return ScreenBeamSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=value_fn,
        attrs_fn=attrs_fn,
    )


def _packet_rate(key: str, value_fn) -> ScreenBeamSensorDescription:
    return ScreenBeamSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=PACKETS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=value_fn,
    )


def _counter(key: str, value_fn) -> ScreenBeamSensorDescription:
    return ScreenBeamSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=PACKETS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=value_fn,
    )


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


SENSORS: tuple[ScreenBeamSensorDescription, ...] = (
    _phy_rate("tx_phy_rate", lambda d: d.status.tx_rate, lambda d: {"peers": d.status.tx_rates}),
    _phy_rate("rx_phy_rate", lambda d: d.status.rx_rate, lambda d: {"peers": d.status.rx_rates}),
    _packet_rate("tx_packet_rate", lambda d: _round(d.rates.tx) if d.rates else None),
    _packet_rate("rx_packet_rate", lambda d: _round(d.rates.rx) if d.rates else None),
    ScreenBeamSensorDescription(
        key="moca_nodes",
        translation_key="moca_nodes",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.status.node_count,
        attrs_fn=lambda d: {"macs": sorted(d.status.node_macs.values())},
    ),
    _counter("tx_packets", lambda d: d.status.frames.tx_good),
    _counter("rx_packets", lambda d: d.status.frames.rx_good),
    _counter("tx_errors", lambda d: d.status.frames.tx_bad),
    _counter("rx_errors", lambda d: d.status.frames.rx_bad),
    _counter("tx_dropped", lambda d: d.status.frames.tx_dropped),
    _counter("rx_dropped", lambda d: d.status.frames.rx_dropped),
    ScreenBeamSensorDescription(
        key="moca_version",
        translation_key="moca_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.status.network_version,
    ),
    ScreenBeamSensorDescription(
        key="beacon_channel",
        translation_key="beacon_channel",
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.status.beacon_channel_mhz,
    ),
    ScreenBeamSensorDescription(
        key="primary_channel",
        translation_key="primary_channel",
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.status.primary_channel_mhz,
    ),
    ScreenBeamSensorDescription(
        key="bonded_channels",
        translation_key="bonded_channels",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.status.bonded_channels,
    ),
)

# Needs ethInfo (firmware 1.18+).
ETHERNET_SPEED = ScreenBeamSensorDescription(
    key="ethernet_speed",
    translation_key="ethernet_speed",
    native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
    device_class=SensorDeviceClass.DATA_RATE,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=0,
    value_fn=lambda d: d.status.eth_speed_mbps,
    attrs_fn=lambda d: {"ports": eth_ports_attr(d.status)},
)

COUNTERS_RESET = ScreenBeamSensorDescription(
    key="counters_reset",
    translation_key="counters_reset",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda d: d.counters_reset_at,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScreenBeamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for an adapter."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        *(ScreenBeamSensor(coordinator, d) for d in SENSORS),
        ScreenBeamCountersResetSensor(coordinator, COUNTERS_RESET),
    ]
    if coordinator.data.status.eth_ports is not None:
        entities.append(ScreenBeamSensor(coordinator, ETHERNET_SPEED))
    async_add_entities(entities)


class ScreenBeamSensor(ScreenBeamEntity, SensorEntity):
    """A ScreenBeam sensor."""

    entity_description: ScreenBeamSensorDescription

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)


class ScreenBeamCountersResetSensor(ScreenBeamSensor, RestoreSensor):
    """When the frame counters last went backwards (restart or wrap).

    Only resets seen while Home Assistant is polling are recorded, so the
    value is kept across Home Assistant restarts.
    """

    async def async_added_to_hass(self) -> None:
        """Restore the last recorded reset."""
        await super().async_added_to_hass()
        if self.coordinator.counters_reset_at is None and (
            last := await self.async_get_last_sensor_data()
        ) is not None and isinstance(last.native_value, datetime):
            self.coordinator.counters_reset_at = last.native_value

    @property
    def native_value(self) -> datetime | None:
        """Return the last recorded reset."""
        return self.coordinator.counters_reset_at
