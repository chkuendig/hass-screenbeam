"""Decode tests against replies captured from a pair of ScreenBeam ECB6200 adapters.

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


def _fixture_call(name: str):
    replies = json.loads((ROOT / "fixtures" / name).read_text())

    async def call(register: str, *data: int) -> list[int]:
        key = register + (":" + ",".join(map(str, data)) if data else "")
        return [int(word, 16) for word in replies[key]]

    return call


def _status(name: str):
    return asyncio.run(decode.read_status(_fixture_call(name)))


def test_helpers() -> None:
    assert decode.version_str(0x25) == "2.5"
    assert decode.mac_from_words(0xD4475A01, 0xB4AE0000) == MAC_117
    assert decode.words_to_ascii([0x312E3137, 0x2E350000]) == "1.17.5"
    assert decode.fmr_request_version(0x25, 0x25) == 2
    assert decode.fmr_request_version(0x25, 0x11) == 1


def test_identity() -> None:
    identity = asyncio.run(decode.read_identity(_fixture_call("ecb6200_117.json")))
    assert identity == decode.Identity(
        mac=MAC_117, chip="MXL371x", node_version="2.5", firmware="1.17.5"
    )


def test_network_coordinator_side() -> None:
    status = _status("ecb6200_117.json")
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


def test_both_ends_agree() -> None:
    """Each adapter decodes the whole network's rate table; they must match."""
    near = _status("ecb6200_117.json")
    far = _status("ecb6200_126.json")
    assert not far.is_network_coordinator
    assert far.mac == MAC_126
    # Captured a few seconds apart, so allow for normal rate jitter.
    assert abs(near.tx_rate - far.rx_rate) <= 50
    assert abs(near.rx_rate - far.tx_rate) <= 50


def test_link_down_has_no_rates() -> None:
    replies = json.loads((ROOT / "fixtures" / "ecb6200_117.json").read_text())
    local = list(replies["0/0x15"])
    local[5] = "0x00000000"  # link down
    local[12] = "0x00000001"  # only this node left
    replies["0/0x15"] = local

    async def call(register: str, *data: int) -> list[int]:
        key = register + (":" + ",".join(map(str, data)) if data else "")
        return [int(word, 16) for word in replies[key]]

    status = asyncio.run(decode.read_status(call))
    assert not status.link_up
    assert status.node_count == 1
    assert status.rates == ()
    assert status.tx_rate is None and status.rx_rate is None
    assert status.primary_channel_mhz is None


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test()
            print("ok", name)
