"""Setup, polling tiers, and values kept while the printer is off."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.hp.const import DOMAIN

from .conftest import SERIAL, FakePrinter

P = "sensor.hp_officejet_pro_9010_series"
B = "binary_sensor.hp_officejet_pro_9010_series"
STATUS = "/DevMgmt/ProductStatusDyn.xml"
USAGE = "/DevMgmt/ProductUsageDyn.xml"
CONSUMABLES = "/DevMgmt/ConsumableConfigDyn.xml"
DEVICE = "/DevMgmt/ProductConfigDyn.xml"
EPRINT = "/ePrint/ePrintConfigDyn.xml"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float = 31) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def _device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    assert devices[0].identifiers == {(DOMAIN, SERIAL)}
    return devices[0]


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def test_setup_creates_entities(hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry) -> None:
    """Every document is read at setup and becomes entities."""
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    assert _state(hass, f"{P}_status") == "ready"
    status = hass.states.get(f"{P}_status")
    assert status.attributes["raw_status"] == "ready"
    assert status.attributes["message"] == "Ready"
    assert status.attributes["alerts"] == ["cartridgeLow"]
    assert _state(hass, f"{P}_printed_pages") == "1234"
    assert _state(hass, f"{P}_printed_color_pages") == "434"
    assert _state(hass, f"{P}_scanned_pages") == "210"
    assert _state(hass, f"{P}_copied_pages") == "45"
    assert hass.states.get(f"{P}_faxed_pages") is None

    assert _state(hass, f"{P}_black_level") == "42"
    black = hass.states.get(f"{P}_black_level")
    assert black.attributes["cartridge"] == "963"
    assert black.attributes["product_number"] == "3JA26AE"
    assert black.attributes["state"] == "ok"
    assert black.attributes["installed"] is True
    assert hass.states.get(f"{P}_cyan_level").attributes["state"] == "very_low"
    assert _state(hass, f"{P}_cyan_level") == "8"
    assert _state(hass, f"{P}_magenta_level") == "60"
    # -128 in the config document: the raw level of the usage document is used.
    assert _state(hass, f"{P}_yellow_level") == "25"
    assert _state(hass, f"{P}_black_pages_remaining") == "380"
    assert hass.states.get(f"{P}_tri_color_level") is None

    assert _state(hass, f"{B}_online") == STATE_ON
    assert _state(hass, f"{B}_wi_fi") == STATE_ON
    assert _state(hass, f"{B}_ethernet") == STATE_OFF
    assert _state(hass, f"{B}_hp_cloud_registered") == STATE_ON

    device = _device(hass, entry)
    assert device.model == "HP OfficeJet Pro 9010 series"
    assert device.sw_version == "TAPP1FN2318CR"
    assert device.serial_number == SERIAL


async def test_offline_keeps_values(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A printer turned off keeps every value; only its status and online sensor change."""
    await _setup(hass, entry)
    printer.online = False
    await _tick(hass, freezer)

    assert _state(hass, f"{P}_status") == "off"
    assert _state(hass, f"{B}_online") == STATE_OFF
    assert _state(hass, f"{P}_printed_pages") == "1234"
    assert _state(hass, f"{P}_black_level") == "42"
    assert _state(hass, f"{B}_wi_fi") == STATE_ON
    for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        # A button and the last scan have no state before they are used, printer on or off.
        never_used = entity.domain in ("button", "image") or entity.entity_id.endswith("_last_scan")
        if entity.disabled_by is None and not never_used:
            assert _state(hass, entity.entity_id) not in (STATE_UNAVAILABLE, STATE_UNKNOWN), entity.entity_id


