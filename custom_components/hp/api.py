"""Local client for the embedded web server (EWS) of HP printers.

HP printers publish their state as small XML documents (the LEDM ``DevMgmt`` interface). This
module reads them over HTTP and turns them into plain dicts that can be stored as JSON: no
third-party dependency, namespaces ignored, and every missing or odd element simply left out,
since models and firmwares differ in what they report.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any
from xml.etree.ElementTree import Element, ParseError, fromstring

import aiohttp
from yarl import URL

from .const import CONNECT_TIMEOUT, LOGGER, MAX_PARALLEL_REQUESTS, REQUEST_TIMEOUT

STATUS = "/DevMgmt/ProductStatusDyn.xml"
DEVICE = "/DevMgmt/ProductConfigDyn.xml"
CONSUMABLES = "/DevMgmt/ConsumableConfigDyn.xml"
USAGE = "/DevMgmt/ProductUsageDyn.xml"
ADAPTERS = "/IoMgmt/Adapters"
EPRINT = "/ePrint/ePrintConfigDyn.xml"

# Consumable label codes (config document) and marker colors (usage document) → color key.
LABEL_COLORS = {"K": "black", "C": "cyan", "M": "magenta", "Y": "yellow", "CMY": "tri_color"}
MARKER_COLORS = {
    "black": "black",
    "cyan": "cyan",
    "magenta": "magenta",
    "yellow": "yellow",
    "cyanmagentayellow": "tri_color",
    "tricolor": "tri_color",
}

PRINTER_COUNTERS = {
    "TotalImpressions": "total_pages",
    "MonochromeImpressions": "monochrome_pages",
    "ColorImpressions": "color_pages",
    "SimplexSheets": "simplex_sheets",
    "DuplexSheets": "duplex_sheets",
    "JamEvents": "jams",
    "MispickEvents": "mispicks",
}
SCANNER_COUNTERS = {
    "ScanImages": "scanned_pages",
    "AdfImages": "scanned_adf_pages",
    "FlatbedImages": "scanned_flatbed_pages",
    "DuplexSheets": "scanned_duplex_sheets",
    "JamEvents": "scanner_jams",
    "MispickEvents": "scanner_mispicks",
}
COPY_COUNTERS = {"TotalImpressions": "copied_pages"}
FAX_COUNTERS = {"TotalImpressions": "faxed_pages"}

STATUS_MAP = {
    "ready": "ready",
    "idle": "ready",
    "processing": "processing",
    "printing": "processing",
    "copying": "copying",
    "scanprocessing": "scan_processing",
    "scanning": "scan_processing",
    "canceljob": "cancel_job",
    "cancelling": "cancel_job",
    "inpowersave": "in_power_save",
    "powersave": "in_power_save",
    "sleep": "in_power_save",
    "initializing": "initializing",
    "inksysteminitializing": "initializing",
    "shuttingdown": "shutting_down",
    "off": "off",
    "trayempty": "tray_empty",
    "closedoororcover": "close_door_or_cover",
}
ADAPTER_KEYS = {"eth0": "ethernet", "wifi0": "wifi", "usb0": "usb"}


class HpError(Exception):
    """The printer could not answer a request."""


class HpConnectionError(HpError):
    """The printer is unreachable: off, asleep, or not on the network."""


class HpUnsupportedError(HpError):
    """The printer does not publish this document."""


# Documents never asked with a condition: the status is tiny and must never be stale.
UNCONDITIONAL = frozenset({STATUS})
# A cached document is fetched in full again after this long, in case a firmware gives an ETag
# that does not follow its content.
CACHE_MAX_AGE = 1800.0


@dataclass
class _Cached:
    etag: str | None
    last_modified: str | None
    document: Any
    stored_at: float


@dataclass
class HpClient:
    """Reads the EWS documents of one printer.

    Documents are fetched with ``If-None-Match`` / ``If-Modified-Since`` when the printer gave an
    ETag or a date: an unchanged document costs a 304 and no parsing. A semaphore keeps the small
    embedded web server from more than ``MAX_PARALLEL_REQUESTS`` requests at a time.
    """

    host: str
    session: aiohttp.ClientSession
    port: int | None = None
    ssl: bool = False
    _cache: dict[str, _Cached] = field(default_factory=dict, init=False, repr=False)
    _semaphore: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(MAX_PARALLEL_REQUESTS), init=False, repr=False
    )

    @property
    def base_url(self) -> URL:
        """Return the printer's EWS address."""
        scheme = "https" if self.ssl else "http"
        return URL.build(scheme=scheme, host=self.host.strip("[]"), port=self.port or (443 if self.ssl else 80))

    @property
    def cached_paths(self) -> list[str]:
        """Return the documents currently cached with an ETag or a date."""
        return list(self._cache)

    def clear_cache(self) -> None:
        """Forget cached documents (the printer restarted: its ETags restart too)."""
        self._cache.clear()

    async def fetch(self, path: str) -> Element | dict[str, Any]:
        """Return the parsed document at ``path`` (XML root without namespaces, or JSON object)."""
        cached = self._cache.get(path)
        if cached is not None and time.monotonic() - cached.stored_at > CACHE_MAX_AGE:
            cached = None
        headers = {}
        if cached is not None:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified
        url = self.base_url.with_path(path)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, sock_connect=CONNECT_TIMEOUT)
        try:
            async with (
                self._semaphore,
                self.session.get(url, headers=headers, timeout=timeout, ssl=False, allow_redirects=True) as response,
            ):
                if response.status == 304 and cached is not None:
                    return cached.document
                if response.status in (404, 405, 501):
                    raise HpUnsupportedError(f"{path}: HTTP {response.status}")
                if response.status >= 400:
                    raise HpError(f"{path}: HTTP {response.status}")
                body = await response.read()
                content_type = response.content_type
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
        except (TimeoutError, aiohttp.ClientConnectionError, OSError) as err:
            raise HpConnectionError(f"{path}: {err.__class__.__name__} {err}".strip()) from err
        except aiohttp.ClientError as err:
            raise HpError(f"{path}: {err}") from err

        document = _parse_body(path, body, content_type)
        if (etag or last_modified) and path not in UNCONDITIONAL:
            self._cache[path] = _Cached(etag, last_modified, document, time.monotonic())
        else:
            self._cache.pop(path, None)
        return document


