# Changelog

## 1.0.0 (2026-11-12)

First release: a local integration for HP printers, built to replace the core HP Printer integration where it is fragile.

- Sensors keep their last values while the printer is off or asleep, and after a restart with the printer off (saved data): no more unavailable or unknown entities; the **Status** turns `off` and a new **Online** sensor turns off
- Home Assistant starts without waiting for the printer when its data was saved
- A lost status request is tried again before the printer counts as off
- Tiered polling: status every 30 s (option), counters and ink levels every 5 minutes and after each job, network every 30 minutes, identity every 6 hours and when the printer comes back
- ETags: unchanged documents answered with a `304`; documents the printer does not publish asked again every 6 hours only; at most two requests at a time
- Status `other` (with the printer's status in an attribute) instead of `unknown`; paper jams and open doors recognized
- Cartridge attributes: state, cartridge number, product number, installed, low threshold; a cartridge taken out keeps its last level
- Zeroconf discovery following address changes, reconfigure flow, detection of another printer at the address, firmware updates on the device page, diagnostics
- No Python dependency
