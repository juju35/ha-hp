"""Config flow of the HP Printer integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SSL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import HpClient, HpError, async_identify
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, MAX_SCAN_INTERVAL, MIN_SCAN_INTERVAL

PORT_SELECTOR = NumberSelector(NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX))


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    port = {"suggested_value": defaults[CONF_PORT]} if defaults.get(CONF_PORT) else {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): TextSelector(),
            vol.Optional(CONF_PORT, description=port): PORT_SELECTOR,
            vol.Required(CONF_SSL, default=defaults.get(CONF_SSL, False)): BooleanSelector(),
        }
    )


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = {CONF_HOST: user_input[CONF_HOST].strip(), CONF_SSL: user_input.get(CONF_SSL, False)}
    if user_input.get(CONF_PORT):
        data[CONF_PORT] = int(user_input[CONF_PORT])
    return data


class HpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add an HP printer by address or from discovery."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._host = ""
        self._title = ""

    async def _identify(self, data: dict[str, Any]) -> dict[str, Any] | None:
        client = HpClient(
            host=data[CONF_HOST],
            session=async_get_clientsession(self.hass, verify_ssl=False),
            port=data.get(CONF_PORT),
            ssl=data.get(CONF_SSL, False),
        )
        try:
            return await async_identify(client)
        except HpError:
            return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the printer's address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            device = await self._identify(data)
            if device is None:
                errors["base"] = "cannot_connect"
            elif not device.get("serial_number"):
                return self.async_abort(reason="missing_serial_number")
            else:
                await self.async_set_unique_id(device["serial_number"])
                self._abort_if_unique_id_configured(updates=data, reload_on_update=False)
                return self.async_create_entry(title=device.get("model") or data[CONF_HOST], data=data)
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}), errors=errors)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """Handle an HP printer announced on the network."""
        self._host = discovery_info.host
        self._async_abort_entries_match({CONF_HOST: self._host})
        device = await self._identify({CONF_HOST: self._host})
        if device is None:
            return self.async_abort(reason="cannot_connect")
        if not device.get("serial_number"):
            return self.async_abort(reason="missing_serial_number")
        await self.async_set_unique_id(device["serial_number"])
        # A known printer at a new address is followed there.
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        self._title = device.get("model") or self._host
        self.context["title_placeholders"] = {"name": self._title}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm a discovered printer."""
        if user_input is not None:
            return self.async_create_entry(title=self._title, data={CONF_HOST: self._host, CONF_SSL: False})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="zeroconf_confirm", description_placeholders={"name": self._title, "host": self._host}
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the address of a printer without removing it."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            device = await self._identify(data)
            if device is None:
                errors["base"] = "cannot_connect"
            elif device.get("serial_number") != entry.unique_id:
                return self.async_abort(reason="wrong_printer")
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure", data_schema=_schema(user_input or dict(entry.data)), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return HpOptionsFlow()


class HpOptionsFlow(OptionsFlow):
    """Polling interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])})
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
