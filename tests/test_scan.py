"""Scanning: hp.scan action, Scan button, scan settings and last scan entities."""

from __future__ import annotations

import asyncio
import io
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from PIL import Image
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events, mock_restore_cache

from custom_components.hp.const import DOMAIN
from custom_components.hp.document import read_pdf

from .conftest import JOB, FakePrinter

P = "hp_officejet_pro_9010_series"


def _jpeg(width: int = 2480, height: int = 3508, color: str = "white") -> bytes:
    with io.BytesIO() as out:
        Image.new("RGB", (width, height), color).save(out, "JPEG")
        return out.getvalue()


JPEG_1 = _jpeg(color="white")
JPEG_2 = _jpeg(color="gray")
PDF = b"%PDF-1.7 from the scanner"


@pytest.fixture(autouse=True)
def media(hass: HomeAssistant, tmp_path: Path) -> Path:
    """Local media in a temporary folder, allowed like in Home Assistant."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    return tmp_path


@pytest.fixture(autouse=True)
def no_busy_delay():
    """Ask a busy scanner again at once."""
    with patch("custom_components.hp.escl.BUSY_DELAY", 0):
        yield


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _view_done(hass: HomeAssistant) -> None:
    for _ in range(20):
        await asyncio.sleep(0.01)
    await hass.async_block_till_done()


async def _scan(hass: HomeAssistant, **data):
    return await hass.services.async_call(DOMAIN, "scan", data, blocking=True, return_response=True)


async def test_scan_entities(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """A printer with an eSCL scanner gets the button, the settings and the last scan entities."""
    await _setup(hass, entry)
    assert hass.states.get(f"button.{P}_scan")
    fmt = hass.states.get(f"select.{P}_scan_format")
    assert fmt.state == "pdf"
    assert fmt.attributes["options"] == ["pdf", "jpeg", "png"]
    assert hass.states.get(f"select.{P}_scan_source").attributes["options"] == ["flatbed", "feeder", "feeder_duplex"]
    assert hass.states.get(f"select.{P}_scan_resolution").attributes["options"] == ["75", "200", "300", "600"]
    assert hass.states.get(f"select.{P}_scan_resolution").state == "300"
    assert hass.states.get(f"select.{P}_scan_color_mode").attributes["options"] == ["color", "grayscale"]
    assert hass.states.get(f"select.{P}_scan_page_size").state == "a4"
    assert hass.states.get(f"image.{P}_last_scanned_image")
    assert hass.states.get(f"sensor.{P}_last_scan").state == "unknown"


async def test_no_scanner_no_entities(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """A printer without eSCL gets no scan entity, and the action says so."""
    printer.unsupported.add("/eSCL/ScannerCapabilities")
    await _setup(hass, entry)
    assert hass.states.get(f"button.{P}_scan") is None
    with pytest.raises(ServiceValidationError) as err:
        await _scan(hass)
    assert err.value.translation_key == "no_scanner"


async def test_scan_pdf(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, media: Path) -> None:
    """A PDF scan of the glass: the scanner's JPEG page in a PDF, in the media folder."""
    await _setup(hass, entry)
    events = async_capture_events(hass, "hp_scan_completed")
    printer.pages = [JPEG_1]
    response = await _scan(hass, filename="invoice")
    path = media / "hp" / "invoice.pdf"
    assert response == {
        "format": "pdf",
        "files": [str(path)],
        "media_ids": ["media-source://media_source/local/hp/invoice.pdf"],
        "download_paths": [f"/api/hp/scans/{entry.entry_id}/0"],
        "pages": 1,
    }
    pages = read_pdf(path.read_bytes())
    assert [page[0] for page in pages] == [JPEG_1]
    # 2480 x 3508 pixels at 300 dpi: an A4 page.
    assert (round(pages[0][1]), round(pages[0][2])) == (595, 842)
    settings = printer.scan_jobs[0].decode()
    for part in (
        "<pwg:InputSource>Platen</pwg:InputSource>",
        "<pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>",
        "<scan:XResolution>300</scan:XResolution>",
        "<scan:ColorMode>RGB24</scan:ColorMode>",
        "<pwg:Height>3508</pwg:Height><pwg:Width>2480</pwg:Width>",
    ):
        assert part in settings
    assert "Duplex" not in settings
    await hass.async_block_till_done()
    last = hass.states.get(f"sensor.{P}_last_scan")
    assert last.state != "unknown"
    assert last.attributes["files"] == [str(path)]
    assert last.attributes["media_ids"] == ["media-source://media_source/local/hp/invoice.pdf"]
    assert last.attributes["pages"] == 1
    assert events[0].data["files"] == [str(path)]
    assert events[0].data["pages"] == 1
    assert events[0].data["device_id"]

    # Same name again: nothing is overwritten.
    printer.pages = [JPEG_1]
    response = await _scan(hass, filename="invoice")
    assert response["files"] == [str(media / "hp" / "invoice_2.pdf")]


