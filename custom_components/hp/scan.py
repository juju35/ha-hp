"""Scan to PDF or JPEG files: the hp.scan action and the Scan button."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .api import HpError
from .const import DOMAIN, LOGGER
from .coordinator import HpConfigEntry, HpCoordinator
from .escl import COLOR_MODES, EXTENSIONS, FORMATS, PAGE_SIZES, SOURCES, ScanError, ScanSettings, async_scan

EVENT_SCAN_COMPLETED = "hp_scan_completed"
SERVICE_SCAN = "scan"
ATTR_DEVICE_ID = "device_id"
ATTR_DIRECTORY = "directory"
ATTR_FILENAME = "filename"

SCAN_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE_ID): cv.string,
        vol.Optional("format"): vol.In(list(FORMATS)),
        vol.Optional("source"): vol.In(list(SOURCES)),
        vol.Optional("resolution"): vol.All(vol.Coerce(int), vol.Range(min=50, max=1200)),
        vol.Optional("color_mode"): vol.In(list(COLOR_MODES)),
        vol.Optional("page_size"): vol.In([*PAGE_SIZES, "max"]),
        vol.Optional(ATTR_DIRECTORY): cv.string,
        vol.Optional(ATTR_FILENAME): vol.All(cv.string, vol.Match(r"^[^/\\:*?\"<>|]+$")),
    }
)


def default_directory(hass: HomeAssistant) -> Path:
    """Return where scans are saved by default: the "hp" folder of the local media."""
    media = hass.config.media_dirs.get("local") or hass.config.path("media")
    return Path(media) / "hp"


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the hp.scan action."""

    async def _scan(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call.data.get(ATTR_DEVICE_ID))
        overrides = {
            key: call.data[key]
            for key in ("format", "source", "resolution", "color_mode", "page_size")
            if key in call.data
        }
        settings = replace(coordinator.scan_settings, **overrides)
        result = await async_scan_to_files(
            hass,
            coordinator,
            settings,
            directory=call.data.get(ATTR_DIRECTORY),
            filename=call.data.get(ATTR_FILENAME),
        )
        return result if call.return_response else None

    hass.services.async_register(
        DOMAIN, SERVICE_SCAN, _scan, schema=SCAN_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )


def _coordinator(hass: HomeAssistant, device_id: str | None) -> HpCoordinator:
    entries: list[HpConfigEntry] = [
        entry for entry in hass.config_entries.async_loaded_entries(DOMAIN) if hasattr(entry, "runtime_data")
    ]
    if device_id is not None:
        device = dr.async_get(hass).async_get(device_id)
        entries = [entry for entry in entries if device is not None and entry.entry_id in device.config_entries]
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="device_not_found")
    elif len(entries) != 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="device_required")
    return entries[0].runtime_data


async def async_scan_to_files(
    hass: HomeAssistant,
    coordinator: HpCoordinator,
    settings: ScanSettings,
    *,
    directory: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Scan, save the documents and return what was saved."""
    capabilities = coordinator.data.get("scanner")
    if not capabilities:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_scanner")
    if not coordinator.data.get("online"):
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="printer_offline")
    folder = Path(directory) if directory else default_directory(hass)
    if not hass.config.is_allowed_path(str(folder)):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="directory_not_allowed",
            translation_placeholders={"directory": str(folder)},
        )
    if coordinator.scan_lock.locked():
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="scanner_busy")

    async with coordinator.scan_lock:
        try:
            result = await async_scan(coordinator.client, settings, capabilities)
        except ScanError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key=err.reason, translation_placeholders={"error": str(err)}
            ) from err
        except HpError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="scan_failed", translation_placeholders={"error": str(err)}
            ) from err

    now = dt_util.now()
    stem = filename or now.strftime("scan_%Y%m%d_%H%M%S")
    extension = EXTENSIONS[result.format]
    files = await hass.async_add_executor_job(_write, folder, stem, extension, result.documents)
    LOGGER.info("%s: scan saved to %s", coordinator.client.host, ", ".join(files))

    last_scan = {"time": now.isoformat(), "format": result.format, "files": files}
    last_image = {"time": now.isoformat(), "file": files[0]} if result.format == "jpeg" else None
    coordinator.async_set_scan(last_scan, last_image)

    hass.bus.async_fire(
        EVENT_SCAN_COMPLETED,
        {
            "device_id": _device_id(hass, coordinator),
            "format": result.format,
            "files": files,
            "pages": len(files) if result.format == "jpeg" else None,
        },
    )
    return {"format": result.format, "files": files}


def _device_id(hass: HomeAssistant, coordinator: HpCoordinator) -> str | None:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), coordinator.config_entry.entry_id)
    return devices[0].id if devices else None


def _write(folder: Path, stem: str, extension: str, documents: list[bytes]) -> list[str]:
    """Write the documents without overwriting anything; return their paths."""
    folder.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    for index, document in enumerate(documents, start=1):
        base = stem if len(documents) == 1 else f"{stem}_{index}"
        path = folder / f"{base}.{extension}"
        counter = 2
        while path.exists():
            path = folder / f"{base}_{counter}.{extension}"
            counter += 1
        path.write_bytes(document)
        files.append(str(path))
    return files
