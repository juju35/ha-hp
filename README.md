# ha-hp

[![Marketplace](https://img.shields.io/badge/Marketplace-Custom-41BDF5.svg)](https://www.home-assistant.io/integrations/marketplace/)
[![Marketplace Validation](https://github.com/juju35/ha-hp/actions/workflows/hacs.yml/badge.svg)](https://github.com/juju35/ha-hp/actions/workflows/hacs.yml)
[![Validate](https://github.com/juju35/ha-hp/actions/workflows/validate.yml/badge.svg)](https://github.com/juju35/ha-hp/actions/workflows/validate.yml)
[![Lint](https://github.com/juju35/ha-hp/actions/workflows/lint.yml/badge.svg)](https://github.com/juju35/ha-hp/actions/workflows/lint.yml)
[![Release](https://img.shields.io/github/v/release/juju35/ha-hp)](https://github.com/juju35/ha-hp/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/juju35/ha-hp/blob/main/LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/julienstep9)

<p align="center"><img src="https://raw.githubusercontent.com/juju35/ha-hp/main/custom_components/hp/brand/icon.png" alt="HP Printer" width="120"></p>

Home Assistant integration for HP printers, fully local: status, ink or toner levels, pages remaining and page counters, read from the printer's built-in web server, and **scanning to PDF, JPEG or PNG** from the glass or the document feeder, multi-page PDFs included. When the printer is off or asleep, **its sensors keep their last values** instead of turning unavailable or unknown, even across a Home Assistant restart.

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
- **No dependency**: no Python package to install, nothing to conflict with Home Assistant (PNG uses Pillow, which Home Assistant ships)
- **Status never unknown**: a status this integration does not know is `other`, with the printer's own status in an attribute; paper jams and open doors are recognized
- **Scan to PDF, JPEG or PNG**: a **Scan** button with its settings (format, source, resolution, color mode, page size) and an `hp.scan` action for automations; glass, document feeder and double-sided feeder; **multi-page PDFs from the glass** with a **Scan and add page** button; files saved in the local media, the last scan shown by an image and a sensor
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
| Scanning | No | PDF (multi-page from the glass too), JPEG or PNG, glass or feeder, buttons and action |
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
| Keep scans not downloaded | 30 min | A scan file not downloaded is deleted after this time (a downloaded file is deleted at once); 0 keeps them |

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

## Scanning

Printers whose scanner answers eSCL (AirScan, at `http://<printer address>/eSCL/ScannerCapabilities`) get the scan entities; the choices offered are those the scanner reports.

| Entity | Notes |
|---|---|
| `button.<printer>_scan` | Scans with the settings below and saves a new file |
| `button.<printer>_scan_and_add_page` | Scans one more page and adds it to the last PDF: put the next page on the glass and press it, page after page |
| `select.<printer>_scan_format` | `pdf` (one file with every page), `jpeg` or `png` (one image per page) |
| `select.<printer>_scan_source` | `flatbed` (glass), `feeder`, `feeder_duplex` |
| `select.<printer>_scan_resolution` | The resolutions the scanner offers (300 by default) |
| `select.<printer>_scan_color_mode` | `color`, `grayscale`, `black_and_white` |
| `select.<printer>_scan_page_size` | `a4` (default), `letter`, `legal`, `max` (largest area of the source) |
| `sensor.<printer>_last_scan` | Time of the last scan; attributes `format`, `files`, `media_ids` (media source IDs, to show the images in the media browser), `download_paths` (to download the files, PDF included), `pages` |
| `image.<printer>_last_scanned_image` | First page of the last scan (PDF, JPEG or PNG) |

Files are saved in the `hp` folder of the local media (`/media/hp` on Home Assistant OS), named `scan_<date>_<time>.pdf` (`_1.jpg`, `_2.jpg`… per page in JPEG or PNG); an existing file is never overwritten. They show in **Media → Local media → hp**. The settings are kept across restarts.

### Action `hp.scan`

Every field is optional: those not given come from the select entities, and `device_id` is only needed with several printers.

```yaml
action: hp.scan
data:
  format: pdf              # pdf, jpeg, png
  source: feeder_duplex    # flatbed, feeder, feeder_duplex
  resolution: 300
  color_mode: grayscale    # color, grayscale, black_and_white
  page_size: a4            # a4, letter, legal, max
  filename: invoice_2026_11
  directory: /media/scans  # must be in allowlist_external_dirs (the media folders are)
  append: false            # true: add the pages to the last PDF instead of a new file
response_variable: scan    # scan.files, scan.media_ids, scan.download_paths, scan.pages
```

When a scan is saved, the event `hp_scan_completed` is fired with `device_id`, `format`, `files`, `media_ids`, `download_paths` and `pages`.

The files of each printer's last scan are downloaded from `/api/hp/scans/<entry>/<n>` (the paths in `download_paths`), by a signed-in user or a signed link: Home Assistant's media view only serves audio, video and images, not PDFs. **A file is deleted once downloaded** (once fully sent: an interrupted download keeps it), and leaves the last scan; a file never downloaded is deleted after 30 minutes (option **Keep scans not downloaded**; 0 keeps them), even across a restart. Only the files the integration wrote are deleted. [ha-printer-card](https://github.com/juju35/ha-printer-card) scans from the glass or the feeder and offers the download link.

PDF and PNG are made by the integration from the scanner's JPEG pages (embedded as is in the PDF, no new compression), which is what lets pages be added to a PDF. A scanner that only offers PDF gets its own PDF saved, without adding pages.

Errors are shown, translated, on the button or the action: printer off, scanner busy, feeder empty, a setting the scanner does not offer, folder not allowed.

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

Scan the feeder to PDF and say where it went:

```yaml
actions:
  - action: hp.scan
    data:
      source: feeder
      format: pdf
    response_variable: scan
  - action: notify.mobile_app_phone
    data:
      message: "Scan saved: {{ scan.files | join(', ') }}"
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

- Scans: eSCL, `POST /eSCL/ScanJobs` (JPEG pages, made into PDF or PNG here) with the settings, then `GET <job>/NextDocument` until the printer has no document left; the scanner and feeder states are checked first, a busy answer (`503`) is asked again, and a job that fails is deleted so the scanner is free. Capabilities are read with the identity, so the scan entities exist even while the printer is off
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

The configuration, options, scan action and error messages follow the language of Home Assistant. Entity names (and status states) stay in English in every language, so that names and entity IDs are the same everywhere. Currently supported:

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