async def test_add_pages_to_pdf(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, media: Path, hass_client
) -> None:
    """Pages scanned one by one on the glass go into the same PDF; the image shows its first page."""
    await _setup(hass, entry)
    printer.pages = [JPEG_1]
    first = await _scan(hass, filename="contract")
    printer.pages = [JPEG_2]
    await hass.services.async_call("button", "press", {"entity_id": f"button.{P}_scan_and_add_page"}, blocking=True)
    printer.pages = [JPEG_1]
    response = await _scan(hass, append=True)
    assert response["files"] == first["files"]
    assert response["pages"] == 3
    pages = read_pdf(Path(first["files"][0]).read_bytes())
    assert [page[0] for page in pages] == [JPEG_1, JPEG_2, JPEG_1]
    assert sorted(p.name for p in (media / "hp").iterdir()) == ["contract.pdf"]

    await hass.async_block_till_done()
    client = await hass_client()
    image = hass.states.get(f"image.{P}_last_scanned_image")
    resp = await client.get(image.attributes["entity_picture"])
    assert resp.status == HTTPStatus.OK
    assert resp.content_type == "image/jpeg"
    assert await resp.read() == JPEG_1


async def test_append_after_a_jpeg_starts_a_pdf(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, media: Path
) -> None:
    """Adding a page when the last scan is not a PDF starts a new PDF."""
    await _setup(hass, entry)
    printer.pages = [JPEG_1]
    await _scan(hass, format="jpeg", filename="photo")
    printer.pages = [JPEG_2]
    response = await _scan(hass, format="pdf", append=True, filename="doc")
    assert response["files"] == [str(media / "hp" / "doc.pdf")]
    assert response["pages"] == 1


async def test_scan_png(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, media: Path) -> None:
    """PNG: the scanner's JPEG converted."""
    await _setup(hass, entry)
    printer.pages = [_jpeg(100, 140)]
    response = await _scan(hass, format="png", filename="drawing")
    path = Path(response["files"][0])
    assert path.name == "drawing.png"
    with Image.open(path) as image:
        assert (image.format, image.size) == ("PNG", (100, 140))
    assert "<pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>" in printer.scan_jobs[0].decode()


async def test_scanner_pdf_only(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, media: Path) -> None:
    """A scanner that only offers PDF: its own PDF is saved, and PNG is not offered."""
    printer.replace("/eSCL/ScannerCapabilities", "<pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>", "")
    await _setup(hass, entry)
    assert hass.states.get(f"select.{P}_scan_format").attributes["options"] == ["pdf"]
    printer.pages = [PDF]
    response = await _scan(hass)
    assert Path(response["files"][0]).read_bytes() == PDF
    assert response["pages"] is None
    assert "<pwg:DocumentFormat>application/pdf</pwg:DocumentFormat>" in printer.scan_jobs[0].decode()


async def test_scan_with_device_id(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """The printer is found by its device."""
    await _setup(hass, entry)
    device = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]
    printer.pages = [JPEG_1]
    response = await _scan(hass, device_id=device.id)
    assert response["pages"] == 1
    with pytest.raises(ServiceValidationError) as err:
        await _scan(hass, device_id="unknown")
    assert err.value.translation_key == "device_not_found"


async def test_scan_jpeg_feeder_duplex(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, media: Path, hass_client
) -> None:
    """JPEG from the feeder: one file per page, shown in the last scanned image."""
    await _setup(hass, entry)
    printer.pages = [JPEG_1, JPEG_2]
    printer.busy_pages = 2
    response = await _scan(hass, format="jpeg", source="feeder_duplex", color_mode="grayscale", filename="doc")
    assert [Path(f).name for f in response["files"]] == ["doc_1.jpg", "doc_2.jpg"]
    settings = printer.scan_jobs[0].decode()
    assert "<pwg:InputSource>Feeder</pwg:InputSource>" in settings
    assert "<scan:Duplex>true</scan:Duplex>" in settings
    assert "<scan:ColorMode>Grayscale8</scan:ColorMode>" in settings

    await hass.async_block_till_done()
    image = hass.states.get(f"image.{P}_last_scanned_image")
    client = await hass_client()
    resp = await client.get(image.attributes["entity_picture"])
    assert resp.status == HTTPStatus.OK
    assert await resp.read() == JPEG_1