async def test_back_online_reads_everything(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A printer turned back on is read in full at once."""
    await _setup(hass, entry)
    printer.online = False
    await _tick(hass, freezer)
    printer.replace(USAGE, ">1234<", ">1240<")
    printer.online = True
    await _tick(hass, freezer)
    assert _state(hass, f"{P}_status") == "ready"
    assert _state(hass, f"{P}_printed_pages") == "1240"
    assert printer.count(DEVICE) == 2


async def test_lost_request_is_not_offline(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """One failed status request is tried again before the printer counts as off."""
    await _setup(hass, entry)
    printer.fail_next = 1
    await _tick(hass, freezer)
    assert _state(hass, f"{P}_status") == "ready"
    assert _state(hass, f"{B}_online") == STATE_ON


async def test_status_tiers(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """Status at every poll; counters every 5 minutes or when a job ends; identity hours apart."""
    await _setup(hass, entry)
    assert printer.count(STATUS) == 1 and printer.count(USAGE) == 1

    await _tick(hass, freezer)
    await _tick(hass, freezer)
    assert printer.count(STATUS) == 3
    assert printer.count(USAGE) == 1
    assert printer.count(DEVICE) == 1

    printer.set_status("processing")
    await _tick(hass, freezer)
    assert _state(hass, f"{P}_status") == "processing"
    assert printer.count(USAGE) == 1
    printer.replace(USAGE, ">1234<", ">1236<")
    printer.set_status("ready")
    await _tick(hass, freezer)
    # The job ended: counters read at once.
    assert printer.count(USAGE) == 2
    assert _state(hass, f"{P}_printed_pages") == "1236"

    await _tick(hass, freezer, 301)
    assert printer.count(USAGE) == 3
    assert printer.count(DEVICE) == 1


async def test_unchanged_documents_not_parsed_again(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """Documents are asked with their ETag: an unchanged one is a 304."""
    await _setup(hass, entry)
    await _tick(hass, freezer, 301)
    assert USAGE in printer.not_modified
    # The status is always read in full: a firmware with a wrong ETag must never freeze it.
    assert STATUS not in printer.not_modified
    assert _state(hass, f"{P}_printed_pages") == "1234"


async def test_unsupported_document(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A document the printer does not publish gives no entity and is not asked at every read."""
    printer.unsupported.add(EPRINT)
    await _setup(hass, entry)
    assert hass.states.get(f"{B}_hp_cloud_registered") is None
    assert printer.count(EPRINT) == 1
    await _tick(hass, freezer, 1801)
    assert printer.count(EPRINT) == 1
    assert printer.count("/IoMgmt/Adapters") == 2


async def test_cartridge_removed_keeps_value(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A cartridge the printer stops listing keeps its last level, marked as not installed."""
    await _setup(hass, entry)
    printer.replace(CONSUMABLES, "<dd:ConsumableLabelCode>C</dd:ConsumableLabelCode>", "")
    await _tick(hass, freezer, 301)
    cyan = hass.states.get(f"{P}_cyan_level")
    assert cyan.state == "8"
    assert cyan.attributes["installed"] is False


async def test_unknown_status(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A status this integration does not know is "other", never unknown."""
    printer.set_status("inkSystemPriming")
    await _setup(hass, entry)
    status = hass.states.get(f"{P}_status")
    assert status.state == "other"
    assert status.attributes["raw_status"] == "inkSystemPriming"
    printer.set_status("jamInPrinter")
    await _tick(hass, freezer)
    assert _state(hass, f"{P}_status") == "paper_jam"


async def test_first_setup_offline_is_retried(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry
) -> None:
    """A printer never seen and off: setup is retried later."""
    printer.online = False
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_data_saved_and_restored_with_printer_off(
    hass: HomeAssistant,
    printer: FakePrinter,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict,
) -> None:
    """The last data is saved; after a restart with the printer off the entities come back with it."""
    await _setup(hass, entry)
    await _tick(hass, freezer, 31)
    saved = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert saved["serial_number"] == SERIAL
    assert saved["data"]["counters"]["total_pages"] == 1234

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    printer.online = False
    printer.requests.clear()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.LOADED
    assert _state(hass, f"{P}_status") == "off"
    assert _state(hass, f"{B}_online") == STATE_OFF
    assert _state(hass, f"{P}_printed_pages") == "1234"
    assert _state(hass, f"{P}_black_level") == "42"
    assert _state(hass, f"{B}_wi_fi") == STATE_ON
    assert entry.runtime_data.last_seen is not None


async def test_stored_data_of_another_printer_ignored(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, hass_storage: dict
) -> None:
    """Saved data of another serial number is not shown."""
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"serial_number": "OTHER", "data": {"counters": {"total_pages": 1}}},
    }
    await _setup(hass, entry)
    assert _state(hass, f"{P}_printed_pages") == "1234"


