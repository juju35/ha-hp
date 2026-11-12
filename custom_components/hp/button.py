"""Scan button of the HP Printer integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HpConfigEntry, HpCoordinator
from .entity import HpEntity
from .scan import async_scan_to_files

PARALLEL_UPDATES = 1

SCAN = ButtonEntityDescription(key="scan", translation_key="scan")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the Scan button once the printer reports a scanner."""
    coordinator = entry.runtime_data
    added = False

    @callback
    def _add() -> None:
        nonlocal added
        if not added and coordinator.data["scanner"]:
            added = True
            async_add_entities([HpScanButton(coordinator)])

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class HpScanButton(HpEntity, ButtonEntity):
    """Scan with the settings of the scan select entities."""

    entity_description = SCAN

    def __init__(self, coordinator: HpCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, SCAN.key)

    async def async_press(self) -> None:
        """Scan and save the documents."""
        await async_scan_to_files(self.hass, self.coordinator, self.coordinator.scan_settings)
