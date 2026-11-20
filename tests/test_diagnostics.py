"""Diagnostics: the printer's data, its host and serial number redacted."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hp.diagnostics import async_get_config_entry_diagnostics

from .conftest import HOST, SERIAL, FakePrinter


async def test_diagnostics_redact_host_and_serial(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry
) -> None:
    """The host and the serial number never leave in a diagnostics file; the rest of the data does."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    diag = await async_get_config_entry_diagnostics(hass, entry)

    text = repr(diag)
    assert HOST not in text
    assert SERIAL not in text
    assert diag["entry"]["host"] == "**REDACTED**"
    assert diag["data"]["device"]["serial_number"] == "**REDACTED**"
    assert diag["data"]["device"]["model"]
    assert isinstance(diag["unsupported_documents"], list)
    assert isinstance(diag["cached_documents"], list)
