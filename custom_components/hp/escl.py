"""Scanning through eSCL (AirScan), the scan protocol of HP printers' embedded web server.

A scan is: ``POST /eSCL/ScanJobs`` with the settings, which answers ``201`` and the job's
address, then ``GET <job>/NextDocument`` once per document until the printer answers 404 (the
feeder is empty). A PDF comes back as one document with every page; JPEG as one image per page.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any
from xml.etree.ElementTree import Element
from xml.sax.saxutils import escape

from yarl import URL

from .api import HpClient, HpError, _int, _parse_body, _root, _text

CAPABILITIES = "/eSCL/ScannerCapabilities"
SCANNER_STATUS = "/eSCL/ScannerStatus"
SCAN_JOBS = "/eSCL/ScanJobs"

FORMATS = {"pdf": "application/pdf", "jpeg": "image/jpeg"}
EXTENSIONS = {"pdf": "pdf", "jpeg": "jpg"}
COLOR_MODES = {"color": "RGB24", "grayscale": "Grayscale8", "black_and_white": "BlackAndWhite1"}
SOURCES = {"flatbed": "Platen", "feeder": "Feeder", "feeder_duplex": "Feeder"}
DEFAULT_RESOLUTIONS = [75, 100, 150, 200, 300, 600]
# Page sizes in 1/300 inch, the unit of eSCL scan regions.
PAGE_SIZES = {"a4": (2480, 3508), "letter": (2550, 3300), "legal": (2550, 4200)}

# A document can take a while to come out of the scanner, page after page.
DOCUMENT_TIMEOUT = 180.0
# The printer answers 503 while the scanner is warming up or the job not ready yet.
BUSY_RETRIES = 30
BUSY_DELAY = 2.0


class ScanError(HpError):
    """The scan could not be done; ``reason`` is a translation key."""

    def __init__(self, reason: str, detail: str = "") -> None:
        """Initialize the error."""
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass
class ScanSettings:
    """What to scan, in this integration's terms."""

    format: str = "pdf"
    source: str = "flatbed"
    resolution: int = 300
    color_mode: str = "color"
    page_size: str = "a4"


@dataclass
class ScanResult:
    """The documents of one scan job."""

    format: str
    documents: list[bytes] = field(default_factory=list)


def parse_capabilities(document: Element | dict[str, Any]) -> dict[str, Any]:
    """Sources, formats, resolutions and color modes the scanner offers, in this integration's terms."""
    root = _root(document, "ScannerCapabilities")
    if root is None:
        raise HpError("ScannerCapabilities: unexpected document")
    sources: dict[str, dict[str, int]] = {}
    formats: set[str] = set()
    resolutions: set[int] = set()
    color_modes: set[str] = set()
    for key, path in (
        ("flatbed", "Platen/PlatenInputCaps"),
        ("feeder", "Adf/AdfSimplexInputCaps"),
        ("feeder_duplex", "Adf/AdfDuplexInputCaps"),
    ):
        caps = root.find(path)
        if caps is None:
            continue
        sources[key] = {size: value for size in ("MaxWidth", "MaxHeight") if (value := _int(caps, size)) is not None}
        for element in caps.iter():
            text = (element.text or "").strip()
            if element.tag in ("DocumentFormat", "DocumentFormatExt"):
                formats.update(name for name, mime in FORMATS.items() if mime == text)
            elif element.tag == "ColorMode":
                color_modes.update(name for name, mode in COLOR_MODES.items() if mode == text)
            elif element.tag == "XResolution" and text.isdigit():
                resolutions.add(int(text))
    if not sources:
        raise HpError("ScannerCapabilities: no input source")
    # A firmware that lists nothing still scans in the eSCL basics.
    return {
        "sources": sources,
        "formats": sorted(formats) or sorted(FORMATS),
        "resolutions": sorted(resolutions) or DEFAULT_RESOLUTIONS,
        "color_modes": [mode for mode in COLOR_MODES if mode in color_modes] or ["color", "grayscale"],
    }


