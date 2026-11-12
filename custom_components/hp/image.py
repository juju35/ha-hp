"""Last scanned image of the HP Printer integration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import HpConfigEntry, HpCoordinator
from .document import read_pdf
from .entity import HpEntity

PARALLEL_UPDATES = 0

LAST_IMAGE = ImageEntityDescription(key="last_scanned_image", translation_key="last_scanned_image")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the image once the printer reports a scanner."""
    coordinator = entry.runtime_data
    added = False

    @callback
    def _add() -> None:
        nonlocal added
        if not added and coordinator.data["scanner"]:
            added = True
            async_add_entities([HpLastScannedImage(coordinator)])

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class HpLastScannedImage(HpEntity, ImageEntity):
    """The first page of the last scan, whatever its format."""

    entity_description = LAST_IMAGE

    def __init__(self, coordinator: HpCoordinator) -> None:
        """Initialize the image."""
        HpEntity.__init__(self, coordinator, LAST_IMAGE.key)
        ImageEntity.__init__(self, coordinator.hass)

    @property
    def _last(self) -> dict[str, str] | None:
        return self.coordinator.data.get("last_image")

    @property
    def image_last_updated(self) -> datetime | None:
        """Return when the image was scanned."""
        last = self._last
        return dt_util.parse_datetime(last["time"]) if last else None

    @property
    def content_type(self) -> str:
        """PNG for a PNG scan, JPEG otherwise (the first page of a PDF is its JPEG)."""
        last = self._last
        return "image/png" if last and last["file"].endswith(".png") else "image/jpeg"

    async def async_image(self) -> bytes | None:
        """Return the image, read from its file."""
        last = self._last
        if not last:
            return None
        return await self.hass.async_add_executor_job(_read, Path(last["file"]))

    @property
    def available(self) -> bool:
        """Always available, like every entity of the printer."""
        return True


def _read(path: Path) -> bytes | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if path.suffix != ".pdf":
        return data
    # A PDF written by this integration holds its pages' JPEGs; one from the scanner itself shows nothing.
    pages = read_pdf(data)
    return pages[0][0] if pages else None
