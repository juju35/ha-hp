"""Diagnostics of the HP Printer integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import HpConfigEntry

TO_REDACT = {CONF_HOST, "serial_number"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: HpConfigEntry) -> dict[str, Any]:
    """Return the entry, the printer's last data and what the integration knows of its documents."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "data": async_redact_data(coordinator.data, TO_REDACT),
        "unsupported_documents": sorted(coordinator.unsupported),
        "cached_documents": sorted(coordinator.client.cached_paths),
    }
