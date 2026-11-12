"""Scan settings of the HP Printer integration, used by the Scan button and as defaults of hp.scan."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import HpConfigEntry, HpCoordinator
from .entity import HpEntity
from .escl import PAGE_SIZES

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HpScanSelectDescription(SelectEntityDescription):
    """A scan setting: the ScanSettings field, its choices, and the preferred default."""

    field: str
    options_fn: Callable[[dict[str, Any]], list[str]]
    preferred: tuple[str, ...]


SCAN_SELECTS: tuple[HpScanSelectDescription, ...] = (
    HpScanSelectDescription(
        key="scan_format",
        translation_key="scan_format",
        field="format",
        options_fn=lambda caps: list(caps["formats"]),
        preferred=("pdf",),
    ),
    HpScanSelectDescription(
        key="scan_source",
        translation_key="scan_source",
        field="source",
        options_fn=lambda caps: list(caps["sources"]),
        preferred=("flatbed",),
    ),
    HpScanSelectDescription(
        key="scan_resolution",
        translation_key="scan_resolution",
        field="resolution",
        options_fn=lambda caps: [str(value) for value in caps["resolutions"]],
        preferred=("300", "200", "150"),
    ),
    HpScanSelectDescription(
        key="scan_color_mode",
        translation_key="scan_color_mode",
        field="color_mode",
        options_fn=lambda caps: list(caps["color_modes"]),
        preferred=("color",),
    ),
    HpScanSelectDescription(
        key="scan_page_size",
        translation_key="scan_page_size",
        field="page_size",
        options_fn=lambda caps: [*PAGE_SIZES, "max"],
        preferred=("a4",),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the scan settings once the printer reports a scanner."""
    coordinator = entry.runtime_data
    added = False

    @callback
    def _add() -> None:
        nonlocal added
        if not added and coordinator.data["scanner"]:
            added = True
            async_add_entities(HpScanSelect(coordinator, description) for description in SCAN_SELECTS)

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class HpScanSelect(HpEntity, SelectEntity, RestoreEntity):
    """A scan setting, kept across restarts."""

    entity_description: HpScanSelectDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HpCoordinator, description: HpScanSelectDescription) -> None:
        """Initialize the select."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def options(self) -> list[str]:
        """Return what the scanner offers."""
        return self.entity_description.options_fn(self.coordinator.data["scanner"])

    @property
    def current_option(self) -> str:
        """Return the setting, or the preferred one the scanner offers."""
        value = str(getattr(self.coordinator.scan_settings, self.entity_description.field))
        if value in self.options:
            return value
        return next((option for option in self.entity_description.preferred if option in self.options), self.options[0])

    async def async_added_to_hass(self) -> None:
        """Restore the last choice."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._apply(last.state if last is not None and last.state in self.options else self.current_option)

    async def async_select_option(self, option: str) -> None:
        """Change the setting."""
        self._apply(option)
        self.async_write_ha_state()

    def _apply(self, option: str) -> None:
        field = self.entity_description.field
        value: Any = int(option) if field == "resolution" else option
        self.coordinator.scan_settings = replace(self.coordinator.scan_settings, **{field: value})