def _parse_body(path: str, body: bytes, content_type: str) -> Element | dict[str, Any]:
    if "json" in content_type or "javascript" in content_type or body.lstrip()[:1] == b"{":
        try:
            data = json.loads(body)
        except ValueError as err:
            raise HpError(f"{path}: invalid JSON") from err
        if not isinstance(data, dict):
            raise HpError(f"{path}: unexpected JSON")
        return data
    try:
        root = fromstring(body)
    except ParseError as err:
        raise HpError(f"{path}: invalid XML ({err})") from err
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.rsplit("}", 1)[1]
    return root


# --- Helpers on namespace-free elements -------------------------------------------------------


def _text(element: Element | None, path: str) -> str | None:
    if element is None:
        return None
    value = element.findtext(path)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _int(element: Element | None, path: str) -> int | None:
    value = _text(element, path)
    if value is None:
        return None
    try:
        number = int(float(value))
    except ValueError:
        return None
    return number if number >= 0 else None


def _percent(element: Element | None, path: str) -> int | float | None:
    value = _text(element, path)
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    # Printers report -128, 255… when they do not know the level.
    if not 0 <= number <= 100:
        return None
    return int(number) if number.is_integer() else round(number, 1)


def _snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value.replace(" ", "")).lower()


def _root(document: Element | dict[str, Any], tag: str) -> Element | None:
    if isinstance(document, Element) and document.tag == tag:
        return document
    return None


# --- Parsers: each returns the part of the snapshot it covers ---------------------------------


def parse_status(document: Element | dict[str, Any]) -> dict[str, Any]:
    """Status category, message and alert IDs from ProductStatusDyn."""
    root = _root(document, "ProductStatusDyn")
    if root is None:
        raise HpError("ProductStatusDyn: unexpected document")
    statuses = root.findall("Status")
    raw = _text(statuses[0], "StatusCategory") if statuses else None
    message = _text(statuses[0], "LocString") if statuses else None
    alerts = [
        alert_id
        for alert in root.findall("AlertTable/Alert")
        if (alert_id := _text(alert, "ProductStatusAlertID") or _text(alert, "AlertID"))
    ]
    return {"status": map_status(raw), "raw_status": raw, "status_message": message, "alerts": alerts}


def map_status(raw: str | None) -> str:
    """Map an HP StatusCategory to one of the status sensor's values."""
    if not raw:
        return "other"
    key = raw.replace("_", "").replace(" ", "").lower()
    if key in STATUS_MAP:
        return STATUS_MAP[key]
    if "jam" in key:
        return "paper_jam"
    if "door" in key or "cover" in key:
        return "close_door_or_cover"
    if "trayempty" in key or "outofpaper" in key or "paperout" in key:
        return "tray_empty"
    if "powersave" in key or "sleep" in key:
        return "in_power_save"
    if "init" in key:
        return "initializing"
    return "other"


def parse_device(document: Element | dict[str, Any]) -> dict[str, Any]:
    """Identity from ProductConfigDyn."""
    root = _root(document, "ProductConfigDyn")
    if root is None:
        raise HpError("ProductConfigDyn: unexpected document")
    info = root.find("ProductInformation")
    return {
        key: value
        for key, value in {
            "model": _text(info, "MakeAndModel") or _text(info, "MakeAndModelBase"),
            "serial_number": _text(info, "SerialNumber"),
            "product_number": _text(info, "ProductNumber"),
            "firmware": _text(info, "Version/Revision"),
        }.items()
        if value is not None
    }


