"""Config flow: address, discovery, reconfigure."""

from __future__ import annotations

from ipaddress import ip_address

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hp.const import DOMAIN

from .conftest import HOST, MODEL, SERIAL, FakePrinter

DISCOVERY = ZeroconfServiceInfo(
    ip_address=ip_address("192.168.1.77"),
    ip_addresses=[ip_address("192.168.1.77")],
    hostname="HP3C2AF4.local.",
    name="HP OfficeJet Pro 9010 series [3C2AF4]._ipp._tcp.local.",
    port=631,
    type="_ipp._tcp.local.",
    properties={},
)


async def test_user(hass: HomeAssistant, printer: FakePrinter) -> None:
    """A printer added by address is named after its model."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": f" {HOST} ", "ssl": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MODEL
    assert result["data"] == {"host": HOST, "ssl": False}
    assert result["result"].unique_id == SERIAL


async def test_user_port(hass: HomeAssistant, printer: FakePrinter) -> None:
    """A port is kept as an integer."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": 8080.0, "ssl": False}
    )
    assert result["data"] == {"host": HOST, "port": 8080, "ssl": False}


async def test_user_cannot_connect(hass: HomeAssistant, printer: FakePrinter) -> None:
    """An unreachable printer is an error on the form, then can be retried."""
    printer.online = False
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": HOST, "ssl": False})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    printer.online = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": HOST, "ssl": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_not_hp(hass: HomeAssistant, printer: FakePrinter) -> None:
    """A device without the HP documents cannot be added."""
    printer.unsupported.add("/DevMgmt/ProductStatusDyn.xml")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": HOST, "ssl": False})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_missing_serial(hass: HomeAssistant, printer: FakePrinter) -> None:
    """A printer without a serial number is refused."""
    printer.replace("/DevMgmt/ProductConfigDyn.xml", SERIAL, "")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": HOST, "ssl": False})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "missing_serial_number"


async def test_user_already_configured(hass: HomeAssistant, printer: FakePrinter) -> None:
    """The same printer at a new address updates the existing entry."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={"host": "10.0.0.2", "ssl": False})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": HOST, "ssl": False})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == HOST


async def test_zeroconf(hass: HomeAssistant, printer: FakePrinter) -> None:
    """A discovered HP printer is confirmed, then added."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_ZEROCONF}, data=DISCOVERY)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["description_placeholders"] == {"name": MODEL, "host": "192.168.1.77"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": "192.168.1.77", "ssl": False}


async def test_zeroconf_follows_new_address(hass: HomeAssistant, printer: FakePrinter) -> None:
    """A known printer announced at a new address is followed there."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={"host": HOST, "ssl": False})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_ZEROCONF}, data=DISCOVERY)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.168.1.77"


async def test_zeroconf_cannot_connect(hass: HomeAssistant, printer: FakePrinter) -> None:
    """A discovered device that does not answer is ignored."""
    printer.online = False
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_ZEROCONF}, data=DISCOVERY)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_reconfigure(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """The address changes without removing the printer."""
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.168.1.99", "ssl": False})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["host"] == "192.168.1.99"


async def test_reconfigure_wrong_printer(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """Another printer at the new address is refused."""
    entry.add_to_hass(hass)
    printer.replace("/DevMgmt/ProductConfigDyn.xml", SERIAL, "CN9ZZ9ZZ9Z")
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.168.1.99", "ssl": False})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_printer"
    assert entry.data["host"] == HOST
