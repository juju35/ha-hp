# Changelog

## 1.1.0 (2026-11-12)

### Improvements
- Scans in a media folder get their media source ID (`media_ids`) in the `hp.scan` response, the `hp_scan_completed` event and the **Last scan** sensor, which also gives the number of `pages`: a dashboard card can show or download the file (ha-printer-card 2.12 does).

### Fixes
- The scan folder is checked outside Home Assistant's event loop (the check reads the disk).

## 1.0.1 (2026-11-12)

### Fixes
- Status `other` (unknown state on the card) on printers that list several statuses, an informative one first: an OfficeJet Pro 9010 reports `genuineHP` ("Cart. HP Instant Ink") before `ready`. The status shown is now the most important known one (a stop, then work, then rest), with its message; `other` only when none is known. Alerts are listed once each.
- Cartridge states keep acronyms whole: `new_genuine_hp` instead of `new_genuine_h_p`.

## 1.0.0 (2026-11-12)

First release: a local integration for HP printers, built to replace the core HP Printer integration where it is fragile.

- Sensors keep their last values while the printer is off or asleep, and after a restart with the printer off (saved data): no more unavailable or unknown entities; the **Status** turns `off` and a new **Online** sensor turns off
- Home Assistant starts without waiting for the printer when its data was saved
- A lost status request is tried again before the printer counts as off
- Tiered polling: status every 30 s (option), counters and ink levels every 5 minutes and after each job, network every 30 minutes, identity every 6 hours and when the printer comes back
- ETags: unchanged documents answered with a `304` (never for the status; full read every 30 minutes anyway); documents the printer does not publish asked again every 6 hours only; at most two requests at a time
- Status `other` (with the printer's status in an attribute) instead of `unknown`; paper jams and open doors recognized
- Cartridge attributes: state, cartridge number, product number, installed, low threshold; a cartridge taken out keeps its last level
- Zeroconf discovery following address changes, reconfigure flow, detection of another printer at the address, firmware updates on the device page, diagnostics
- Nothing written when a poll finds nothing new: no entity write and nothing recorded every 30 s; the **Last seen** sensor, the one value that changes at every poll, is disabled by default
- Page counters never go down (a lower firmware value is ignored, so long-term statistics see no false reset); counters and ink not read while the printer starts up or shuts down
- Scanning to PDF, JPEG or PNG through eSCL (AirScan): **Scan** button with format, source (glass, feeder, double-sided feeder), resolution, color mode and page size selects kept across restarts; `hp.scan` action with a response (saved files, pages); files in the local media `hp` folder, never overwritten; **Last scan** sensor, **Last scanned image** (first page, PDF included) and `hp_scan_completed` event
- Multi-page PDFs from the glass: **Scan and add page** button and `append` field add the next page to the last PDF; PDFs are built from the scanner's JPEG pages without recompression, PNG converted with Home Assistant's Pillow
- No Python dependency