async def test_job_address_from_status(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """A firmware that gives no job address: it is read from the scanner status."""
    await _setup(hass, entry)
    printer.give_location = False
    printer.pages = [JPEG_1]
    response = await _scan(hass)
    assert len(response["files"]) == 1


@pytest.mark.parametrize(
    ("setup", "data", "key"),
    [
        (lambda p: setattr(p, "adf_state", "ScannerAdfEmpty"), {"source": "feeder"}, "feeder_empty"),
        (lambda p: setattr(p, "scanner_state", "Processing"), {}, "scanner_busy"),
        (lambda p: None, {"resolution": 150}, "unsupported_resolution"),
        (lambda p: None, {"color_mode": "black_and_white"}, "unsupported_color_mode"),
        (lambda p: setattr(p, "online", False), {}, "printer_offline"),
    ],
)
async def test_scan_errors(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer, setup, data, key
) -> None:
    """Errors the scan can meet are translated."""
    await _setup(hass, entry)
    setup(printer)
    if not printer.online:
        from datetime import timedelta

        from pytest_homeassistant_custom_component.common import async_fire_time_changed

        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
    with pytest.raises(HomeAssistantError) as err:
        await _scan(hass, **data)
    assert err.value.translation_key == key


async def test_failed_job_is_cancelled(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """A job that never gives a document is deleted, freeing the scanner."""
    await _setup(hass, entry)
    printer.busy_pages = 1000
    with pytest.raises(HomeAssistantError) as err:
        await _scan(hass)
    assert err.value.translation_key == "scanner_busy"
    assert printer.deleted == [JOB]


async def test_directory_not_allowed(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """Files are only written to allowed folders."""
    await _setup(hass, entry)
    with pytest.raises(ServiceValidationError) as err:
        await _scan(hass, directory="/etc")
    assert err.value.translation_key == "directory_not_allowed"
    assert printer.scan_jobs == []


async def test_button_uses_selects(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """The Scan button scans with the settings chosen in the selects."""
    await _setup(hass, entry)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": f"select.{P}_scan_format", "option": "jpeg"}, blocking=True
    )
    await hass.services.async_call(
        "select", "select_option", {"entity_id": f"select.{P}_scan_resolution", "option": "600"}, blocking=True
    )
    printer.pages = [JPEG_1]
    await hass.services.async_call("button", "press", {"entity_id": f"button.{P}_scan"}, blocking=True)
    settings = printer.scan_jobs[0].decode()
    assert "<pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>" in settings
    assert "<scan:XResolution>600</scan:XResolution>" in settings


async def test_selects_restored(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """Scan settings come back after a restart; a choice the scanner lost falls back to the default."""
    mock_restore_cache(
        hass,
        [State(f"select.{P}_scan_format", "jpeg"), State(f"select.{P}_scan_resolution", "1200")],
    )
    await _setup(hass, entry)
    assert hass.states.get(f"select.{P}_scan_format").state == "jpeg"
    assert hass.states.get(f"select.{P}_scan_resolution").state == "300"
    assert entry.runtime_data.scan_settings.format == "jpeg"


async def test_two_printers_need_a_device(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """With several printers the action needs a device."""
    await _setup(hass, entry)
    other = MockConfigEntry(domain=DOMAIN, unique_id="OTHER", data={"host": "10.0.0.9", "ssl": False})
    printer.replace("/DevMgmt/ProductConfigDyn.xml", "TH0AB1C2DE", "OTHER")
    await _setup(hass, other)
    with pytest.raises(ServiceValidationError) as err:
        await _scan(hass)
    assert err.value.translation_key == "device_required"


async def test_outside_media_no_media_id(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, tmp_path: Path
) -> None:
    """A file saved outside the media folders has no media source ID."""
    other = tmp_path.parent / f"{tmp_path.name}_scans"
    other.mkdir()
    hass.config.allowlist_external_dirs.add(str(other))
    await _setup(hass, entry)
    printer.pages = [JPEG_1]
    response = await _scan(hass, directory=str(other))
    assert response["media_ids"] == []


async def test_download_last_scan(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, hass_client, hass_client_no_auth
) -> None:
    """The last scan's PDF is downloaded through the integration (the media view does not serve PDFs)."""
    await _setup(hass, entry)
    printer.pages = [JPEG_1]
    response = await _scan(hass, filename="letter")
    path = response["download_paths"][0]
    client = await hass_client()
    resp = await client.get(path)
    assert resp.status == HTTPStatus.OK
    assert resp.headers["Content-Type"] == "application/pdf"
    assert resp.headers["Content-Disposition"] == 'attachment; filename="letter.pdf"'
    body = await resp.read()
    assert body[:5] == b"%PDF-"
    # Downloaded: the file is deleted and leaves the last scan (the view finishes after the body is sent).
    await _view_done(hass)
    assert not Path(response["files"][0]).exists()
    last = hass.states.get(f"sensor.{P}_last_scan")
    assert last.attributes["files"] == []
    assert last.attributes["download_paths"] == []
    assert (await client.get(path)).status == HTTPStatus.NOT_FOUND

    # Several pages: each file downloaded goes, the others keep working links.
    printer.pages = [JPEG_1, JPEG_2]
    response = await _scan(hass, format="jpeg", source="feeder", filename="pages")
    resp = await client.get(response["download_paths"][1])
    assert await resp.read() == JPEG_2
    await _view_done(hass)
    last = hass.states.get(f"sensor.{P}_last_scan")
    assert last.attributes["files"] == [response["files"][0]]
    assert last.attributes["download_paths"] == [f"/api/hp/scans/{entry.entry_id}/0"]
    resp = await client.get(last.attributes["download_paths"][0])
    assert await resp.read() == JPEG_1

    for other in (f"/api/hp/scans/{entry.entry_id}/5", f"/api/hp/scans/{entry.entry_id}/x", "/api/hp/scans/nope/0"):
        assert (await client.get(other)).status == HTTPStatus.NOT_FOUND
    anonymous = await hass_client_no_auth()
    assert (await anonymous.get(path)).status == HTTPStatus.UNAUTHORIZED
