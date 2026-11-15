"""Decode tests against replies captured from a pair of ScreenBeam ECB7250 adapters.

Fixtures map "<register>[:<data,...>]" to the raw reply words. The decoder has
no Home Assistant dependency, so it is loaded straight from its file.

Run with ``python -m pytest tests`` or ``python tests/test_decode.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "screenbeam_decode", ROOT.parent / "custom_components" / "screenbeam" / "decode.py"
)
decode = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = decode  # dataclasses resolve annotations via sys.modules
_spec.loader.exec_module(decode)

MAC_117 = "d4:47:5a:01:b4:ae"
MAC_126 = "d4:47:5a:01:b4:b0"


def _replies_call(replies: dict[str, list[str]]):
    """Answer from captured replies; registers the capture lacks are unsupported."""

    async def call(register: str, *data: int) -> list[int]:
        key = register + (":" + ",".join(map(str, data)) if data else "")
        if key not in replies:
            raise decode.UnsupportedRegister(key)
        return [int(word, 16) for word in replies[key]]

    return call


def _replies(name: str) -> dict[str, list[str]]:
    return json.loads((ROOT / "fixtures" / name).read_text())


def _fixture_call(name: str):
    return _replies_call(_replies(name))


def _status(name: str):
    return asyncio.run(decode.read_status(_fixture_call(name)))


def test_helpers() -> None:
    assert decode.version_str(0x25) == "2.5"
    assert decode.mac_from_words(0xD4475A01, 0xB4AE0000) == MAC_117
    assert decode.words_to_ascii([0x312E3137, 0x2E350000]) == "1.17.5"
    assert decode.fmr_request_version(0x25, 0x25) == 2
    assert decode.fmr_request_version(0x25, 0x11) == 1


def test_identity() -> None:
    identity = asyncio.run(decode.read_identity(_fixture_call("ecb7250_117.json")))
    assert identity == decode.Identity(
        mac=MAC_117, chip="MXL371x", node_version="2.5", firmware="1.17.5"
    )


def test_network_coordinator_side() -> None:
    status = _status("ecb7250_117.json")
    assert status.mac == MAC_117
    assert status.link_up
    assert status.is_network_coordinator
    assert status.network_version == "2.5"
    assert status.node_macs == {0: MAC_117, 1: MAC_126}
    assert status.beacon_channel_mhz == 1150
    assert status.primary_channel_mhz == 1175
    assert status.bonded_channels == 5
    assert status.tx_rates.keys() == {MAC_126}
    assert status.rx_rates.keys() == {MAC_126}
    # MoCA 2.5 over five bonded channels: well above 1 Gbit/s each way.
    assert 1400 < status.tx_rate < 2600
    assert 1400 < status.rx_rate < 2600
    assert status.frames.tx_good > 0 and status.frames.rx_good > 0
    # Enhanced privacy (MoCA 2.x) is on in the captures; legacy privacy is off.
    assert status.encrypted
    # 1.17.5 answers HTTP 400 to ethInfo: no Ethernet port state, no failure.
    assert status.eth_ports is None
    assert not status.eth_link_up and status.eth_speed_mbps is None


def test_both_ends_agree() -> None:
    """Each adapter decodes the whole network's rate table; they must match."""
    near = _status("ecb7250_117.json")
    far = _status("ecb7250_126.json")
    assert not far.is_network_coordinator
    assert far.mac == MAC_126
    # Captured a few seconds apart, so allow for normal rate jitter.
    assert abs(near.tx_rate - far.rx_rate) <= 50
    assert abs(near.rx_rate - far.tx_rate) <= 50


def test_link_down_has_no_rates() -> None:
    replies = _replies("ecb7250_117.json")
    local = list(replies["0/0x15"])
    local[5] = "0x00000000"  # link down
    local[12] = "0x00000001"  # only this node left
    replies["0/0x15"] = local

    status = asyncio.run(decode.read_status(_replies_call(replies)))
    assert not status.link_up
    assert status.node_count == 1
    assert status.rates == ()
    assert status.tx_rate is None and status.rx_rate is None
    assert status.primary_channel_mhz is None


def _frames(tx: int, rx: int):
    return decode.FrameCounters(tx, 0, 0, rx, 0, 0)


def test_packet_rates() -> None:
    rates = decode.packet_rates(_frames(1000, 5000), _frames(7000, 35000), 60.0)
    assert rates == decode.PacketRates(tx=100.0, rx=500.0)
    assert decode.packet_rates(_frames(1, 1), _frames(1, 1), 0) is None


