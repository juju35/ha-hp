"""Polls an HP printer and keeps its last known data.

The printer being off is a normal state, not an error: the update never fails for it. The
entities keep the last values the printer reported (saved to disk, so they also survive a
restart with the printer off), the status turns ``off`` and the online sensor turns off.
"""

from __future__ import annotations

import asyncio
import time
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
    UNSUPPORTED_RETRY,
    USAGE_INTERVAL,
)

type HpConfigEntry = ConfigEntry[HpCoordinator]

# The saved data is also written at least this often while it only differs by "last_seen".
SAVE_LAST_SEEN_EVERY = 600


def empty_data() -> dict[str, Any]:
    """Return the data of a printer never seen yet."""
    return {
        "online": False,
        "last_seen": None,
        "device": {},
        "status": "off",
        "raw_status": None,
        "status_message": None,
        "alerts": [],
        "counters": {},
        "consumables": {},
        "connectivity": {},
    }


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
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._due: dict[str, datetime] = {}
        self._unsupported: dict[str, datetime] = {}
        self._last_saved = 0.0
        self._wrong_printer_logged = False

    async def async_load(self) -> bool:
        """Load the data saved by a previous run; return whether there was some for this printer."""
        stored = await self._store.async_load()
        if not stored or stored.get("serial_number") != self.config_entry.unique_id:
            return False
        data = empty_data()
        # Shown as saved (online and status included, so a restart does not flip them) until the
        # first poll, which runs right after setup and reads everything.
        data.update(stored.get("data") or {})
        self.data = data
        return True

    @property
    def unsupported(self) -> list[str]:
        """Return the documents the printer does not publish."""
        return list(self._unsupported)

    async def async_remove_store(self) -> None:
        """Delete the saved data (entry removed)."""
        await self._store.async_remove()

    def _save(self, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_saved < SAVE_LAST_SEEN_EVERY:
            return
        self._last_saved = now
        self._store.async_delay_save(
            lambda: {"serial_number": self.config_entry.unique_id, "data": self.data}, SAVE_DELAY
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

    async def _status(self) -> dict[str, Any]:
        try:
            return parse_status(await self.client.fetch(STATUS))
        except HpUnsupportedError:
            raise
        except HpError:
            # One lost request is not a printer turned off.
            await asyncio.sleep(RETRY_DELAY)
            return parse_status(await self.client.fetch(STATUS))

    async def _async_update_data(self) -> dict[str, Any]:
        previous = self.data or empty_data()
        data = deepcopy(previous)
        now = dt_util.utcnow()

        try:
            status = await self._status()
        except HpError as err:
            if not previous.get("last_seen"):
                # Never seen: nothing to show yet, setup is retried later.
                raise UpdateFailed(f"{self.client.host} does not answer: {err}") from err
            if previous.get("online"):
                LOGGER.info("%s is offline (%s), keeping its last values", self.client.host, err)
            self._go_offline(data)
            self._save(force=previous.get("online", False))
            return data

        came_back = not previous.get("online")
        if came_back:
            self._due.clear()
        was_busy = previous.get("status") in BUSY_STATUSES
        data.update(status)
        data["online"] = True
        data["last_seen"] = now.isoformat()

        job_ended = was_busy and data["status"] not in BUSY_STATUSES
        read_device = self._is_due("device", now)
        read_usage = job_ended or self._is_due("usage", now)
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
                    # The address now belongs to another printer (DHCP): this one is not there.
                    if not self._wrong_printer_logged:
                        LOGGER.warning(
                            "%s is now printer %s, not %s: give this printer a fixed address or reconfigure it",
                            self.client.host,
                            serial,
                            self.config_entry.unique_id,
                        )
                        self._wrong_printer_logged = True
                    data = deepcopy(previous)
                    self._go_offline(data)
                    return data
                self._wrong_printer_logged = False
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
        changed = {k: v for k, v in data.items() if k != "last_seen"} != {
            k: v for k, v in previous.items() if k != "last_seen"
        }
        self._save(force=changed)
        return data

    def _merge_usage(self, data: dict[str, Any], usage: Any, config: Any) -> None:
        if usage is not None:
            try:
                data["counters"] = {**data["counters"], **parse_counters(usage)}
            except HpError as err:
                LOGGER.debug("%s: %s", self.client.host, err)
        if usage is None and config is None:
            return
        fresh = parse_consumables(config, usage)
        merged: dict[str, dict[str, Any]] = {}
        for color in {*data["consumables"], *fresh}:
            entry = {**data["consumables"].get(color, {}), **fresh.get(color, {})}
            # A cartridge the printer stops listing (taken out) keeps its last values.
            if config is not None:
                entry["installed"] = color in fresh
            merged[color] = entry
        data["consumables"] = dict(sorted(merged.items()))

    def _go_offline(self, data: dict[str, Any]) -> None:
        data["online"] = False
        data["status"] = "off"
        data["raw_status"] = None
        data["status_message"] = None
        data["alerts"] = []
        # Its ETags restart with it, and everything is read again when it answers.
        self.client.clear_cache()
        self._due.clear()


async def _none() -> None:
    return None
