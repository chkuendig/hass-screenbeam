"""Decode the register API of ScreenBeam MoCA adapters (MaxLinear MXL37xx).

The adapters' web UI reads every value with a POST to ``/ms/<bus>/<register>``
whose body is ``{"data":[...]}``; the reply is a list of hex words. The word
offsets and the PHY-rate arithmetic here follow the adapters' own
``devStatus.html`` and ``phyRates.html``. Everything is read-only.

This module has no Home Assistant dependency so it can be tested on its own.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

# call(register, *data) -> reply words as integers
Call = Callable[..., Awaitable[list[int]]]

MAX_NODES = 16

REG_LOCAL_INFO = "0/0x15"
REG_FRAME_INFO = "0/0x14"
REG_NODE_INFO = "0/0x16"
REG_FMR = "0/0x1D"
REG_PHY_INFO = "0/0x24"
REG_M25_PHY_INFO = "0/0x7f"
REG_CHIP_ID = "1/0x303/GET"

CHIPS = {0x15: "MXL370x", 0x16: "MXL371x"}

# Offset of the primary channel from the beacon channel (localInfo[18]).
_PRIMARY_OFFSET_MHZ = {0: 0, 1: 25, 2: -25}

# PHY-rate constants from phyRates.html.
_LDPC_LEN_100MHZ = 3900
_LDPC_LEN_50MHZ = 1200
_FFT_LEN_100MHZ = 512
_FFT_LEN_50MHZ = 256


def version_str(value: int) -> str:
    """Format a MoCA version byte (0x25) as "2.5"."""
    return f"{value >> 4 & 0xF}.{value & 0xF}"


def words_to_ascii(words: list[int]) -> str:
    """Decode a NUL-terminated big-endian ASCII string packed into words."""
    out: list[str] = []
    for word in words:
        for shift in (24, 16, 8, 0):
            byte = word >> shift & 0xFF
            if not 0 < byte < 0x80:
                return "".join(out)
            out.append(chr(byte))
    return "".join(out)


def mac_from_words(high: int, low: int) -> str:
    """Build a MAC address from a node GUID (4 bytes + top 2 bytes)."""
    raw = high.to_bytes(4, "big") + (low >> 16).to_bytes(2, "big")
    return ":".join(f"{b:02x}" for b in raw)


@dataclass(frozen=True)
class LocalInfo:
    """Fields of the local-info register (0x15)."""

    node_id: int
    nc_node_id: int
    link_up: bool
    network_version: int
    node_mask: int
    primary_offset: int
    firmware: str

    @property
    def node_ids(self) -> list[int]:
        """Node IDs currently on the MoCA network."""
        return [n for n in range(MAX_NODES) if self.node_mask >> n & 1]


def parse_local_info(words: list[int]) -> LocalInfo:
    """Parse the local-info register."""
    return LocalInfo(
        node_id=words[0],
        nc_node_id=words[1] & 0xFF,
        link_up=words[5] != 0,
        network_version=words[11] & 0xFF,
        node_mask=words[12],
        primary_offset=words[18],
        firmware=words_to_ascii(words[21:28]),
    )


@dataclass(frozen=True)
class FrameCounters:
    """Ethernet frame counters (frame-info register 0x14), 32-bit, wrapping."""

    tx_good: int
    tx_bad: int
    tx_dropped: int
    rx_good: int
    rx_bad: int
    rx_dropped: int


def parse_frame_info(words: list[int]) -> FrameCounters:
    """Parse the frame-info register."""
    return FrameCounters(
        tx_good=words[6],
        tx_bad=words[15],
        tx_dropped=words[24],
        rx_good=words[33],
        rx_bad=words[42],
        rx_dropped=words[51],
    )


def _rate_100mhz(gap: int, ofdmb: int) -> int:
    if not gap:
        return 0
    return (_LDPC_LEN_100MHZ * ofdmb) // ((_FFT_LEN_100MHZ + (gap + 10) * 2) * 46)


def _rate_50mhz(gap: int, ofdmb: int) -> int:
    if not gap:
        return 0
    return (_LDPC_LEN_50MHZ * ofdmb) // ((_FFT_LEN_50MHZ + (gap * 2 + 10)) * 26)


def fmr_request_version(nc_version: int, node_version: int) -> int:
    """Payload version to ask for in an FMR request (1 = MoCA 1.x, 2 = 2.x)."""
    return 1 if min(nc_version, node_version) < 0x20 else 2


def parse_fmr(
    fmr: list[int], entry: int, node_versions: dict[int, int], nc_version: int
) -> dict[int, tuple[int, int]]:
    """Decode the FMR reply for node ``entry``.

    Returns ``{to_node: (nper_mbps, vlper_mbps)}`` for every other node: the PHY
    rate from ``entry`` to that node (the web UI's "From/To" table row).
    """
    node_version = node_versions[entry]
    entry_payload_version = min(node_version, nc_version)
    index, aligned = 10, True
    rates: dict[int, tuple[int, int]] = {}
    for peer in range(MAX_NODES):
        if peer not in node_versions:
            # Absent nodes still occupy space in the payload.
            if node_version >= 0x20:
                index += 1 if aligned else 2
            elif not aligned:
                index += 1
            aligned = not aligned
            continue

        if nc_version < 0x20:
            payload_version = min(entry_payload_version, node_versions[peer])
        else:
            payload_version = node_version

        if payload_version in (0x20, 0x25):
            if aligned:
                gap_n = fmr[index] >> 24 & 0xFF
                gap_vl = fmr[index] >> 16 & 0xFF
                ofdmb_n = fmr[index] & 0xFFFF
                ofdmb_vl = fmr[index + 1] >> 16 & 0xFFFF
                index += 1
            else:
                gap_n = fmr[index] >> 8 & 0xFF
                gap_vl = fmr[index] & 0xFF
                ofdmb_n = fmr[index + 1] >> 16 & 0xFFFF
                ofdmb_vl = fmr[index + 1] & 0xFFFF
                index += 2
        else:
            if aligned:
                gap_n = (fmr[index] & 0xF8000000) >> 27
                ofdmb_n = (fmr[index] & 0x07FF0000) >> 16
            else:
                gap_n = (fmr[index] & 0x0000F800) >> 11
                ofdmb_n = fmr[index] & 0x000007FF
                index += 1
            gap_vl = ofdmb_vl = 0
        aligned = not aligned

        if peer == entry:
            continue  # diagonal = broadcast (GCD) rate
        if gap_vl == 0 and payload_version == 0x20:
            nper = _rate_50mhz(gap_n, ofdmb_n)
        else:
            nper = _rate_100mhz(gap_n, ofdmb_n)
        rates[peer] = (nper, _rate_100mhz(gap_vl, ofdmb_vl))
    return rates


@dataclass(frozen=True)
class Identity:
    """Static facts about an adapter, read once at setup."""

    mac: str
    chip: str
    node_version: str
    firmware: str


@dataclass(frozen=True)
class PhyRate:
    """PHY rate between two adapters on the coax, in Mbit/s."""

    from_mac: str
    to_mac: str
    nper_mbps: int
    vlper_mbps: int


@dataclass(frozen=True)
class Status:
    """One poll of an adapter."""

    mac: str
    node_id: int
    nc_node_id: int
    link_up: bool
    network_version: str
    firmware: str
    node_macs: dict[int, str]
    beacon_channel_mhz: int
    primary_channel_mhz: int | None
    bonded_channels: int | None
    frames: FrameCounters
    rates: tuple[PhyRate, ...]

    @property
    def is_network_coordinator(self) -> bool:
        """Whether this adapter is the MoCA network coordinator."""
        return self.node_id == self.nc_node_id

    @property
    def node_count(self) -> int:
        """Number of adapters on the MoCA network, this one included."""
        return len(self.node_macs)

    @property
    def tx_rates(self) -> dict[str, int]:
        """PHY rate from this adapter to each peer, by peer MAC."""
        return {r.to_mac: r.nper_mbps for r in self.rates if r.from_mac == self.mac}

    @property
    def rx_rates(self) -> dict[str, int]:
        """PHY rate from each peer to this adapter, by peer MAC."""
        return {r.from_mac: r.nper_mbps for r in self.rates if r.to_mac == self.mac}

    @property
    def tx_rate(self) -> int | None:
        """Slowest PHY rate from this adapter to a peer (None without peers)."""
        return min(self.tx_rates.values(), default=None)

    @property
    def rx_rate(self) -> int | None:
        """Slowest PHY rate from a peer to this adapter (None without peers)."""
        return min(self.rx_rates.values(), default=None)


async def _node_info(call: Call, nodes: list[int]) -> tuple[dict[int, int], dict[int, str]]:
    versions: dict[int, int] = {}
    macs: dict[int, str] = {}
    for node in nodes:
        words = await call(REG_NODE_INFO, node)
        macs[node] = mac_from_words(words[0], words[1])
        versions[node] = words[4] & 0xFF
    return versions, macs


async def read_identity(call: Call) -> Identity:
    """Read the adapter's MAC, chipset and firmware."""
    local = parse_local_info(await call(REG_LOCAL_INFO))
    versions, macs = await _node_info(call, [local.node_id])
    chip = (await call(REG_CHIP_ID, 0))[0]
    return Identity(
        mac=macs[local.node_id],
        chip=CHIPS.get(chip, f"0x{chip:x}"),
        node_version=version_str(versions[local.node_id]),
        firmware=local.firmware,
    )


async def read_status(call: Call) -> Status:
    """Read link state, channels, PHY rates and frame counters."""
    local = parse_local_info(await call(REG_LOCAL_INFO))
    frames = parse_frame_info(await call(REG_FRAME_INFO, 0))
    phy = await call(REG_PHY_INFO)
    m25 = await call(REG_M25_PHY_INFO)

    nodes = local.node_ids or [local.node_id]
    versions, macs = await _node_info(call, nodes)
    nc_version = versions.get(local.nc_node_id, local.network_version)

    rates: list[PhyRate] = []
    if local.link_up and len(nodes) > 1:
        for node in nodes:
            fmr = await call(
                REG_FMR, 1 << node, fmr_request_version(nc_version, versions[node])
            )
            for peer, (nper, vlper) in parse_fmr(fmr, node, versions, nc_version).items():
                rates.append(PhyRate(macs[node], macs[peer], nper, vlper))

    beacon = phy[1]
    offset = _PRIMARY_OFFSET_MHZ.get(local.primary_offset)
    bonded = m25[3] if len(m25) > 3 and m25[3] else None
    return Status(
        mac=macs[local.node_id],
        node_id=local.node_id,
        nc_node_id=local.nc_node_id,
        link_up=local.link_up,
        network_version=version_str(local.network_version),
        firmware=local.firmware,
        node_macs=macs if local.link_up else {local.node_id: macs[local.node_id]},
        beacon_channel_mhz=beacon,
        primary_channel_mhz=beacon + offset if offset is not None and local.link_up else None,
        bonded_channels=bonded if local.link_up else None,
        frames=frames,
        rates=tuple(rates),
    )
