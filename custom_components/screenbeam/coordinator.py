"""Polling coordinator for one ScreenBeam adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ScreenBeamAuthError, ScreenBeamClient, ScreenBeamError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .decode import Identity, PacketRates, Status, counters_reset, packet_rates

_LOGGER = logging.getLogger(__name__)

type ScreenBeamConfigEntry = ConfigEntry[ScreenBeamCoordinator]


@dataclass(frozen=True)
class ScreenBeamData:
    """One poll plus what is derived from the previous one."""

    status: Status
    rates: PacketRates | None
    counters_reset_at: datetime | None


class ScreenBeamCoordinator(DataUpdateCoordinator[ScreenBeamData]):
    """Polls one adapter."""

    config_entry: ScreenBeamConfigEntry
    identity: Identity

    def __init__(
        self, hass: HomeAssistant, entry: ScreenBeamConfigEntry, client: ScreenBeamClient
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(
                seconds=int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            ),
        )
        self.client = client
        self._previous: tuple[Status, float] | None = None
        # Seeded from the restored "Last counter reset" sensor.
        self.counters_reset_at: datetime | None = None

    async def _async_setup(self) -> None:
        try:
            self.identity = await self.client.async_get_identity()
        except ScreenBeamAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ScreenBeamError as err:
            raise UpdateFailed(str(err)) from err
        if format_mac(self.identity.mac) != self.config_entry.unique_id:
            # The address now belongs to a different adapter.
            raise UpdateFailed(
                f"{self.client.host} answers as {self.identity.mac}, not"
                f" {self.config_entry.unique_id}; reconfigure the address"
            )

    async def _async_update_data(self) -> ScreenBeamData:
        try:
            status = await self.client.async_get_status()
        except ScreenBeamAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ScreenBeamError as err:
            raise UpdateFailed(str(err)) from err

        if self.data is not None and (
            status.firmware != self.identity.firmware
            or (status.eth_ports is None) != (self.data.status.eth_ports is None)
        ):
            # Upgraded or downgraded: reload so the device info and the
            # Ethernet entities (firmware 1.18+) follow the new firmware.
            _LOGGER.info(
                "%s now runs firmware %s (was %s); reloading",
                self.client.host,
                status.firmware,
                self.identity.firmware,
            )
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

        now = time.monotonic()
        rates = None
        if self._previous is not None:
            previous, then = self._previous
            if counters_reset(previous.frames, status.frames):
                self.counters_reset_at = dt_util.utcnow().replace(microsecond=0)
            else:
                rates = packet_rates(previous.frames, status.frames, now - then)
        self._previous = (status, now)
        return ScreenBeamData(status, rates, self.counters_reset_at)
