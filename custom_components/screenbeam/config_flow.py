"""Config flow for ScreenBeam MoCA adapters."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .api import ScreenBeamAuthError, ScreenBeamClient, ScreenBeamError
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .decode import Identity

_LOGGER = logging.getLogger(__name__)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): _PASSWORD,
    }
)
USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str}).extend(CREDENTIALS_SCHEMA.schema)


def _title(identity: Identity) -> str:
    # Matches the adapter's DHCP hostname, VSCO-XXXX.
    return f"ScreenBeam {identity.mac.replace(':', '')[-4:].upper()}"


class ScreenBeamConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a ScreenBeam adapter."""

    VERSION = 1

    _host: str

    async def _async_validate(
        self, host: str, username: str, password: str
    ) -> tuple[Identity | None, dict[str, str]]:
        client = ScreenBeamClient(async_get_clientsession(self.hass), host, username, password)
        try:
            return await client.async_get_identity(), {}
        except ScreenBeamAuthError:
            return None, {"base": "invalid_auth"}
        except ScreenBeamError:
            return None, {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error reading %s", host)
            return None, {"base": "unknown"}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set up an adapter by address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            identity, errors = await self._async_validate(
                user_input[CONF_HOST], user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if identity:
                await self.async_set_unique_id(format_mac(identity.mac))
                self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
                return self.async_create_entry(title=_title(identity), data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Handle an adapter seen on DHCP."""
        await self.async_set_unique_id(format_mac(discovery_info.macaddress))
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        self._host = discovery_info.ip
        self.context["title_placeholders"] = {"host": discovery_info.ip}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the credentials of a discovered adapter."""
        errors: dict[str, str] = {}
        if user_input is not None:
            identity, errors = await self._async_validate(
                self._host, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if identity:
                return self.async_create_entry(
                    title=_title(identity), data={CONF_HOST: self._host, **user_input}
                )
        return self.async_show_form(
            step_id="discovery_confirm",
            data_schema=CREDENTIALS_SCHEMA,
            errors=errors,
            description_placeholders={"host": self._host},
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle rejected credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            identity, errors = await self._async_validate(
                entry.data[CONF_HOST], user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if identity:
                await self.async_set_unique_id(format_mac(identity.mac))
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                CREDENTIALS_SCHEMA, {CONF_USERNAME: entry.data[CONF_USERNAME]}
            ),
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or credentials of an adapter."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            identity, errors = await self._async_validate(
                user_input[CONF_HOST], user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if identity:
                await self.async_set_unique_id(format_mac(identity.mac))
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA,
                user_input
                or {CONF_HOST: entry.data[CONF_HOST], CONF_USERNAME: entry.data[CONF_USERNAME]},
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> ScreenBeamOptionsFlow:
        """Return the options flow."""
        return ScreenBeamOptionsFlow()


class ScreenBeamOptionsFlow(OptionsFlow):
    """Options: how often to poll."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
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
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, self.config_entry.options),
        )