def test_counter_reset_is_detected() -> None:
    before, after = _frames(4_000_000, 9_000_000), _frames(1_200, 3_400)
    assert decode.counters_reset(before, after)
    assert decode.packet_rates(before, after, 60.0) is None
    assert not decode.counters_reset(after, after)


def test_encryption_off() -> None:
    replies = _replies("ecb7250_126.json")
    replies["0/0x130D/GET"] = ["0x00000003"]  # enhanced privacy bit (2) clear
    assert not asyncio.run(decode.read_status(_replies_call(replies))).encrypted


# Firmware 1.18.14.1 replies. No adapter here runs 1.18, so these follow the
# layout in that firmware's own devStatus.html instead of a capture.


def _hex(words: list[int]) -> list[str]:
    return [f"0x{word:08x}" for word in words]


def _ascii_words(text: str, count: int) -> list[int]:
    raw = text.encode().ljust(count * 4, b"\0")
    return [int.from_bytes(raw[i : i + 4], "big") for i in range(0, len(raw), 4)]


def _replies_118(name: str, eth: list[int]) -> dict[str, list[str]]:
    replies = _replies(name)
    local = replies["0/0x15"]
    local[21:28] = _hex(_ascii_words("1.18.14.1", 7))
    frames = [0] * 108
    for index, value in {
        12: 5 << 32 | 123,  # tx good, past the old 32-bit limit
        30: 7,  # tx bad
        48: 1,  # tx dropped
        66: 1 << 32,  # rx good
        84: 2,  # rx bad
        102: 3,  # rx dropped
    }.items():
        frames[index], frames[index + 1] = value >> 32, value & 0xFFFFFFFF
    replies["0/0x14:0"] = _hex(frames)
    replies["1/0x307/GET:0"] = _hex(eth)
    return replies


def test_firmware_118_counters_are_64_bit() -> None:
    replies = _replies_118("ecb7250_117.json", [1, 4, 1, 0, 5, 0])
    status = asyncio.run(decode.read_status(_replies_call(replies)))
    assert status.firmware == "1.18.14.1"
    assert status.frames == decode.FrameCounters(
        tx_good=5 << 32 | 123, tx_bad=7, tx_dropped=1, rx_good=1 << 32, rx_bad=2, rx_dropped=3
    )


def test_firmware_118_ethernet_ports() -> None:
    # Port 0: up at 2.5 Gbit/s full duplex; port 1 (unused SGMII): down.
    call = _replies_call(_replies_118("ecb7250_117.json", [1, 4, 1, 0, 5, 0]))
    assert asyncio.run(decode.read_identity(call)).firmware == "1.18.14.1"
    status = asyncio.run(decode.read_status(call))
    assert status.eth_ports == (
        decode.EthPort(link_up=True, speed_mbps=2500, full_duplex=True),
        decode.EthPort(link_up=False, speed_mbps=None, full_duplex=False),
    )
    assert status.eth_link_up
    assert status.eth_speed_mbps == 2500


def test_ethinfo_short_reply_keeps_the_rest() -> None:
    # A truncated ethInfo reply yields the complete ports only, not a failed poll.
    replies = _replies_118("ecb7250_117.json", [1, 2, 1, 0])
    status = asyncio.run(decode.read_status(_replies_call(replies)))
    assert status.eth_ports == (decode.EthPort(True, 1000, True),)
    assert status.tx_rate is not None


def test_ethernet_negotiating_and_down() -> None:
    negotiating = decode.parse_eth_info([1, 3, 1, 0, 2, 1], 2)
    assert negotiating[0].speed_mbps is None  # "Auto-Neg"
    status = decode.Status(
        mac=MAC_117, node_id=0, nc_node_id=0, link_up=True, network_version="2.5",
        firmware="1.18.14.1", node_macs={0: MAC_117}, beacon_channel_mhz=1150,
        primary_channel_mhz=None, bonded_channels=None, frames=_frames(0, 0), rates=(),
        encrypted=True, eth_ports=negotiating,
    )
    # Port 1 reports 1 Gbit/s but has no link, so it does not count.
    assert status.eth_link_up and status.eth_speed_mbps is None
    assert decode.parse_eth_info([1, 2, 1], 2) == (decode.EthPort(True, 1000, True),)


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print("ok", name)
