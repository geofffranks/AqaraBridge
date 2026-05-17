import logging
import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import (
    CONN_CLASS_LOCAL_PUSH,
    ConfigFlow,
    OptionsFlow,
    ConfigEntry,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import init_hass_data, data_masking, gen_auth_entry
from .core.const import *

_LOGGER = logging.getLogger(__name__)

DEVICE_GET_TOKEN_CONFIG = vol.Schema({vol.Required(CONF_FIELD_AUTH_CODE): str})

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


class AqaraBridgeFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle an Aqara Bridge config flow."""

    VERSION = 1

    def __init__(self):
        """Initialize."""
        self.account = None
        self.country_code = None
        self.account_type = None
        self.app_id = None
        self.app_key = None
        self.key_id = None
        self._session = None
        self._device_manager = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """get option flow"""
        return OptionsFlowHandler()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        init_hass_data(self.hass)
        self._device_manager = self.hass.data[DOMAIN][HASS_DATA_AIOT_MANAGER]
        auth_entry_id = self.hass.data[DOMAIN][HASS_DATA_AUTH_ENTRY_ID]
        self._session = self.hass.data[DOMAIN][HASS_DATA_AIOTCLOUD]
        return await self.async_step_get_auth_code()

    async def async_step_reauth(self, entry_data):
        """Handle re-authentication when the saved tokens are no longer valid."""
        init_hass_data(self.hass)
        self._device_manager = self.hass.data[DOMAIN][HASS_DATA_AIOT_MANAGER]
        self._session = self.hass.data[DOMAIN][HASS_DATA_AIOTCLOUD]
        self.account = entry_data.get(CONF_ENTRY_AUTH_ACCOUNT)
        self.country_code = entry_data.get(CONF_ENTRY_AUTH_COUNTRY_CODE)
        self.app_id = entry_data.get(CONF_ENTRY_APP_ID)
        self.app_key = entry_data.get(CONF_ENTRY_APP_KEY)
        self.key_id = entry_data.get(CONF_ENTRY_KEY_ID)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Delegate to the standard auth-code form; pre-fill via instance attrs."""
        return await self.async_step_get_auth_code(user_input=user_input)

    def _is_reauth(self) -> bool:
        return self.source == "reauth"

    def _finalize_auth(self, auth_entry: dict):
        """Update existing entry on reauth; otherwise create a new one (initial flow)."""
        if self._is_reauth():
            existing = self.hass.config_entries.async_get_entry(
                self.context["entry_id"]
            )
            if existing is not None:
                self.hass.config_entries.async_update_entry(
                    existing, data=auth_entry
                )
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(existing.entry_id)
                )
                return self.async_abort(reason="reauth_successful")
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "get_token"}, data=auth_entry
            )
        )
        return self.async_abort(reason="complete")

    async def async_step_get_auth_code(self, user_input=None):
        """Configure an aqara device through the Aqara Cloud."""
        errors = {}
        if user_input:
            self.account = user_input.get(CONF_FIELD_ACCOUNT)
            self.country_code = user_input.get(CONF_FIELD_COUNTRY_CODE)
            self.app_id = user_input.get(CONF_FIELD_APP_ID)
            self.app_key = user_input.get(CONF_FIELD_APP_KEY)
            self.key_id = user_input.get(CONF_FIELD_KEY_ID)
            self.account_type = 0
            self._session.set_country(self.country_code)
            self._session.set_app_id(self.app_id)
            self._session.set_app_key(self.app_key)
            self._session.set_key_id(self.key_id)

            refresh_token = user_input.get(CONF_FIELD_REFRESH_TOKEN)
            if refresh_token and refresh_token != "":
                resp = await self._session.async_refresh_token(refresh_token)
                if resp["code"] == 0:
                    auth_entry = gen_auth_entry(
                        self.app_id,
                        self.app_key,
                        self.key_id,
                        self.account,
                        self.account_type,
                        self.country_code,
                        resp["result"],
                    )
                    return self._finalize_auth(auth_entry)
                else:
                    errors["base"] = "refresh_token_error"
            else:
                resp = await self._session.async_get_auth_code(self.account, 0)
                if resp["code"] == 0:
                    return await self.async_step_get_token()
                else:
                    errors["base"] = "auth_code_error"
        def_account = (
            user_input.get(CONF_FIELD_ACCOUNT)
            if user_input and user_input.get(CONF_FIELD_ACCOUNT)
            else (self.account or "")
        )
        def_country_code = (
            user_input.get(CONF_FIELD_COUNTRY_CODE)
            if user_input and user_input.get(CONF_FIELD_COUNTRY_CODE)
            else (self.country_code or SERVER_COUNTRY_CODES_DEFAULT)
        )
        def_app_id = (
            user_input.get(CONF_FIELD_APP_ID)
            if user_input and user_input.get(CONF_FIELD_APP_ID)
            else (self.app_id or DEFAULT_CLOUD_APP_ID)
        )
        def_app_key = (
            user_input.get(CONF_FIELD_APP_KEY)
            if user_input and user_input.get(CONF_FIELD_APP_KEY)
            else (self.app_key or DEFAULT_CLOUD_APP_KEY)
        )
        def_key_id = (
            user_input.get(CONF_FIELD_KEY_ID)
            if user_input and user_input.get(CONF_FIELD_KEY_ID)
            else (self.key_id or DEFAULT_CLOUD_KEY_ID)
        )

        config_scheme = vol.Schema(
            {
                vol.Required(CONF_FIELD_ACCOUNT, default=def_account): str,
                vol.Required(CONF_FIELD_COUNTRY_CODE, default=def_country_code): vol.In(
                    SERVER_COUNTRY_CODES
                ),
                vol.Required(CONF_FIELD_APP_ID, default=def_app_id): str,
                vol.Required(CONF_FIELD_APP_KEY, default=def_app_key): str,
                vol.Required(CONF_FIELD_KEY_ID, default=def_key_id): str,
                vol.Optional(CONF_FIELD_REFRESH_TOKEN): PASSWORD_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="get_auth_code",
            data_schema=config_scheme,
            errors=errors,
        )

    async def async_step_get_token(self, user_input=None):
        errors = {}
        if user_input:
            if CONF_FIELD_AUTH_CODE in user_input:
                auth_code = user_input.get(CONF_FIELD_AUTH_CODE)
                resp = await self._session.async_get_token(auth_code, self.account, 0)

                if resp["code"] == 0:
                    auth_entry = gen_auth_entry(
                        self.app_id,
                        self.app_key,
                        self.key_id,
                        self.account,
                        self.account_type,
                        self.country_code,
                        resp["result"],
                    )
                    return self._finalize_auth(auth_entry)
                else:
                    errors["base"] = "get_auth_code_error"
            elif CONF_ENTRY_AUTH_ACCOUNT in user_input:
                return self.async_create_entry(
                    title=data_masking(user_input[CONF_ENTRY_AUTH_ACCOUNT], 4),
                    data=user_input,
                )

            return self.async_abort(reason="complete")

        return self.async_show_form(
            step_id="get_token", data_schema=DEVICE_GET_TOKEN_CONFIG, errors=errors
        )


class OptionsFlowHandler(OptionsFlow):
    def __init__(self) -> None:
        """Initialize options flow."""
        self.account = None
        self.country_code = None
        self.account_type = 0
        self._session = None

    async def async_step_init(self, user_input=None):
        """Configure an aqara device through the Aqara Cloud."""
        errors = {}
        if isinstance(user_input, dict):
            # 用户输入
            self.account = user_input.get(CONF_FIELD_ACCOUNT)
            self.country_code = user_input.get(CONF_FIELD_COUNTRY_CODE)
            if self._session is None:
                self._session = self.hass.data[DOMAIN][HASS_DATA_AIOTCLOUD]
            self._session.set_country(self.country_code)
            self._session.set_app_id(user_input.get(CONF_FIELD_APP_ID))
            self._session.set_app_key(user_input.get(CONF_FIELD_APP_KEY))
            self._session.set_key_id(user_input.get(CONF_FIELD_KEY_ID))

            refresh_token = user_input.get(CONF_FIELD_REFRESH_TOKEN)
            if refresh_token and refresh_token != "":
                # 更新了token值
                resp = await self._session.async_refresh_token(refresh_token)
                if resp["code"] == 0:
                    auth_entry = gen_auth_entry(
                        self._session.get_app_id(),
                        self._session.get_app_key(),
                        self._session.get_key_id(),
                        self.account,
                        self.account_type,
                        self.country_code,
                        resp["result"],
                    )
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=auth_entry
                    )
                    return self.async_abort(reason="complete")
                else:
                    errors["base"] = "refresh_token_error"
            else:
                resp = await self._session.async_get_auth_code(self.account, 0)
                if resp["code"] == 0:
                    return await self.async_step_option_get_token()
                else:
                    errors["base"] = "auth_code_error"
        else:
            prev_input = {
                **self.config_entry.data,
                **self.config_entry.options,
            }
            # HA options flows pre-fill UI from description={"suggested_value": ...},
            # NOT from default=. The default kwarg only affects post-submit validation
            # fallback; it does not render as the visible value in the form. See
            # https://developers.home-assistant.io/docs/data_entry_flow_index
            config_scheme = vol.Schema(
                {
                    vol.Required(
                        CONF_FIELD_ACCOUNT,
                        description={
                            "suggested_value": prev_input.get(CONF_ENTRY_AUTH_ACCOUNT)
                        },
                    ): str,
                    vol.Required(
                        CONF_FIELD_COUNTRY_CODE,
                        description={
                            "suggested_value": prev_input.get(
                                CONF_ENTRY_AUTH_COUNTRY_CODE,
                                SERVER_COUNTRY_CODES_DEFAULT,
                            )
                        },
                    ): vol.In(SERVER_COUNTRY_CODES),
                    vol.Optional(
                        CONF_FIELD_APP_ID,
                        description={
                            "suggested_value": prev_input.get(CONF_ENTRY_APP_ID)
                        },
                    ): str,
                    vol.Optional(
                        CONF_FIELD_APP_KEY,
                        description={
                            "suggested_value": prev_input.get(CONF_ENTRY_APP_KEY)
                        },
                    ): str,
                    vol.Optional(
                        CONF_FIELD_KEY_ID,
                        description={
                            "suggested_value": prev_input.get(CONF_ENTRY_KEY_ID)
                        },
                    ): str,
                    vol.Optional(
                        CONF_FIELD_REFRESH_TOKEN,
                        description={
                            "suggested_value": prev_input.get(
                                CONF_ENTRY_AUTH_REFRESH_TOKEN, ""
                            )
                        },
                    ): PASSWORD_SELECTOR,
                }
            )
            return self.async_show_form(
                step_id="init", data_schema=config_scheme, errors=errors
            )

    async def async_step_option_get_token(self, user_input=None):
        errors = {}
        if user_input and CONF_FIELD_AUTH_CODE in user_input:
            auth_code = user_input.get(CONF_FIELD_AUTH_CODE)
            resp = await self._session.async_get_token(auth_code, self.account, 0)
            if resp["code"] == 0:
                auth_entry = gen_auth_entry(
                    self._session.get_app_id(),
                    self._session.get_app_key(),
                    self._session.get_key_id(),
                    self.account,
                    self.account_type,
                    self.country_code,
                    resp["result"],
                )
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=auth_entry
                )
                return self.async_abort(reason="complete")
            else:
                errors["base"] = "auth_code_error"
        return self.async_show_form(
            step_id="option_get_token",
            data_schema=DEVICE_GET_TOKEN_CONFIG,
            errors=errors,
        )
