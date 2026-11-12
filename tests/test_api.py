"""Document parsers."""

from __future__ import annotations

import pytest

from custom_components.hp.api import _parse_body as parse_body
from custom_components.hp.api import map_status, parse_adapters, parse_consumables, parse_eprint, parse_status


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        ("ready", "ready"),
        ("inPowerSave", "in_power_save"),
        ("scanProcessing", "scan_processing"),
        ("cancelJob", "cancel_job"),
        ("trayEmpty", "tray_empty"),
        ("jamInPrinter", "paper_jam"),
        ("doorOpen", "close_door_or_cover"),
        ("inkSystemInitializing", "initializing"),
        ("somethingNew", "other"),
        (None, "other"),
    ],
)
def test_map_status(raw: str | None, status: str) -> None:
    """HP categories map to the sensor's values, unknown ones to "other"."""
    assert map_status(raw) == status


def test_adapters_json() -> None:
    """Some firmwares answer /IoMgmt/Adapters in JSON."""
    document = parse_body(
        "/IoMgmt/Adapters",
        b'{"Adapters": {"Adapter": [{"HardwareConfig": {"Name": "wifi0", "IsConnected": "true"}},'
        b' {"HardwareConfig": {"Name": "eth0", "IsConnected": "false"}}]}}',
        "application/json",
    )
    assert parse_adapters(document) == {"wifi": True, "ethernet": False}


def test_eprint_unregistered() -> None:
    """Cloud registration and services."""
    document = parse_body(
        "/ePrint/ePrintConfigDyn.xml",
        b"<ePrintConfigDyn><RegistrationState>unregistered</RegistrationState>"
        b"<CloudServicesSwitch><Status>disabled</Status></CloudServicesSwitch></ePrintConfigDyn>",
        "text/xml",
    )
    assert parse_eprint(document) == {"cloud_registered": False, "cloud_services": False}


def test_toner_and_tri_color() -> None:
    """Toner cartridges and tri-color ink cartridges, from either document."""
    config = parse_body(
        "/DevMgmt/ConsumableConfigDyn.xml",
        b"<ConsumableConfigDyn><ConsumableInfo><ConsumableTypeEnum>toner</ConsumableTypeEnum>"
        b"<ConsumableLabelCode>K</ConsumableLabelCode><ConsumablePercentageLevelRemaining>70"
        b"</ConsumablePercentageLevelRemaining></ConsumableInfo></ConsumableConfigDyn>",
        "text/xml",
    )
    usage = parse_body(
        "/DevMgmt/ProductUsageDyn.xml",
        b"<ProductUsageDyn><ConsumableSubunit><Consumable><MarkerColor>CyanMagentaYellow</MarkerColor>"
        b"<ConsumableRawPercentageLevelRemaining>33</ConsumableRawPercentageLevelRemaining>"
        b"</Consumable></ConsumableSubunit></ProductUsageDyn>",
        "text/xml",
    )
    assert parse_consumables(config, usage) == {
        "black": {"level": 70, "type": "toner"},
        "tri_color": {"level": 33},
    }


def test_status_skips_informative_entries() -> None:
    """An OfficeJet Pro 9010 lists "genuineHP" before its real status: the real one is shown."""
    document = parse_body(
        "/DevMgmt/ProductStatusDyn.xml",
        b"<ProductStatusDyn>"
        b"<Status><StatusCategory>genuineHP</StatusCategory><LocString>Cart. HP Instant Ink</LocString></Status>"
        b"<Status><StatusCategory>ready</StatusCategory><LocString>Ready</LocString></Status>"
        b"<AlertTable><Alert><ProductStatusAlertID>genuineHP</ProductStatusAlertID></Alert>"
        b"<Alert><ProductStatusAlertID>genuineHP</ProductStatusAlertID></Alert></AlertTable>"
        b"</ProductStatusDyn>",
        "text/xml",
    )
    assert parse_status(document) == {
        "status": "ready",
        "raw_status": "ready",
        "status_message": "Ready",
        "alerts": ["genuineHP"],
    }


def test_status_stop_wins() -> None:
    """A jam is shown before the printer's work, and an unknown status only when nothing is known."""

    def status(*categories: str) -> str:
        body = "".join(f"<Status><StatusCategory>{c}</StatusCategory></Status>" for c in categories)
        return parse_status(parse_body("/s", f"<ProductStatusDyn>{body}</ProductStatusDyn>".encode(), "text/xml"))[
            "status"
        ]

    assert status("processing", "jamInPrinter") == "paper_jam"
    assert status("genuineHP", "inPowerSave") == "in_power_save"
    assert status("genuineHP") == "other"


def test_cartridge_state_snake_case() -> None:
    """Cartridge states keep acronyms whole."""
    config = parse_body(
        "/DevMgmt/ConsumableConfigDyn.xml",
        b"<ConsumableConfigDyn><ConsumableInfo><ConsumableLabelCode>K</ConsumableLabelCode>"
        b"<ConsumableLifeState><ConsumableState>newGenuineHP</ConsumableState></ConsumableLifeState>"
        b"</ConsumableInfo></ConsumableConfigDyn>",
        "text/xml",
    )
    assert parse_consumables(config, None)["black"]["state"] == "new_genuine_hp"
