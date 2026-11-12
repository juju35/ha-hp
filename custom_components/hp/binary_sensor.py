"""Binary sensors of the HP Printer integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HpConfigEntry, HpCoordinator
from .entity import HpEntity

PARALLEL_UPDATES = 0

ONLINE = BinarySensorEntityDescription(
    key="online",
    translation_key="online",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)

# Read from data["connectivity"][key]; off while the printer is offline (the last report is kept for its return).
CONNECTIVITY: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="ethernet",
        translation_key="ethernet",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="wifi",
        translation_key="wifi",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="usb",
        translation_key="usb",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    BinarySensorEntityDescription(
        key="cloud_registered",
        translation_key="cloud_registered",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="cloud_services",
        translation_key="cloud_services",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the online sensor, and the others as the printer reports them."""
    coordinator = entry.runtime_data
    known: set[str] = {ONLINE.key}
    async_add_entities([HpOnlineSensor(coordinator)])

    @callback
    def _add_new() -> None:
        connectivity = coordinator.data["connectivity"]
        new = [d for d in CONNECTIVITY if d.key not in known and d.key in connectivity]
        if new:
            known.update(d.key for d in new)
            async_add_entities(HpConnectivitySensor(coordinator, d) for d in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class HpOnlineSensor(HpEntity, BinarySensorEntity):
    """Whether the printer answers."""

    entity_description = ONLINE

    def __init__(self, coordinator: HpCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, ONLINE.key)

    @property
    def is_on(self) -> bool:
        """Return whether the printer answered the last poll."""
        return bool(self.coordinator.data.get("online"))


class HpConnectivitySensor(HpEntity, BinarySensorEntity):
    """A network adapter or cloud setting, as last reported; off while the printer is offline."""

    def __init__(self, coordinator: HpCoordinator, description: BinarySensorEntityDescription) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the last reported value, off when the printer does not answer.

        A printer that is off is connected to nothing: its adapters and cloud services are off, not
        the last value it reported.
        """
        if not self.coordinator.data.get("online"):
            return False
        return self.coordinator.data["connectivity"].get(self.entity_description.key)
