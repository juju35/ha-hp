# HP Printer — Agent Context

## Purpose
Home Assistant custom integration (domain `hp`) for HP printers, fully local through the printer's embedded web server (LEDM `DevMgmt` XML documents). Rewrite of the core `hp_printer` integration whose main rule is: **entities never turn unavailable or unknown because the printer is off**.

## Architecture

```
custom_components/hp/
├── __init__.py      # Entry setup: HpClient + HpCoordinator; async_load() from the Store → entities at once and first refresh as a background task, else async_config_entry_first_refresh (offline and never seen → ConfigEntryNotReady); listener updating sw_version/model in the device registry; update listener reloads (options, zeroconf host); async_remove_entry deletes the Store
├── api.py           # HpClient.fetch(path): aiohttp, semaphore MAX_PARALLEL_REQUESTS, If-None-Match/If-Modified-Since cache (304 → cached document; never for STATUS, entries older than CACHE_MAX_AGE refetched), 404/405/501 → HpUnsupportedError, connection/timeout → HpConnectionError; XML parsed with stdlib ElementTree, namespaces stripped; JSON for /IoMgmt/Adapters on some firmwares; parse_status/device/consumables/counters/adapters/eprint return plain JSON-able dicts; map_status → STATUSES (core keys kept, "other" fallback)
├── coordinator.py   # DataUpdateCoordinator[dict], always_update=False: data holds only what the printer reports (last_seen is a coordinator attribute, pushed to answer_listeners) so an unchanged poll writes no entity; never raises once the printer was seen (offline = data["online"] False, status "off", values kept); status retried once only when it was online (RETRY_DELAY); counters never go down; no usage read in UNSETTLED_STATUSES; another serial at the address → offline, checked again every WRONG_PRINTER_RETRY; tiers in self._due (device DEVICE_INTERVAL, usage USAGE_INTERVAL or job ended = status leaves BUSY_STATUSES, network NETWORK_INTERVAL), all due again when the printer comes back; unsupported documents skipped until UNSUPPORTED_RETRY; another serial at the address → kept offline; Store saved (SAVE_DELAY) on change, last_seen every SAVE_LAST_SEEN_EVERY; consumables merged per color, "installed" False when the config document stops listing one
├── escl.py          # eSCL scanning: parse_capabilities (sources flatbed/feeder/feeder_duplex, formats, resolutions, color modes → data["scanner"], read in the device tier), build_settings (checked against capabilities, 1/300 inch regions, PAGE_SIZES), async_scan: ScannerStatus check (busy, feeder empty) → POST ScanJobs (job from Location, else from ScannerStatus) → NextDocument until 404 (503 retried BUSY_RETRIES), DELETE on failure; HpClient.request() bypasses the cache and the semaphore
├── scan.py          # hp.scan action (registered in async_setup, response optional) and async_scan_to_files: checks (scanner, online, allowed folder, scan_lock), files written in the executor without overwriting, coordinator.async_set_scan (last_scan, last_image), event hp_scan_completed
├── button.py / select.py / image.py  # Scan button; scan settings selects (RestoreEntity, coordinator.scan_settings); last scanned image (JPEG file read from disk)
├── entity.py        # HpEntity: unique_id <serial>_<key>, device info, available always True
├── sensor.py        # Status (enum STATUSES + raw_status/message/alerts), last_seen, COUNTERS (data["counters"]), consumable level/pages_remaining/pages_printed per color (data["consumables"]); created when the key first appears
├── binary_sensor.py # Online (always), ethernet/wifi/usb/cloud_registered/cloud_services (data["connectivity"])
├── config_flow.py   # user (host, port, ssl), zeroconf (_ipp/_ipps hp*) following new addresses, reconfigure (abort wrong_printer), options (scan_interval)
├── diagnostics.py   # Entry, data, unsupported and cached documents; host and serial redacted
└── const.py / manifest.json / icons.json / translations/*.json / brand/
```

## Rules
- Never put a value that changes at every poll in `data`: it would write every entity at every poll.
- Never let the update raise for an offline printer once it has been seen: values must stay. Only a never-seen printer raises UpdateFailed (setup retried).
- A new value = a key in the snapshot (JSON-serializable, it is saved) + a description; new entity keys go in translations/en.json and icons.json only (entity names are not translated; tests/test_translations.py checks en.json ↔ entities ↔ icons, and that the other languages have the same config/options keys).
- No third-party requirement: keep the parsers on the standard library.

## Release
Bump `version` in manifest.json and `VERSION` in const.py, add the CHANGELOG.md section; pushing to main publishes `vX.Y.Z` with `hp.zip`.

## Tests
`pip install -r requirements_test.txt && pytest`. `FakePrinter` (tests/conftest.py) replaces the HTTP session: documents from tests/fixtures, ETags, power (`online`), 404s (`unsupported`), dropped requests (`fail_next`). Coordinator refreshes run as background tasks: tests wait with `async_block_till_done(wait_background_tasks=True)`. CI also runs the suite on HA 2025.8.0.
