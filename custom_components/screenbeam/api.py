"""HTTP client for the register API of ScreenBeam MoCA adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from http import HTTPStatus
import json

import aiohttp

from .decode import Identity, Status, UnsupportedRegister, read_identity, read_status

_HEADERS = {
    # The adapter's own UI sends JSON under this content type.
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "text/html, */*",
}


class ScreenBeamError(Exception):
    """Base error talking to an adapter."""


class ScreenBeamConnectionError(ScreenBeamError):
    """The adapter could not be reached or gave an unusable reply."""


class ScreenBeamAuthError(ScreenBeamError):
    """The adapter rejected the credentials."""


class ScreenBeamUnsupportedError(ScreenBeamError, UnsupportedRegister):
    """The firmware does not know the register."""


class ScreenBeamClient:
    """Read-only client for one adapter.

    The embedded web server handles one request at a time, so calls are
    serialised.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        *,
        timeout: float = 10.0,
    ) -> None:
        """Initialise the client."""
        self.host = host
        self._session = session
        self._auth = aiohttp.BasicAuth(username, password)
        self._timeout = timeout
        self._lock = asyncio.Lock()

    async def call(self, register: str, *data: int) -> list[int]:
        """POST to a register and return the reply words."""
        url = f"http://{self.host}/ms/{register}"
        body = json.dumps({"data": list(data)}, separators=(",", ":"))
        async with self._lock:
            try:
                async with (
                    asyncio.timeout(self._timeout),
                    self._session.post(
                        url, data=body, auth=self._auth, headers=_HEADERS
                    ) as resp,
                ):
                    if resp.status == HTTPStatus.UNAUTHORIZED:
                        raise ScreenBeamAuthError(f"{self.host} rejected the credentials")
                    if resp.status == HTTPStatus.BAD_REQUEST:
                        raise ScreenBeamUnsupportedError(
                            f"{self.host} does not support {register}"
                        )
                    resp.raise_for_status()
                    raw = await resp.read()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise ScreenBeamConnectionError(
                    f"Error talking to {self.host}: {err or type(err).__name__}"
                ) from err
        try:
            return [int(word, 16) for word in json.loads(raw.decode("latin-1"))["data"]]
        except (ValueError, KeyError, TypeError) as err:
            raise ScreenBeamConnectionError(
                f"Unexpected reply from {url}: {raw[:80]!r}"
            ) from err

    @contextmanager
    def _short_reply(self) -> Iterator[None]:
        try:
            yield
        except IndexError as err:
            raise ScreenBeamConnectionError(f"Short reply from {self.host}") from err

    async def async_get_identity(self) -> Identity:
        """Read MAC, chipset and firmware."""
        with self._short_reply():
            return await read_identity(self.call)

    async def async_get_status(
        self, *, chip: str, no_eth_firmware: Collection[str] = ()
    ) -> Status:
        """Read link state, PHY rates, counters and Ethernet ports."""
        with self._short_reply():
            return await read_status(self.call, chip=chip, no_eth_firmware=no_eth_firmware)