async def test_address_taken_by_another_printer(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """Another printer at the address (DHCP): this one counts as off and keeps its values."""
    await _setup(hass, entry)
    printer.online = False
    await _tick(hass, freezer)
    printer.replace(DEVICE, SERIAL, "CN9ZZ9ZZ9Z")
    printer.replace(USAGE, ">1234<", ">9<")
    printer.online = True
    await _tick(hass, freezer)
    assert _state(hass, f"{P}_status") == "off"
    assert _state(hass, f"{P}_printed_pages") == "1234"


async def test_firmware_update_followed(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A new firmware reaches the device registry."""
    await _setup(hass, entry)
    printer.replace(DEVICE, "TAPP1FN2318CR", "TAPP1FN2420AR")
    await _tick(hass, freezer, 6 * 3600 + 1)
    device = _device(hass, entry)
    assert device.sw_version == "TAPP1FN2420AR"


async def test_options_change_interval(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """The status interval comes from the options."""
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 120, "scan_retention": 30}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.options == {"scan_interval": 120, "scan_retention": 30}
    before = printer.count(STATUS)
    await _tick(hass, freezer, 61)
    assert printer.count(STATUS) == before
    await _tick(hass, freezer, 61)
    assert printer.count(STATUS) == before + 1


async def test_remove_entry_deletes_saved_data(
    hass: HomeAssistant,
    printer: FakePrinter,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict,
) -> None:
    """Removing the printer removes its saved data."""
    await _setup(hass, entry)
    await _tick(hass, freezer, 31)
    assert f"{DOMAIN}.{entry.entry_id}" in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert f"{DOMAIN}.{entry.entry_id}" not in hass_storage


async def test_unchanged_poll_writes_nothing(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A poll that finds nothing new writes no entity (no state change, nothing recorded)."""
    await _setup(hass, entry)
    before = {state.entity_id: state.last_updated for state in hass.states.async_all()}
    await _tick(hass, freezer)
    await _tick(hass, freezer)
    assert {state.entity_id: state.last_updated for state in hass.states.async_all()} == before
    assert printer.count(STATUS) == 3


async def test_last_seen_sensor_follows_every_answer(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """The last-seen sensor, disabled by default, is the one entity written at every answer."""
    entity_id = f"{P}_last_seen"
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", DOMAIN, f"{SERIAL}_last_seen", suggested_object_id=entity_id[7:])
    registry.async_update_entity(entity_id, disabled_by=None)
    await _setup(hass, entry)
    first = _state(hass, entity_id)
    await _tick(hass, freezer)
    second = _state(hass, entity_id)
    assert second != first
    printer.online = False
    await _tick(hass, freezer)
    assert _state(hass, entity_id) == second


async def test_offline_not_retried(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A printer already off gets one attempt per poll, and its data is not saved again."""
    await _setup(hass, entry)
    printer.online = False
    await _tick(hass, freezer)
    attempts = printer.attempts
    await _tick(hass, freezer)
    assert printer.attempts == attempts + 1


async def test_counters_never_go_down(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A counter reported lower (firmware glitch) keeps its value: no false reset in statistics."""
    await _setup(hass, entry)
    printer.replace(USAGE, ">1234<", ">0<")
    await _tick(hass, freezer, 301)
    assert _state(hass, f"{P}_printed_pages") == "1234"


async def test_no_usage_read_while_initializing(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """Counters and ink are not read while the printer starts up."""
    await _setup(hass, entry)
    printer.set_status("initializing")
    await _tick(hass, freezer, 301)
    assert printer.count(USAGE) == 1
    printer.set_status("ready")
    await _tick(hass, freezer)
    assert printer.count(USAGE) == 2


async def test_missing_cartridge_still_in_usage(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """A cartridge reported "missing" is not installed, even when the usage document still lists it."""
    await _setup(hass, entry)
    printer.replace(
        CONSUMABLES, "<dd:ConsumableState>ok</dd:ConsumableState>", "<dd:ConsumableState>missing</dd:ConsumableState>"
    )
    printer.replace(
        CONSUMABLES, "<dd:ConsumablePercentageLevelRemaining>42<", "<dd:ConsumablePercentageLevelRemaining>-1<"
    )
    await _tick(hass, freezer, 301)
    black = hass.states.get(f"{P}_black_level")
    assert black.state == "42"
    assert black.attributes["installed"] is False
    assert black.attributes["state"] == "missing"


async def test_wrong_printer_not_read_every_poll(
    hass: HomeAssistant, printer: FakePrinter, entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """Another printer at the address is checked every few minutes only, then this one is followed again."""
    await _setup(hass, entry)
    printer.online = False
    await _tick(hass, freezer)
    printer.replace(DEVICE, SERIAL, "CN9ZZ9ZZ9Z")
    printer.online = True
    await _tick(hass, freezer)
    usage, device = printer.count(USAGE), printer.count(DEVICE)
    await _tick(hass, freezer)
    await _tick(hass, freezer)
    assert (printer.count(USAGE), printer.count(DEVICE)) == (usage, device)
    printer.replace(DEVICE, "CN9ZZ9ZZ9Z", SERIAL)
    await _tick(hass, freezer, 301)
    assert _state(hass, f"{P}_status") == "ready"
    assert printer.count(DEVICE) == device + 1