def parse_consumables(
    config: Element | dict[str, Any] | None, usage: Element | dict[str, Any] | None
) -> dict[str, dict[str, Any]]:
    """Ink or toner cartridges, keyed by color, merged from ConsumableConfigDyn and ProductUsageDyn."""
    consumables: dict[str, dict[str, Any]] = {}

    config_root = _root(config, "ConsumableConfigDyn") if config is not None else None
    if config_root is not None:
        for item in config_root.findall("ConsumableInfo"):
            color = LABEL_COLORS.get(_text(item, "ConsumableLabelCode") or "")
            kind = (_text(item, "ConsumableTypeEnum") or "").lower()
            if color is None or "printhead" in kind:
                continue
            state = _text(item, "ConsumableLifeState/ConsumableState")
            consumables[color] = {
                key: value
                for key, value in {
                    "level": _percent(item, "ConsumablePercentageLevelRemaining"),
                    "state": _snake(state) if state else None,
                    "type": kind or None,
                    "cartridge": _text(item, "ConsumableSelectibilityNumber"),
                    "product_number": _text(item, "ProductNumber"),
                    "low_threshold": _percent(item, "ConsumableLowThreshold"),
                }.items()
                if value is not None
            }

    usage_root = _root(usage, "ProductUsageDyn") if usage is not None else None
    if usage_root is not None:
        for item in usage_root.findall("ConsumableSubunit/Consumable"):
            marker = (_text(item, "MarkerColor") or "").replace(" ", "").lower()
            color = MARKER_COLORS.get(marker)
            if color is None:
                continue
            entry = consumables.setdefault(color, {})
            if "level" not in entry and (raw := _percent(item, "ConsumableRawPercentageLevelRemaining")) is not None:
                entry["level"] = raw
            for key, path in (("pages_remaining", "EstimatedPagesRemaining"), ("pages_printed", "TotalImpressions")):
                if (value := _int(item, path)) is not None:
                    entry[key] = value

    return {color: data for color, data in consumables.items() if data}


def installed_colors(config: Element | dict[str, Any]) -> set[str]:
    """Colors of the cartridges ConsumableConfigDyn lists as present (not "missing")."""
    root = _root(config, "ConsumableConfigDyn")
    if root is None:
        return set()
    colors = set()
    for item in root.findall("ConsumableInfo"):
        color = LABEL_COLORS.get(_text(item, "ConsumableLabelCode") or "")
        state = (_text(item, "ConsumableLifeState/ConsumableState") or "").lower()
        if color is not None and state != "missing":
            colors.add(color)
    return colors


def parse_counters(document: Element | dict[str, Any]) -> dict[str, int]:
    """Page counters from ProductUsageDyn."""
    root = _root(document, "ProductUsageDyn")
    if root is None:
        raise HpError("ProductUsageDyn: unexpected document")
    counters: dict[str, int] = {}
    for subunit, mapping in (
        ("PrinterSubunit", PRINTER_COUNTERS),
        ("ScannerEngineSubunit", SCANNER_COUNTERS),
        ("CopyApplicationSubunit", COPY_COUNTERS),
        ("FaxApplicationSubunit", FAX_COUNTERS),
    ):
        element = root.find(subunit)
        if element is None:
            continue
        for tag, key in mapping.items():
            if (value := _int(element, tag)) is not None:
                counters[key] = value
    return counters


def parse_adapters(document: Element | dict[str, Any]) -> dict[str, bool]:
    """Connection of the Ethernet, Wi-Fi and USB adapters from /IoMgmt/Adapters (XML or JSON)."""
    adapters: list[tuple[str | None, str | None]] = []
    if isinstance(document, Element):
        adapters = [
            (_text(item, "HardwareConfig/Name"), _text(item, "HardwareConfig/IsConnected"))
            for item in document.findall("Adapter")
        ]
    else:
        items = (document.get("Adapters") or {}).get("Adapter") if isinstance(document.get("Adapters"), dict) else None
        for item in items if isinstance(items, list) else [items] if isinstance(items, dict) else []:
            hardware = item.get("HardwareConfig") if isinstance(item, dict) else None
            if isinstance(hardware, dict):
                adapters.append((hardware.get("Name"), str(hardware.get("IsConnected", "")) or None))
    result: dict[str, bool] = {}
    for name, connected in adapters:
        key = ADAPTER_KEYS.get((name or "").lower())
        if key is not None and connected is not None:
            result[key] = connected.lower() == "true"
    return result


def parse_eprint(document: Element | dict[str, Any]) -> dict[str, bool]:
    """HP cloud (ePrint) registration from ePrintConfigDyn."""
    root = _root(document, "ePrintConfigDyn")
    if root is None:
        raise HpError("ePrintConfigDyn: unexpected document")
    result: dict[str, bool] = {}
    if (state := _text(root, "RegistrationState")) is not None:
        result["cloud_registered"] = state.lower() == "registered"
    if (switch := _text(root, "CloudServicesSwitch/Status")) is not None:
        result["cloud_services"] = switch.lower() == "enabled"
    return result


async def async_identify(client: HpClient) -> dict[str, Any]:
    """Return the printer identity, checking that its status document answers too (config flow)."""
    device = parse_device(await client.fetch(DEVICE))
    parse_status(await client.fetch(STATUS))
    LOGGER.debug("Identified %s at %s", device.get("model"), client.host)
    return device
