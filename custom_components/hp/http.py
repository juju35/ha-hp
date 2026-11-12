"""Download of the last scan's files.

Home Assistant's media view only serves audio, video and images: a PDF in the media folder is
answered 404. This view serves the files of a printer's last scan (and only those), to an
authenticated user or a signed link.
"""

from __future__ import annotations

import mimetypes
from http import HTTPStatus
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.http import KEY_HASS

from .const import DOMAIN

DOWNLOAD_URL = "/api/hp/scans/{entry_id}/{index}"


def download_path(entry_id: str, index: int) -> str:
    """Return the path that downloads one file of a printer's last scan."""
    return DOWNLOAD_URL.format(entry_id=entry_id, index=index)


class HpScanView(HomeAssistantView):
    """Serves a file of a printer's last scan as an attachment."""

    url = DOWNLOAD_URL
    name = "api:hp:scans"
    requires_auth = True

    async def get(self, request: web.Request, entry_id: str, index: str) -> web.StreamResponse:
        """Return the file, or 404 for anything that is not a file of the last scan."""
        hass = request.app[KEY_HASS]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        files = (entry.runtime_data.data.get("last_scan") or {}).get("files", [])
        if not index.isdigit() or int(index) >= len(files):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        path = Path(files[int(index)])
        if not await hass.async_add_executor_job(path.is_file):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return web.FileResponse(
            path,
            headers={
                "Content-Type": content_type,
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "Cache-Control": "no-store",
            },
        )
