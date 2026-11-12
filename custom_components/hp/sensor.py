"""Sensors of the HP Printer integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import STATUSES
from .coordinator import HpConfigEntry, HpCoordinator
from .entity import HpEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HpCounterDescription(SensorEntityDescription):
    """A page counter, read from data["counters"][key]."""


def _counter(key: str, *, diagnostic: bool = False, enabled: bool = True) -> HpCounterDescription:
    return HpCounterDescription(
        key=key,
        translation_key=key,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
        entity_registry_enabled_default=enabled,
    )


COUNTERS: tuple[HpCounterDescription, ...] = (
    _counter("total_pages"),
    _counter("monochrome_pages"),
    _counter("color_pages"),
    _counter("simplex_sheets", enabled=False),
    _counter("duplex_sheets", enabled=False),
    _counter("jams", diagnostic=True),
    _counter("mispicks", diagnostic=True, enabled=False),
    _counter("scanned_pages"),
    _counter("scanned_adf_pages", enabled=False),
    _counter("scanned_flatbed_pages", enabled=False),
    _counter("scanned_duplex_sheets", enabled=False),
    _counter("scanner_jams", diagnostic=True, enabled=False),
    _counter("scanner_mispicks", diagnostic=True, enabled=False),
    _counter("copied_pages"),
    _counter("faxed_pages"),
)


@dataclass(frozen=True, kw_only=True)
class HpConsumableDescription(SensorEntityDescription):
    """A value of one cartridge, read from data["consumables"][color][key]."""


CONSUMABLE_SENSORS: tuple[HpConsumableDescription, ...] = (
    HpConsumableDescription(
        key="level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    HpConsumableDescription(key="pages_remaining", state_class=SensorStateClass.MEASUREMENT),
    HpConsumableDescription(
        key="pages_printed",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
)
COLORS = ("black", "cyan", "magenta", "yellow", "tri_color")

STATUS = SensorEntityDescription(
    key="status",
    translation_key="status",
    device_class=SensorDeviceClass.ENUM,
    options=list(STATUSES),
)
LAST_SCAN = SensorEntityDescription(
    key="last_scan",
    translation_key="last_scan",
    device_class=SensorDeviceClass.TIMESTAMP,
)
LAST_SEEN = SensorEntityDescription(
    key="last_seen",
    translation_key="last_seen",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors, then those for data the printer starts to report later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        data = coordinator.data
        entities: list[SensorEntity] = []
        if "status" not in known:
            entities += [HpStatusSensor(coordinator), HpLastSeenSensor(coordinator)]
            known.add("status")
        if "last_scan" not in known and data["scanner"]:
            entities.append(HpLastScanSensor(coordinator))
            known.add("last_scan")
        for description in COUNTERS:
            if description.key not in known and description.key in data["counters"]:
                known.add(description.key)
                entities.append(HpCounterSensor(coordinator, description))
        for color, consumable in data["consumables"].items():
            if color not in COLORS:
                continue
            for description in CONSUMABLE_SENSORS:
                key = f"{color}_{description.key}"
                if key not in known and description.key in consumable:
                    known.add(key)
                    entities.append(HpConsumableSensor(coordinator, color, description))
        if entities:
            async_add_entities(entities)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class HpStatusSensor(HpEntity, SensorEntity):
    """What the printer is doing; "off" while it does not answer."""

    entity_description = STATUS

    def __init__(self, coordinator: HpCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, STATUS.key)

    @property
    def native_value(self) -> str:
        """Return the status."""
        status = self.coordinator.data.get("status")
        return status if status in STATUSES else "other"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the printer's own status, message and alerts."""
        data = self.coordinator.data
        return {
            "raw_status": data.get("raw_status"),
            "message": data.get("status_message"),
            "alerts": data.get("alerts") or [],
        }


class HpLastSeenSensor(HpEntity, SensorEntity):
    """When the printer last answered.

    Disabled by default: it changes at every poll, so it is the only entity written (and
    recorded) every 30 s. The others are only written when a value changes.
    """

    entity_description = LAST_SEEN

    def __init__(self, coordinator: HpCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, LAST_SEEN.key)

    async def async_added_to_hass(self) -> None:
        """Follow every answer of the printer, not only data changes."""
        await super().async_added_to_hass()
        listeners = self.coordinator.answer_listeners
        listeners.append(self.async_write_ha_state)
        self.async_on_remove(lambda: listeners.remove(self.async_write_ha_state))

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the last answer."""
        return self.coordinator.last_seen


class HpLastScanSensor(HpEntity, SensorEntity):
    """When the last scan was saved, with its files."""

    entity_description = LAST_SCAN

    def __init__(self, coordinator: HpCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, LAST_SCAN.key)

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the last scan."""
        last = self.coordinator.data.get("last_scan")
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the format, files, media source IDs (to download them) and pages of the last scan."""
        last = self.coordinator.data.get("last_scan") or {}
        return {
            "format": last.get("format"),
            "files": last.get("files", []),
            "media_ids": last.get("media_ids", []),
            "pages": last.get("pages"),
        }


class HpCounterSensor(HpEntity, SensorEntity):
    """A page counter, kept while the printer is off."""

    entity_description: HpCounterDescription

    def __init__(self, coordinator: HpCoordinator, description: HpCounterDescription) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        """Return the counter."""
        return self.coordinator.data["counters"].get(self.entity_description.key)


class HpConsumableSensor(HpEntity, SensorEntity):
    """A value of one cartridge, kept while the printer is off or the cartridge is out."""

    entity_description: HpConsumableDescription

    def __init__(self, coordinator: HpCoordinator, color: str, description: HpConsumableDescription) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, f"{color}_{description.key}")
        self.entity_description = description
        self._color = color
        self._attr_translation_key = f"{color}_{description.key}"

    @property
    def _consumable(self) -> dict[str, Any]:
        return self.coordinator.data["consumables"].get(self._color, {})

    @property
    def native_value(self) -> float | int | None:
        """Return the value."""
        return self._consumable.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the cartridge details on the level sensor."""
        if self.entity_description.key != "level":
            return None
        consumable = self._consumable
        return {
            key: consumable[key]
            for key in ("state", "installed", "cartridge", "product_number", "low_threshold", "type")
            if key in consumable
        }