def build_settings(settings: ScanSettings, capabilities: dict[str, Any]) -> bytes:
    """Return the eSCL ScanSettings document for a job, checked against the capabilities."""
    source = capabilities["sources"].get(settings.source)
    if source is None:
        raise ScanError("unsupported_source", settings.source)
    if settings.format not in capabilities["formats"]:
        raise ScanError("unsupported_format", settings.format)
    if settings.resolution not in capabilities["resolutions"]:
        raise ScanError("unsupported_resolution", str(settings.resolution))
    if settings.color_mode not in capabilities["color_modes"]:
        raise ScanError("unsupported_color_mode", settings.color_mode)
    max_width = source.get("MaxWidth", PAGE_SIZES["letter"][0])
    max_height = source.get("MaxHeight", PAGE_SIZES["a4"][1])
    width, height = PAGE_SIZES.get(settings.page_size, (max_width, max_height))
    width, height = min(width, max_width), min(height, max_height)
    mime = FORMATS[settings.format]
    duplex = (
        f"<scan:Duplex>{'true' if settings.source == 'feeder_duplex' else 'false'}</scan:Duplex>"
        if settings.source != "flatbed"
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"'
        ' xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">'
        "<pwg:Version>2.0</pwg:Version>"
        "<scan:Intent>Document</scan:Intent>"
        "<pwg:ScanRegions><pwg:ScanRegion>"
        f"<pwg:Height>{height}</pwg:Height><pwg:Width>{width}</pwg:Width>"
        "<pwg:XOffset>0</pwg:XOffset><pwg:YOffset>0</pwg:YOffset>"
        "<pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>"
        "</pwg:ScanRegion></pwg:ScanRegions>"
        f"<pwg:InputSource>{SOURCES[settings.source]}</pwg:InputSource>"
        f"<pwg:DocumentFormat>{escape(mime)}</pwg:DocumentFormat>"
        f"<scan:DocumentFormatExt>{escape(mime)}</scan:DocumentFormatExt>"
        f"<scan:XResolution>{settings.resolution}</scan:XResolution>"
        f"<scan:YResolution>{settings.resolution}</scan:YResolution>"
        f"<scan:ColorMode>{COLOR_MODES[settings.color_mode]}</scan:ColorMode>"
        f"{duplex}"
        "</scan:ScanSettings>"
    ).encode()


def _scanner_state(document: Element | dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Scanner state, feeder state, and the address of a job in progress, from ScannerStatus."""
    root = _root(document, "ScannerStatus")
    if root is None:
        return None, None, None
    job = None
    for info in root.findall("Jobs/JobInfo"):
        if (_text(info, "JobState") or "").lower() == "processing":
            job = _text(info, "JobUri")
    return _text(root, "State"), _text(root, "AdfState"), job


async def _status(client: HpClient) -> tuple[str | None, str | None, str | None]:
    status, headers, body = await client.request("GET", SCANNER_STATUS)
    if status != 200:
        return None, None, None
    try:
        return _scanner_state(_parse_body(SCANNER_STATUS, body, headers.get("Content-Type", "")))
    except HpError:
        return None, None, None


async def async_scan(client: HpClient, settings: ScanSettings, capabilities: dict[str, Any]) -> ScanResult:
    """Run one scan job and return its documents."""
    payload = build_settings(settings, capabilities)

    state, adf_state, _ = await _status(client)
    if state and state.lower() != "idle":
        raise ScanError("scanner_busy", state)
    if settings.source != "flatbed" and adf_state and "loaded" not in adf_state.lower():
        raise ScanError("feeder_empty", adf_state)

    status, headers, _ = await client.request("POST", SCAN_JOBS, data=payload)
    if status == 503:
        raise ScanError("scanner_busy", "HTTP 503")
    if status not in (200, 201):
        raise ScanError("scan_failed", f"HTTP {status}")
    location = next((value for key, value in headers.items() if key.lower() == "location"), None)
    job = URL(location).path if location else None
    if not job:
        # Some firmwares do not give the job's address: it is in the scanner status.
        _, _, job = await _status(client)
    if not job:
        raise ScanError("scan_failed", "no job address")
    job = job.rstrip("/")

    result = ScanResult(format=settings.format)
    try:
        while True:
            document = await _next_document(client, job)
            if document is None:
                break
            result.documents.append(document)
            if settings.format == "pdf" or settings.source == "flatbed":
                # A PDF holds every page; the glass gives one page.
                break
    except BaseException:
        # Free the scanner for the next job.
        await _cancel(client, job)
        raise
    if not result.documents:
        raise ScanError("scan_failed", "no document")
    return result


async def _next_document(client: HpClient, job: str) -> bytes | None:
    """Return the next document of the job, or None when there is none left."""
    for _ in range(BUSY_RETRIES):
        status, _, body = await client.request("GET", f"{job}/NextDocument", timeout=DOCUMENT_TIMEOUT)
        if status == 200 and body:
            return body
        if status in (404, 410):
            return None
        if status != 503:
            raise ScanError("scan_failed", f"NextDocument HTTP {status}")
        await asyncio.sleep(BUSY_DELAY)
    raise ScanError("scanner_busy", "document not ready")


async def _cancel(client: HpClient, job: str) -> None:
    with contextlib.suppress(HpError):
        await client.request("DELETE", job)
