<p align="center"><img src="custom_components/screenbeam/brand/logo.png" alt="ScreenBeam" height="64"></p>

# ScreenBeam MoCA for Home Assistant

Monitor ScreenBeam MoCA (Ethernet over coax) adapters in Home Assistant: whether the coax link
is up, the PHY rate in each direction, and the Ethernet traffic and error counters. Each adapter
becomes a device. The integration only reads from the adapters and never changes their settings.

![A pair of ScreenBeam MoCA adapters](screenbeam.jpg)

## Supported adapters

Tested with a pair of **ECB7250** adapters (MoCA 2.5, MaxLinear MXL371x, firmware 1.17.5).
Other ScreenBeam adapters on MaxLinear MXL37xx chipsets use the same web interface and
should work too (ECB6250, and the ScreenBeam-branded MoCA 2.5 ECB6200). If yours does, please open
an issue so it can be listed here. The older Actiontec-branded ECB6200 (bonded MoCA 2.0, firmware
2.11.x) is a different design and is not expected to work.

### Firmware

ScreenBeam publishes release notes per model. For the ECB7250, version
[1.18.14.1](https://residential.screenbeam.com/support/ecb7250-firmware-release-notes) (June 2024)
fixes MoCA link flapping and CVE-2020-25928 (a DNS vulnerability) over 1.17.5. The ECB6250's newest
release is 1.17.5. ECB6250 and ECB7250 builds share version numbers but are different images, so only
install firmware made for your model. The firmware version is shown on the device page.

The integration supports both 1.17.5 and 1.18.14.1. Firmware 1.18 makes the frame counters 64 bits
wide and adds the Ethernet port's link state and speed, which show up as two extra entities. When an
adapter's firmware changes, the integration reloads it by itself. Support for 1.18 is based on that
firmware's own web interface. It has not been tested on an upgraded adapter yet; if you run 1.18,
please report how it works.

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
| Model (option) | The model printed on the label, such as ECB7250. The adapters do not report their model, so until it is set the device shows "MoCA 2.5 adapter". |
| Poll interval (option) | How often to read the adapter, 10–3600 s, default 60 s. One poll is about a dozen small requests and takes about a second. |

Each device is named `ScreenBeam XXXX` after its DHCP hostname. Rename the devices after the room
they are in. If an adapter's address changes, use **Reconfigure** on its entry.

## Entities

| Entity | Description |
|---|---|
| Coax link | On while the adapter is linked to at least one other adapter over the coax. |
| Coax TX / RX PHY rate | PHY rate to and from the other adapters in Mbit/s. With more than two adapters, this is the slowest link; the `peers` attribute lists the rate for each peer MAC. |
| Ethernet TX / RX rate | Frames per second sent and received on the adapter's Ethernet port, averaged over one poll interval. Unknown for the first poll after a restart and right after the counters reset. The adapters only count frames, not bytes, so there is no throughput in Mbit/s. |
| MoCA nodes | Number of adapters on the coax network, this one included. |
| Ethernet TX / RX packets *(diagnostic)* | Running totals of those frames, for long-term statistics and Prometheus. |
| Ethernet TX / RX errors, dropped *(diagnostic)* | Bad and dropped frames. |
| Last counter reset *(diagnostic)* | When Home Assistant last saw the counters start again from zero, which happens when an adapter restarts or the coax network forms again. Resets while Home Assistant was not polling are missed. |
| Coax encryption *(diagnostic)* | Whether link encryption (MoCA privacy or enhanced privacy) is on. The adapters ship with a published default network password; change it on both adapters if the coax is shared with neighbours or the street. |
| Network coordinator *(diagnostic)* | Whether this adapter coordinates the MoCA network. |
| Ethernet link *(firmware 1.18+)* | On while the adapter's Ethernet port has a link. The `ports` attribute lists link, speed and duplex for each port the chip reports. |
| Ethernet link speed *(firmware 1.18+)* | Negotiated speed of the Ethernet port in Mbit/s (10, 100, 1000 or 2500). Unknown while the port is down or still negotiating. |
| MoCA version, beacon channel, primary channel, bonded channels *(diagnostic)* | Network version and the frequencies in use. MoCA 2.5 bonds up to five 100 MHz channels. |

The PHY rate is the speed the two adapters negotiate on the coax, not the actual throughput. A
rate that drops over time usually points to a bad connector, splitter or cable.

The counters are 32 bits wide (64 bits from firmware 1.18) and start again from zero when an
adapter restarts or the coax network forms again. Home Assistant treats them as `total_increasing`, so statistics handle the
resets.

### Monitoring tips

- Usually only one adapter of a pair is on the same side of the coax as Home Assistant. The far
  one is reached over the coax itself, so when the link drops, the far adapter becomes
  *unavailable* and the near one reports **Coax link** off. Alert on the near adapter's link
  sensor.
- With Home Assistant's [Prometheus integration](https://www.home-assistant.io/integrations/prometheus/)
  the values are exported as `hass_sensor_data_rate_mbit_per_s`, `hass_sensor_unit_packets`,
  `hass_sensor_unit_packets_per_s` and `hass_binary_sensor_state`. For example, `rate(hass_sensor_unit_packets{entity=~".*_rx_errors"}[1h])`
  shows rising error counts, and `resets(hass_sensor_unit_packets{entity=~".*_tx_packets"}[1d])`
  counts restarts and re-forms of the network.

## How it works

The adapters have no API, SNMP or UPnP. Their web interface reads every value with a small JSON
POST to `/ms/<bus>/<register>` behind HTTP basic authentication. This integration makes the same
requests as the interface's *Device Status* and *PHY Rates* pages and decodes the replies the same
way: link state from register `0x15`, frame counters from `0x14`, channels from `0x24` and `0x7f`,
privacy settings from `0x1059` and `0x130D`, Ethernet port state from `1/0x307` (firmware 1.18+),
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
