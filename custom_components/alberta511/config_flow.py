"""Config and options flow for Alberta 511."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import Alberta511AuthError, Alberta511Client, Alberta511Error
from .const import (
    COLLECTION_CAMERAS,
    CONF_API_KEY,
    CONF_CAMERA,
    CONF_DATA_INTERVAL,
    CONF_EVENT_RADIUS,
    CONF_FILTER,
    CONF_IMAGE_INTERVAL,
    CONF_SHOW_SELECTOR,
    CONF_TEMP_UNIT,
    CONF_WEATHER_RADIUS,
    CONF_WIND_UNIT,
    DEFAULT_DATA_INTERVAL,
    DEFAULT_EVENT_RADIUS,
    DEFAULT_IMAGE_INTERVAL,
    DEFAULT_TEMP_UNIT,
    DEFAULT_WEATHER_RADIUS,
    DEFAULT_WIND_UNIT,
    DOMAIN,
)
from .models import CameraView, build_labels, parse_cameras


class Alberta511ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add an Alberta 511 camera feed."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_key: str = ""
        self._filter: str = ""
        self._views: dict[str, CameraView] = {}

    def _existing_key(self) -> str:
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_API_KEY):
                return entry.data[CONF_API_KEY]
        return ""

    async def _load_views(self, api_key: str) -> str | None:
        client = Alberta511Client(async_get_clientsession(self.hass), api_key or None)
        try:
            views = parse_cameras(await client.async_get(COLLECTION_CAMERAS))
        except Alberta511AuthError:
            return "invalid_auth" if api_key else "key_required"
        except Alberta511Error:
            return "cannot_connect"
        if not views:
            return "no_cameras"
        self._views = {v.key: v for v in views}
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._api_key = (user_input.get(CONF_API_KEY) or "").strip()
            self._filter = (user_input.get(CONF_FILTER) or "").strip()
            error = await self._load_views(self._api_key)
            if error:
                errors["base"] = error
            else:
                return await self.async_step_camera()

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_API_KEY,
                    description={"suggested_value": self._api_key or self._existing_key()},
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                vol.Optional(
                    CONF_FILTER, description={"suggested_value": self._filter}
                ): TextSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_camera(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        labels = build_labels(self._views.values())
        if self._filter:
            terms = self._filter.lower().split()
            filtered = {l: k for l, k in labels.items() if all(t in l.lower() for t in terms)}
            if filtered:
                labels = filtered
            else:
                # Show everything, flag it once, and don't block the next submit.
                self._filter = ""
                if user_input is None:
                    errors["base"] = "no_match"

        if user_input is not None and not errors:
            key = user_input[CONF_CAMERA]
            show_selector = bool(user_input.get(CONF_SHOW_SELECTOR, True))
            label = next((l for l, k in labels.items() if k == key), key)
            if not show_selector:
                # Fixed feeds are unique per camera view; switchable viewers are not.
                await self.async_set_unique_id(f"fixed_{key}")
                self._abort_if_unique_id_configured()
            title = (user_input.get(CONF_NAME) or "").strip() or (
                "511 Viewer" if show_selector else label
            )
            return self.async_create_entry(
                title=title,
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_CAMERA: key,
                    CONF_SHOW_SELECTOR: show_selector,
                },
            )

        options = [SelectOptionDict(value=k, label=l) for l, k in labels.items()]
        schema = vol.Schema(
            {
                vol.Required(CONF_CAMERA): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN, sort=False)
                ),
                vol.Optional(CONF_SHOW_SELECTOR, default=True): BooleanSelector(),
                vol.Optional(CONF_NAME): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="camera",
            data_schema=schema,
            errors=errors,
            description_placeholders={"count": str(len(options))},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = (user_input.get(CONF_API_KEY) or "").strip()
            error = await self._load_views(key)
            if error:
                errors["base"] = error
            else:
                entry = self._get_reauth_entry()
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: key}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return Alberta511OptionsFlow()


def _number(minimum: float, maximum: float, step: float, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=minimum, max=maximum, step=step, unit_of_measurement=unit, mode=NumberSelectorMode.BOX)
    )


class Alberta511OptionsFlow(OptionsFlow):
    """Refresh rates, search radii and unit overrides."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_IMAGE_INTERVAL, default=opts.get(CONF_IMAGE_INTERVAL, DEFAULT_IMAGE_INTERVAL)
                ): _number(30, 3600, 10, "s"),
                vol.Required(
                    CONF_DATA_INTERVAL, default=opts.get(CONF_DATA_INTERVAL, DEFAULT_DATA_INTERVAL)
                ): _number(2, 60, 1, "min"),
                vol.Required(
                    CONF_EVENT_RADIUS, default=opts.get(CONF_EVENT_RADIUS, DEFAULT_EVENT_RADIUS)
                ): _number(1, 200, 1, "km"),
                vol.Required(
                    CONF_WEATHER_RADIUS, default=opts.get(CONF_WEATHER_RADIUS, DEFAULT_WEATHER_RADIUS)
                ): _number(0.5, 50, 0.5, "km"),
                vol.Required(
                    CONF_TEMP_UNIT, default=opts.get(CONF_TEMP_UNIT, DEFAULT_TEMP_UNIT)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value="celsius", label="Celsius"),
                            SelectOptionDict(value="fahrenheit", label="Fahrenheit"),
                        ]
                    )
                ),
                vol.Required(
                    CONF_WIND_UNIT, default=opts.get(CONF_WIND_UNIT, DEFAULT_WIND_UNIT)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value="km/h", label="km/h"),
                            SelectOptionDict(value="mph", label="mph"),
                            SelectOptionDict(value="m/s", label="m/s"),
                        ]
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
