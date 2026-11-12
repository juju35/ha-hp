"""Polls an HP printer and keeps its last known data.

The printer being off is a normal state, not an error: the update never fails for it. The
entities keep the last values the printer reported (saved to disk, so they also survive a
restart with the printer off), the status turns ``off`` and the online sensor turns off.

``data`` only holds what the printer reports, so a poll that finds nothing new leaves it equal
and the entities are not written again (``always_update=False``). The time of the last answer,
which changes at every poll, is kept beside it in ``last_seen``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    ADAPTERS,
    CONSUMABLES,
    DEVICE,
    EPRINT,
    STATUS,
    USAGE,
    HpClient,
    HpError,
    HpUnsupportedError,
    installed_colors,
    parse_adapters,
    parse_consumables,
    parse_counters,
    parse_device,
    parse_eprint,
    parse_status,
)
from .const import (
    BUSY_STATUSES,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_INTERVAL,
    DOMAIN,
    LOGGER,
    NETWORK_INTERVAL,
    RETRY_DELAY,
    SAVE_DELAY,
    STORAGE_VERSION,
    UNSETTLED_STATUSES,
    UNSUPPORTED_RETRY,
    USAGE_INTERVAL,
    WRONG_PRINTER_RETRY,
)

type HpConfigEntry = ConfigEntry[HpCoordinator]

# While online and unchanged, the last-seen time is still saved this often.
SAVE_LAST_SEEN_EVERY = 600


def empty_data() -> dict[str, Any]:
    """Return the data of a printer never seen yet."""
    return {
        "online": False,
        "device": {},
        "status": "off",
        "raw_status": None,
        "status_message": None,
        "alerts": [],
        "counters": {},
        "consumables": {},
        "connectivity": {},
    }


def store_for(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Return the store of a printer's saved data."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")


class HpCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Reads the printer in tiers: status at each poll, the rest only when it can have changed."""

    config_entry: HpConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HpConfigEntry, client: HpClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.host}",
            update_interval=timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            always_update=False,
        )
        self.client = client
        self.last_seen: datetime | None = None
        # Called after every poll that got an answer, even when data did not change.
        self.answer_listeners: list[Callable[[], None]] = []
        self._store = store_for(hass, entry.entry_id)
        self._due: dict[str, datetime] = {}
        self._unsupported: dict[str, datetime] = {}
        self._last_saved = 0.0
        # Serial number answering at the address when it is not this printer's (DHCP).
        self._wrong_printer: str | None = None

    async def async_load(self) -> bool:
        """Load the data saved by a previous run; return whether there was some for this printer."""
        stored = await self._store.async_load()
        if not stored or stored.get("serial_number") != self.config_entry.unique_id:
            return False
        saved = dict(stored.get("data") or {})
        last_seen = stored.get("last_seen") or saved.get("last_seen")
        self.last_seen = dt_util.parse_datetime(last_seen) if last_seen else None
        # Shown as saved (online and status included, so a restart does not flip them) until the
        # first poll, which runs right after setup and reads everything.
        data = empty_data()
        data.update({key: value for key, value in saved.items() if key in data})
        self.data = data
        return True

    @property
    def unsupported(self) -> list[str]:
        """Return the documents the printer does not publish."""
        return list(self._unsupported)

    def _save(self) -> None:
        self._last_saved = time.monotonic()
        self._store.async_delay_save(
            lambda: {
                "serial_number": self.config_entry.unique_id,
                "last_seen": self.last_seen.isoformat() if self.last_seen else None,
                "data": self.data,
            },
            SAVE_DELAY,
        )

    def _is_due(self, group: str, now: datetime) -> bool:
        return now >= self._due.get(group, now)

    async def _optional(self, path: str, now: datetime) -> Any:
        """Fetch a document the printer may not publish; None when it doesn't or fails this time."""
        if (retry := self._unsupported.get(path)) is not None and now < retry:
            return None
        try:
            document = await self.client.fetch(path)
        except HpUnsupportedError:
            LOGGER.debug("%s: %s not published, asked again in %s", self.client.host, path, UNSUPPORTED_RETRY)
            self._unsupported[path] = now + UNSUPPORTED_RETRY
            return None
        except HpError as err:
            LOGGER.debug("%s: %s", self.client.host, err)
            return None
        self._unsupported.pop(path, None)
        return document

    async def _status(self, retry: bool) -> dict[str, Any]:
        try:
            return parse_status(await self.client.fetch(STATUS))
        except HpUnsupportedError:
            raise
        except HpError:
            # One lost request is not a printer turned off. A printer already off is not tried
            # twice: that would only double the wait on a host that is not there.
            if not retry:
                raise
            await asyncio.sleep(RETRY_DELAY)
            return parse_status(await self.client.fetch(STATUS))

    async def _async_update_data(self) -> dict[str, Any]:
        previous = self.data or empty_data()
        was_online = bool(previous.get("online"))
        now = dt_util.utcnow()

        try:
            status = await self._status(retry=was_online)
        except HpError as err:
            if self.last_seen is None:
                # Never seen: nothing to show yet, setup is retried later.
                raise UpdateFailed(f"{self.client.host} does not answer: {err}") from err
            if was_online:
                LOGGER.info("%s is offline (%s), keeping its last values", self.client.host, err)
            return self._offline(previous)

        if self._wrong_printer is not None and not self._is_due("device", now):
            # Another printer still holds the address: nothing read before the next check.
            return previous

        data = deepcopy(previous)
        came_back = not was_online
        if came_back:
            self._due.clear()
        was_busy = previous.get("status") in BUSY_STATUSES
        data.update(status)
        data["online"] = True

        # Counters and ink are read right after a job, but not while the printer starts or shuts
        # down: firmwares report zeros then.
        settled = data["status"] not in UNSETTLED_STATUSES
        job_ended = was_busy and data["status"] not in BUSY_STATUSES
        read_device = self._is_due("device", now)
        read_usage = settled and (job_ended or self._is_due("usage", now))
        read_network = self._is_due("network", now)

        device, usage, consumables, adapters, eprint = await asyncio.gather(
            self._optional(DEVICE, now) if read_device else _none(),
            self._optional(USAGE, now) if read_usage else _none(),
            self._optional(CONSUMABLES, now) if read_usage else _none(),
            self._optional(ADAPTERS, now) if read_network else _none(),
            self._optional(EPRINT, now) if read_network else _none(),
        )

        if device is not None:
            try:
                identity = parse_device(device)
            except HpError as err:
                LOGGER.debug("%s: %s", self.client.host, err)
            else:
                serial = identity.get("serial_number")
                if serial and self.config_entry.unique_id and serial != self.config_entry.unique_id:
                    if self._wrong_printer != serial:
                        LOGGER.warning(
                            "%s is now printer %s, not %s: give this printer a fixed address or reconfigure it",
                            self.client.host,
                            serial,
                            self.config_entry.unique_id,
                        )
                    self._wrong_printer = serial
                    offline = self._offline(previous)
                    self._due["device"] = now + WRONG_PRINTER_RETRY
                    return offline
                if self._wrong_printer is not None:
                    LOGGER.info("%s is printer %s again", self.client.host, serial)
                    self._wrong_printer = None
                data["device"] = {**data["device"], **identity}
                self._due["device"] = now + DEVICE_INTERVAL

        if read_usage:
            self._merge_usage(data, usage, consumables)
            self._due["usage"] = now + USAGE_INTERVAL

        if read_network:
            connectivity = dict(data["connectivity"])
            for document, parser in ((adapters, parse_adapters), (eprint, parse_eprint)):
                if document is None:
                    continue
                try:
                    connectivity.update(parser(document))
                except HpError as err:
                    LOGGER.debug("%s: %s", self.client.host, err)
            data["connectivity"] = connectivity
            self._due["network"] = now + NETWORK_INTERVAL

        if came_back:
            LOGGER.info("%s is online", self.client.host)
        self.last_seen = now
        for listener in self.answer_listeners:
            listener()
        if data != previous or time.monotonic() - self._last_saved >= SAVE_LAST_SEEN_EVERY:
            self._save()
        return data

    def _merge_usage(self, data: dict[str, Any], usage: Any, config: Any) -> None:
        if usage is not None:
            try:
                fresh_counters = parse_counters(usage)
            except HpError as err:
                LOGGER.debug("%s: %s", self.client.host, err)
            else:
                counters = dict(data["counters"])
                for key, value in fresh_counters.items():
                    # Page counters never go down: a lower value is a firmware glitch, and taken
                    # as a reset it would break the long-term statistics.
                    if value >= counters.get(key, 0):
                        counters[key] = value
                    else:
                        LOGGER.debug("%s: %s went down (%s → %s), ignored", self.client.host, key, counters[key], value)
                data["counters"] = counters
        if usage is None and config is None:
            return
        fresh = parse_consumables(config, usage)
        installed = installed_colors(config) if config is not None else None
        merged: dict[str, dict[str, Any]] = {}
        for color in {*data["consumables"], *fresh}:
            entry = {**data["consumables"].get(color, {}), **fresh.get(color, {})}
            # A cartridge taken out keeps its last values, marked as not installed.
            if installed is not None:
                entry["installed"] = color in installed
            merged[color] = entry
        data["consumables"] = dict(sorted(merged.items()))

    def _offline(self, previous: dict[str, Any]) -> dict[str, Any]:
        """Return the data of a printer that does not answer; saved once, when it goes off."""
        if not previous.get("online"):
            return previous
        data = deepcopy(previous)
        data["online"] = False
        data["status"] = "off"
        data["raw_status"] = None
        data["status_message"] = None
        data["alerts"] = []
        # Its ETags restart with it, and everything is read again when it answers.
        self.client.clear_cache()
        self._due.clear()
        self._save()
        return data


async def _none() -> None:
    return None
