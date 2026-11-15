<p align="center"><img src="custom_components/screenbeam/brand/logo.png" alt="ScreenBeam" height="64"></p>

# ScreenBeam MoCA for Home Assistant

Monitor ScreenBeam MoCA (Ethernet over coax) adapters in Home Assistant: whether the coax link
is up, the PHY rate in each direction, and the Ethernet traffic and error counters. Each adapter
becomes a device. The integration only reads from the adapters and never changes their settings.

![A pair of ScreenBeam MoCA adapters](screenbeam.jpg)

## Supported adapters

Tested with a pair of **ECB7250** adapters (MoCA 2.5, MaxLinear MXL371x, firmware 1.17.5).
Other ScreenBeam adapters on MaxLinear MXL37xx chipsets use the same web interface and
should work too. If yours does, please open an issue so it can be listed here.

## Installation

### Marketplace

1. In Home Assistant, open **Settings → Marketplace**, add this repository
   (`https://github.com/chkuendig/hass-screenbeam`) as a custom repository of type
   **Integration**, and install **ScreenBeam MoCA**.
2. Restart Home Assistant.

### Manual

Copy `custom_components/screenbeam` into the `custom_components` folder of your Home Assistant
configuration and restart Home Assistant.

## Configuration

Adapters announce themselves over DHCP (hostname `VSCO-XXXX`), so Home Assistant usually offers
them under **Settings → Devices & services → Discovered**. To add one by hand, go to
**Add integration → ScreenBeam MoCA**. Add each adapter of a pair separately.

| Setting | Description |
|---|---|
| Host | IP address of the adapter's web interface. Give the adapters fixed DHCP leases. |
| Username / Password | The login of the adapter's web interface (the username is usually `admin`). |
| Poll interval (option) | How often to read the adapter, 10–3600 s, default 60 s. One poll is about a dozen small requests and takes about a second. |

Each device is named `ScreenBeam XXXX` after its DHCP hostname. Rename the devices after the room
they are in. If an adapter's address changes, use **Reconfigure** on its entry.

## Entities

| Entity | Description |
|---|---|
| Coax link | On while the adapter is linked to at least one other adapter over the coax. |
| Coax TX / RX PHY rate | PHY rate to and from the other adapters in Mbit/s. With more than two adapters, this is the slowest link; the `peers` attribute lists the rate for each peer MAC. |
| MoCA nodes | Number of adapters on the coax network, this one included. |
| Ethernet TX / RX packets | Frames sent and received on the adapter's Ethernet port. |
| Ethernet TX / RX errors, dropped *(diagnostic)* | Bad and dropped frames. |
| Network coordinator *(diagnostic)* | Whether this adapter coordinates the MoCA network. |
| MoCA version, beacon channel, primary channel, bonded channels *(diagnostic)* | Network version and the frequencies in use. MoCA 2.5 bonds up to five 100 MHz channels. |

The PHY rate is the speed the two adapters negotiate on the coax, not the actual throughput. A
rate that drops over time usually points to a bad connector, splitter or cable.

The counters are 32 bits wide and start again from zero when an adapter restarts or the coax
network forms again. Home Assistant treats them as `total_increasing`, so statistics handle the
resets.

### Monitoring tips

- Usually only one adapter of a pair is on the same side of the coax as Home Assistant. The far
  one is reached over the coax itself, so when the link drops, the far adapter becomes
  *unavailable* and the near one reports **Coax link** off. Alert on the near adapter's link
  sensor.
- With Home Assistant's [Prometheus integration](https://www.home-assistant.io/integrations/prometheus/)
  the values are exported as `hass_sensor_data_rate_mbit_per_s`, `hass_sensor_unit_packets` and
  `hass_binary_sensor_state`. For example, `rate(hass_sensor_unit_packets{entity=~".*_rx_errors"}[1h])`
  shows rising error counts, and `resets(hass_sensor_unit_packets{entity=~".*_tx_packets"}[1d])`
  counts restarts and re-forms of the network.

## How it works

The adapters have no API, SNMP or UPnP. Their web interface reads every value with a small JSON
POST to `/ms/<bus>/<register>` behind HTTP basic authentication. This integration makes the same
requests as the interface's *Device Status* and *PHY Rates* pages and decodes the replies the same
way: link state from register `0x15`, frame counters from `0x14`, channels from `0x24` and `0x7f`,
each node's MAC and MoCA version from `0x16`, and the PHY rates from each node's FMR (full mesh
rate) report in `0x1D`. The decoding lives in [`decode.py`](custom_components/screenbeam/decode.py),
with tests against replies captured from a pair of ECB7250s in [`tests/`](tests).

```sh
python -m pytest tests     # or: python tests/test_decode.py
```

The adapters also offer a telnet diagnostic shell, which is off by default. The integration does
not use it.

## Disclaimer

This is not an official ScreenBeam product, and it is not affiliated with or endorsed by
ScreenBeam Inc. ScreenBeam and the ScreenBeam logo are trademarks of ScreenBeam Inc. and are used
here only to identify the adapters this integration works with.
