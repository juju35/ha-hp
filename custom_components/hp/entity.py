"""Base entity of the HP Printer integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HpCoordinator


class HpEntity(CoordinatorEntity[HpCoordinator]):
    """An entity of one printer, available even while the printer is off."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HpCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        device = coordinator.data["device"]
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            configuration_url=str(coordinator.client.base_url),
            manufacturer="HP",
            model=device.get("model"),
            model_id=device.get("product_number"),
            name=device.get("model") or entry.title,
            serial_number=device.get("serial_number"),
            sw_version=device.get("firmware"),
        )

    @property
    def available(self) -> bool:
        """Always available: a printer that is off keeps its last values."""
        return True
