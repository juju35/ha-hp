"""HP Printer: local integration for HP printers that keeps their values while they are off."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SSL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HpClient
from .const import DOMAIN
from .coordinator import HpConfigEntry, HpCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: HpConfigEntry) -> bool:
    """Set up a printer.

    With data saved by a previous run, setup does not wait for the printer: the entities come up
    at once with their last values, and the first poll runs in the background. Home Assistant
    starts just as fast with the printer off.
    """
    client = HpClient(
        host=entry.data[CONF_HOST],
        session=async_get_clientsession(hass, verify_ssl=False),
        port=entry.data.get(CONF_PORT),
        ssl=entry.data.get(CONF_SSL, False),
    )
    coordinator = HpCoordinator(hass, entry, client)
    if await coordinator.async_load():
        entry.async_create_background_task(hass, coordinator.async_refresh(), f"{DOMAIN} first refresh")
    else:
        await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    @callback
    def _update_device() -> None:
        """Follow firmware updates in the device registry."""
        device = coordinator.data["device"]
        registry = dr.async_get(hass)
        # Looked up by config entry: identifiers are no longer unique across entries (HA 2026.10).
        devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
        if not devices:
            return
        entry_device = devices[0]
        changes = {
            attr: value
            for attr, value in (("sw_version", device.get("firmware")), ("model", device.get("model")))
            if value and getattr(entry_device, attr) != value
        }
        if changes:
            registry.async_update_device(entry_device.id, **changes)

    entry.async_on_unload(coordinator.async_add_listener(_update_device))
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: HpConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HpConfigEntry) -> bool:
    """Unload a printer."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: HpConfigEntry) -> None:
    """Delete the saved data of a removed printer."""
    client = HpClient(host=entry.data[CONF_HOST], session=async_get_clientsession(hass))
    await HpCoordinator(hass, entry, client).async_remove_store()
