"""Polling coordinator for one ScreenBeam adapter."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ScreenBeamAuthError, ScreenBeamClient, ScreenBeamError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .decode import Identity, Status

_LOGGER = logging.getLogger(__name__)

type ScreenBeamConfigEntry = ConfigEntry[ScreenBeamCoordinator]


class ScreenBeamCoordinator(DataUpdateCoordinator[Status]):
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

    async def _async_update_data(self) -> Status:
        try:
            return await self.client.async_get_status()
        except ScreenBeamAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ScreenBeamError as err:
            raise UpdateFailed(str(err)) from err
