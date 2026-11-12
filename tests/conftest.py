"""Fixtures: a fake HP printer answering its EWS documents, and a config entry for it."""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest
from multidict import CIMultiDict
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hp.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
HOST = "192.168.1.50"
SERIAL = "TH0AB1C2DE"
MODEL = "HP OfficeJet Pro 9010 series"

DOCUMENTS = {
    "/DevMgmt/ProductStatusDyn.xml": "ProductStatusDyn.xml",
    "/DevMgmt/ProductConfigDyn.xml": "ProductConfigDyn.xml",
    "/DevMgmt/ConsumableConfigDyn.xml": "ConsumableConfigDyn.xml",
    "/DevMgmt/ProductUsageDyn.xml": "ProductUsageDyn.xml",
    "/IoMgmt/Adapters": "Adapters.xml",
    "/ePrint/ePrintConfigDyn.xml": "ePrintConfigDyn.xml",
    "/eSCL/ScannerCapabilities": "ScannerCapabilities.xml",
}
JOB = "/eSCL/ScanJobs/1c852a4d-0001"


def scanner_status(state: str = "Idle", adf: str = "ScannerAdfLoaded", job: str | None = None) -> bytes:
    """An eSCL ScannerStatus document."""
    jobs = (
        f"<scan:Jobs><scan:JobInfo><pwg:JobUri>{job}</pwg:JobUri><pwg:JobState>Processing</pwg:JobState>"
        "</scan:JobInfo></scan:Jobs>"
        if job
        else ""
    )
    return (
        '<scan:ScannerStatus xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"'
        ' xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">'
        f"<pwg:State>{state}</pwg:State><scan:AdfState>{adf}</scan:AdfState>{jobs}</scan:ScannerStatus>"
    ).encode()


class FakeResponse:
    """The part of an aiohttp response the client uses."""

    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = CIMultiDict(headers or {})
        self.content_type = self.headers.get("Content-Type", "text/xml").split(";")[0]

    async def read(self) -> bytes:
        return self._body


class FakePrinter:
    """An HP printer's embedded web server: documents, ETags, power and failures."""

    def __init__(self) -> None:
        self.documents: dict[str, bytes] = {path: (FIXTURES / name).read_bytes() for path, name in DOCUMENTS.items()}
        self.online = True
        self.etags = True
        self.unsupported: set[str] = set()
        self.fail_next = 0
        self.requests: list[str] = []
        self.not_modified: list[str] = []
        self.attempts = 0
        # Scanner: state, pages of the next job, posted settings, 503s before a page, job address given.
        self.scanner_state = "Idle"
        self.adf_state = "ScannerAdfLoaded"
        self.pages: list[bytes] = []
        self.scan_jobs: list[bytes] = []
        self.busy_pages = 0
        self.give_location = True
        self.job_running = False
        self.deleted: list[str] = []

    def set_status(self, category: str) -> None:
        body = (FIXTURES / "ProductStatusDyn.xml").read_text()
        self.documents["/DevMgmt/ProductStatusDyn.xml"] = body.replace(
            "<pscat:StatusCategory>ready", f"<pscat:StatusCategory>{category}"
        ).encode()

    def replace(self, path: str, old: str, new: str) -> None:
        self.documents[path] = self.documents[path].replace(old.encode(), new.encode())

    def count(self, path: str) -> int:
        return self.requests.count(path)

    @asynccontextmanager
    async def request(self, method: str, url: Any, data: bytes | None = None, **_: Any):
        """eSCL requests: scanner status, scan jobs and their documents."""
        path = url.path
        self.attempts += 1
        if not self.online:
            raise aiohttp.ClientConnectionError("host unreachable")
        if method == "GET" and path == "/eSCL/ScannerStatus":
            job = JOB if self.job_running else None
            yield FakeResponse(
                200, scanner_status(self.scanner_state, self.adf_state, job), {"Content-Type": "text/xml"}
            )
        elif method == "POST" and path == "/eSCL/ScanJobs":
            self.scan_jobs.append(data or b"")
            self.job_running = True
            headers = {"Location": f"http://printer.local:80{JOB}"} if self.give_location else {}
            yield FakeResponse(201, b"", headers)
        elif method == "GET" and path == f"{JOB}/NextDocument":
            if self.busy_pages:
                self.busy_pages -= 1
                yield FakeResponse(503)
            elif self.pages:
                yield FakeResponse(200, self.pages.pop(0), {"Content-Type": "application/octet-stream"})
            else:
                self.job_running = False
                yield FakeResponse(404)
        elif method == "DELETE":
            self.deleted.append(path)
            self.job_running = False
            yield FakeResponse(200)
        else:
            yield FakeResponse(404)

    @asynccontextmanager
    async def get(self, url: Any, headers: dict[str, str] | None = None, **_: Any):
        path = url.path
        self.attempts += 1
        if not self.online:
            raise aiohttp.ClientConnectionError("host unreachable")
        if self.fail_next:
            self.fail_next -= 1
            raise aiohttp.ServerDisconnectedError()
        self.requests.append(path)
        if path in self.unsupported or path not in self.documents:
            yield FakeResponse(404)
            return
        body = self.documents[path]
        etag = f'"{hashlib.md5(body).hexdigest()}"' if self.etags else None
        if etag and (headers or {}).get("If-None-Match") == etag:
            self.not_modified.append(path)
            yield FakeResponse(304, headers={"ETag": etag})
            return
        yield FakeResponse(200, body, {"Content-Type": "text/xml", **({"ETag": etag} if etag else {})})


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/hp."""


@pytest.fixture(autouse=True)
def no_retry_delay() -> Generator[None]:
    """Retry a lost status request at once."""
    with patch("custom_components.hp.coordinator.RETRY_DELAY", 0):
        yield


@pytest.fixture
def printer() -> Generator[FakePrinter]:
    """Replace Home Assistant's HTTP session by the fake printer."""
    fake = FakePrinter()
    with (
        patch("custom_components.hp.async_get_clientsession", return_value=fake),
        patch("custom_components.hp.config_flow.async_get_clientsession", return_value=fake),
    ):
        yield fake


@pytest.fixture
def entry() -> MockConfigEntry:
    """A configured printer."""
    return MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, title=MODEL, data={"host": HOST, "ssl": False}, options={})
