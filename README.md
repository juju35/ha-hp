# ha-hp

[![Marketplace](https://img.shields.io/badge/Marketplace-Custom-41BDF5.svg)](https://www.home-assistant.io/integrations/marketplace/)
[![Marketplace Validation](https://github.com/juju35/ha-hp/actions/workflows/hacs.yml/badge.svg)](https://github.com/juju35/ha-hp/actions/workflows/hacs.yml)
[![Validate](https://github.com/juju35/ha-hp/actions/workflows/validate.yml/badge.svg)](https://github.com/juju35/ha-hp/actions/workflows/validate.yml)
[![Lint](https://github.com/juju35/ha-hp/actions/workflows/lint.yml/badge.svg)](https://github.com/juju35/ha-hp/actions/workflows/lint.yml)
[![Release](https://img.shields.io/github/v/release/juju35/ha-hp)](https://github.com/juju35/ha-hp/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/juju35/ha-hp/blob/main/LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/julienstep9)

<p align="center"><img src="https://raw.githubusercontent.com/juju35/ha-hp/main/custom_components/hp/brand/icon.png" alt="HP Printer" width="120"></p>

Home Assistant integration for HP printers, fully local: status, ink or toner levels, pages remaining and page counters, read from the printer's built-in web server. When the printer is off or asleep, **its sensors keep their last values** instead of turning unavailable or unknown, even across a Home Assistant restart.

[![Open your Home Assistant instance and open a repository inside the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=juju35&repository=ha-hp&category=integration)

## Features

- **Never unavailable**: a printer that is off keeps every value it last reported (ink levels, counters, network); only the **Status** turns `off` and the **Online** sensor turns off
- **Survives restarts**: the last values are saved, so after a restart with the printer off the entities come back at once with them, and Home Assistant does not wait for the printer to start
- **No false "off"**: a lost request is tried again before the printer counts as off; a printer already off is not tried twice per poll
- **Clean statistics**: page counters never go down (a lower value from the firmware is ignored instead of being taken as a reset), and counters and ink are not read while the printer starts up or shuts down, when firmwares report zeros
- **Light on the printer**: the status is read at every poll (30 s by default), the page counters and ink levels every 5 minutes **and right after each job**, the network every 30 minutes, the identity every 6 hours and when the printer comes back
- **Nothing written when nothing changes**: a poll that finds nothing new writes no entity, so the recorder stores nothing
- **Unchanged documents not downloaded again**: counters, ink, identity and network are asked with their ETag, so an unchanged one costs a short `304` and no parsing (the status is always read in full, and cached documents are read in full again every 30 minutes, in case a firmware's ETags do not follow its content)
- **Unsupported documents not asked again and again**: a document the printer does not publish is asked again every 6 hours only
- **At most two requests at a time** to the printer's small web server
- **No dependency**: no Python package to install, nothing to conflict with Home Assistant
- **Status never unknown**: a status this integration does not know is `other`, with the printer's own status in an attribute; paper jams and open doors are recognized
- **Cartridge details** on each level sensor: state (`ok`, `low`, `very_low`…), cartridge number to buy, product number, installed; a cartridge taken out keeps its last level, with `installed: false`
- **Zeroconf discovery**, and a printer announced at a new address is followed there
- **Reconfigure** the address without removing the printer; a printer that changed address is detected and keeps its values instead of mixing them with another printer's
- **Firmware updates** shown on the device page
- **Diagnostics** with the address and serial number redacted
- English, French, German, Spanish, Italian, Dutch, Portuguese (European and Brazilian), Polish, Serbian (Cyrillic and Latin), Romanian, Danish, Swedish, Bulgarian, Russian, Ukrainian, Hungarian, Slovak, Czech, Slovenian, Latvian and Greek

### Compared with the core HP Printer integration

| | Core `hp_printer` | `hp` (this integration) |
|---|---|---|
| Printer off or asleep | Every entity **unavailable** | Last values kept, status `off`, **Online** off |
| Restart with the printer off | Setup retried, no entity | Entities at once with their last values |
| Unknown status | `unknown` | `other` + the printer's status in an attribute |
| Requests per poll (every minute) | All documents | Status only; the rest when it can have changed |
| Entity writes per poll | Every entity | None unless a value changed |
| Unchanged documents | Downloaded and parsed again | `304` with ETags |
| Cartridge taken out | Unavailable | Last level kept, `installed: false` |
| Address change | Remove and add the printer again | Reconfigure, or followed by discovery |
| Python dependency | `aiohpprinter` | None |

The two can be installed side by side (different domains), but use only one per printer.

## Supported printers

HP printers whose built-in web server publishes the `/DevMgmt/*.xml` documents: OfficeJet, OfficeJet Pro, ENVY, DeskJet, Smart Tank, LaserJet and Color LaserJet with a network connection. Which sensors are created depends on the model: a printer without a scanner or fax gets no scanner or fax sensor.

To check a printer, open `http://<printer address>/DevMgmt/ProductStatusDyn.xml` in a browser: it should show an XML document.

## Prerequisites

- Home Assistant 2025.8 or newer
- The printer on the network, with a fixed IP address given in your router (recommended)

## Installation

### Via the Marketplace (recommended)

Click the button below to add the repository directly:

[![Add to the Marketplace](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=juju35&repository=ha-hp&category=integration)

Then click **Install** and restart Home Assistant.

Or manually:

1. Open **Settings → Marketplace → Add from link** (top right; this needs a GitHub account connected)
2. Add `https://github.com/juju35/ha-hp` — Type: **Integration**
3. Open **HP Printer** and click **Install**
4. Restart Home Assistant

### Manual

Copy `custom_components/hp/` to `/config/custom_components/hp/`, then restart Home Assistant.

## Configuration

**Settings → Devices & services → Add integration → HP Printer**, or accept the discovered printer. The printer must be on when it is added.

| Field | Description |
|---|---|
| Host | IP address or hostname of the printer |
| Port | Empty for the default port (80, or 443 with HTTPS) |
| Use HTTPS | Only for printers whose web server answers over HTTPS only |

### Options

| Option | Default | Description |
|---|---|---|
| Status refresh interval | 30 s | How often the status is read (10 to 600 s). Counters and ink levels are read every 5 minutes and after each job, whatever this interval |

## Entities

Entities are named after the printer model, for example `sensor.hp_officejet_pro_9010_series_black_level`. Entity names stay in English in every language, so entity IDs do not depend on the language of Home Assistant.

| Entity | Notes |
|---|---|
| `sensor.<printer>_status` | `ready`, `processing`, `copying`, `scan_processing`, `cancel_job`, `in_power_save`, `initializing`, `shutting_down`, `off`, `tray_empty`, `paper_jam`, `close_door_or_cover`, `other`; attributes `raw_status`, `message`, `alerts` |
| `binary_sensor.<printer>_online` | Whether the printer answered the last poll |
| `sensor.<printer>_<color>_level` | `black`, `cyan`, `magenta`, `yellow`, `tri_color`, in %; attributes `state`, `installed`, `cartridge`, `product_number`, `low_threshold`, `type` |
| `sensor.<printer>_<color>_pages_remaining` | When the printer estimates it |
| `sensor.<printer>_<color>_pages_printed` | Disabled by default |
| `sensor.<printer>_printed_pages`, `_printed_black_and_white_pages`, `_printed_color_pages` | Page counters |
| `sensor.<printer>_scanned_pages`, `_copied_pages`, `_faxed_pages` | When the printer has a scanner, copier or fax |
| `sensor.<printer>_printed_single_sided_sheets`, `_printed_double_sided_sheets`, `_scanned_pages_from_document_feeder`, `_scanned_pages_from_glass`, `_scanned_double_sided_sheets` | Disabled by default |
| `sensor.<printer>_paper_jams`, `_paper_mispicks`, `_scanner_jams`, `_scanner_mispicks` | Diagnostic; mispicks and scanner counters disabled by default |
| `sensor.<printer>_last_seen` | Diagnostic, disabled by default: when the printer last answered (it changes at every poll, so it is the only entity written every 30 s) |
| `binary_sensor.<printer>_ethernet`, `_wi_fi`, `_usb` | Diagnostic: adapter connected (USB disabled by default) |
| `binary_sensor.<printer>_hp_cloud_registered`, `_hp_cloud_services` | Diagnostic |

### Automation examples

Ink running low, whether the printer is on or not:

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.office_printer_black_level
    below: 10
actions:
  - action: notify.mobile_app_phone
    data:
      message: >
        Black cartridge at {{ states('sensor.office_printer_black_level') }} %
        ({{ state_attr('sensor.office_printer_black_level', 'cartridge') }}).
```

Out of paper:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.office_printer_status
    to: tray_empty
actions:
  - action: notify.mobile_app_phone
    data:
      message: The printer is out of paper.
```

## How it works

- Documents: `ProductStatusDyn` (status), `ConsumableConfigDyn` and `ProductUsageDyn` (cartridges and counters), `ProductConfigDyn` (identity), `/IoMgmt/Adapters` and `ePrintConfigDyn` (network), over HTTP on port 80 (HTTPS optional, self-signed certificates accepted)
- A poll reads the status; when it does not answer twice in a row, the printer is off: the status turns `off`, the other values stay, and everything is read again when it answers. While it is off, one attempt per poll
- Another printer answering at the address (DHCP) is detected by its serial number: this printer counts as off and keeps its values, and the address is checked again every 5 minutes
- The data is saved in `.storage/hp.<entry id>` when it changes (and every 10 minutes for the last-seen time while the printer is on), and removed with the printer

## Development

```bash
pip install -r requirements_test.txt && pytest
pre-commit run --all-files
```

### Releasing

1. Bump the version in `custom_components/hp/manifest.json` and `const.py` (`VERSION`)
2. Add a `## <version>` section at the top of [CHANGELOG.md](https://github.com/juju35/ha-hp/blob/main/CHANGELOG.md)
3. Push to `main`: the **Release** workflow creates the tag and the GitHub release with the changelog section as notes

## Translations

The configuration, options and error messages follow the language of Home Assistant. Entity names (and status states) stay in English in every language, so that names and entity IDs are the same everywhere. Currently supported:

| Language | Code |
|---|---|
| English | `en` |
| Français | `fr` |
| Deutsch | `de` |
| Español | `es` |
| Italiano | `it` |
| Nederlands | `nl` |
| Português | `pt` |
| Português (Brasil) | `pt-BR` |
| Polski | `pl` |
| Română | `ro` |
| Dansk | `da` |
| Svenska | `sv` |
| Български | `bg` |
| Русский | `ru` |
| Українська | `uk` |
| Magyar | `hu` |
| Slovenčina | `sk` |
| Čeština | `cs` |
| Slovenščina | `sl` |
| Latviešu | `lv` |
| Ελληνικά | `el` |
| Српски | `sr` |
| Srpski (latinica) | `sr-Latn` |

Contributions for additional languages are welcome!

## License

[MIT](https://github.com/juju35/ha-hp/blob/main/LICENSE)

## Support

If you find this project useful, you can support its development:

<a href="https://buymeacoffee.com/julienstep9"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="50"></a>
