"""Einrichtungs- und Optionsdialog."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

from . import planner
from .const import (
    CONF_BASE_FEE,
    CONF_BATTERY_CHARGE_ENERGY_SENSOR,
    CONF_CAPACITY,
    CONF_E3DC_DEVICE,
    CONF_EV2_MAX_SOC_SENSOR,
    CONF_EV2_NAME,
    CONF_EV2_PLUG_SENSOR,
    CONF_EV2_SOC_SENSOR,
    CONF_EV_MAX_SOC_SENSOR,
    CONF_EV_NAME,
    CONF_EV_SOC_SENSOR,
    CONF_GRID_IMPORT_SENSOR,
    CONF_HOUSE_ENERGY_SENSOR,
    CONF_HOUSE_POWER_SENSOR,
    CONF_HP_MODEL,
    CONF_HP_OFFSET,
    CONF_MAX_CHARGE_W,
    CONF_MAX_DISCHARGE_W,
    CONF_OUTDOOR_TEMP,
    CONF_PRICE_NORMAL,
    CONF_PV_ENERGY_SENSOR,
    CONF_PV_POWER_SENSOR,
    CONF_SG1,
    CONF_SG2,
    CONF_SG_SURPLUS_SENSOR,
    CONF_SOC_SENSOR,
    CONF_SOLCAST_TODAY,
    CONF_SOLCAST_TOMORROW,
    CONF_TARIFF_START,
    CONF_TARIFF_WINDOWS,
    CONF_WALLBOXES,
    CONF_WEATHER,
    DEFAULT_BASE_FEE,
    DEFAULT_BATTERY_CHARGE_ENERGY_SENSOR,
    DEFAULT_CAPACITY,
    DEFAULT_EV2_MAX_SOC_SENSOR,
    DEFAULT_EV2_NAME,
    DEFAULT_EV2_PLUG_SENSOR,
    DEFAULT_EV2_SOC_SENSOR,
    DEFAULT_EV_MAX_SOC_SENSOR,
    DEFAULT_EV_NAME,
    DEFAULT_EV_SOC_SENSOR,
    DEFAULT_GRID_IMPORT_SENSOR,
    DEFAULT_HOUSE_ENERGY_SENSOR,
    DEFAULT_HP_MODEL,
    DEFAULT_MAX_CHARGE_W,
    DEFAULT_MAX_DISCHARGE_W,
    DEFAULT_PRICE_NORMAL,
    DEFAULT_PV_ENERGY_SENSOR,
    DEFAULT_TARIFF,
    DEFAULT_TARIFF_START,
    DEFAULT_WALLBOXES,
    DOMAIN,
)

# Vorbelegung passend zu Thomas' Installation
SUGGEST = {
    CONF_SOC_SENSOR: "sensor.s10e_pro_state_of_charge",
    CONF_HOUSE_POWER_SENSOR: "sensor.s10e_pro_house_consumption",
    CONF_SOLCAST_TODAY: "sensor.solcast_pv_forecast_prognose_heute",
    CONF_SOLCAST_TOMORROW: "sensor.solcast_pv_forecast_prognose_morgen",
    CONF_WEATHER: "weather.forecast_home",
    CONF_OUTDOOR_TEMP: "sensor.ws2900_v2_02_03_outdoor_temperature_2",
    CONF_SG1: "switch.sg_ready1",
    CONF_SG2: "switch.sg_ready2",
    CONF_SG_SURPLUS_SENSOR: "sensor.s10e_pro_sg_ready",
    CONF_HP_OFFSET: "number.remko_mqtt_kalter_warmer",
    CONF_EV_SOC_SENSOR: DEFAULT_EV_SOC_SENSOR,
    CONF_GRID_IMPORT_SENSOR: DEFAULT_GRID_IMPORT_SENSOR,
    CONF_BATTERY_CHARGE_ENERGY_SENSOR: DEFAULT_BATTERY_CHARGE_ENERGY_SENSOR,
    CONF_PV_ENERGY_SENSOR: DEFAULT_PV_ENERGY_SENSOR,
    CONF_HOUSE_ENERGY_SENSOR: DEFAULT_HOUSE_ENERGY_SENSOR,
    CONF_EV_MAX_SOC_SENSOR: DEFAULT_EV_MAX_SOC_SENSOR,
    CONF_EV2_SOC_SENSOR: DEFAULT_EV2_SOC_SENSOR,
    CONF_EV2_MAX_SOC_SENSOR: DEFAULT_EV2_MAX_SOC_SENSOR,
    CONF_EV2_PLUG_SENSOR: DEFAULT_EV2_PLUG_SENSOR,
}


def _ent(domain: str | list[str]) -> sel.EntitySelector:
    return sel.EntitySelector(sel.EntitySelectorConfig(domain=domain))


def _num(mn: float, mx: float, step: float | str, unit: str | None = None) -> sel.NumberSelector:
    return sel.NumberSelector(
        sel.NumberSelectorConfig(min=mn, max=mx, step=step, unit_of_measurement=unit, mode="box")
    )


def _opt(key: str, cur: dict, default: Any = None, required: bool = True):
    val = cur.get(key, SUGGEST.get(key, default))
    cls = vol.Required if required else vol.Optional
    if val is None:
        return cls(key)
    return cls(key, description={"suggested_value": val}) if not required else cls(key, default=val)


def schema_basic(cur: dict) -> vol.Schema:
    return vol.Schema(
        {
            _opt(CONF_E3DC_DEVICE, cur): sel.DeviceSelector(
                sel.DeviceSelectorConfig(integration="e3dc_rscp")
            ),
            _opt(CONF_SOC_SENSOR, cur): _ent("sensor"),
            _opt(CONF_HOUSE_POWER_SENSOR, cur): _ent("sensor"),
            _opt(CONF_PV_POWER_SENSOR, cur, required=False): _ent("sensor"),
            _opt(CONF_GRID_IMPORT_SENSOR, cur, required=False): _ent("sensor"),
            _opt(CONF_BATTERY_CHARGE_ENERGY_SENSOR, cur, required=False): _ent("sensor"),
            _opt(CONF_PV_ENERGY_SENSOR, cur, required=False): _ent("sensor"),
            _opt(CONF_HOUSE_ENERGY_SENSOR, cur, required=False): _ent("sensor"),
            _opt(CONF_CAPACITY, cur, DEFAULT_CAPACITY): _num(1, 200, 0.1, "kWh"),
            _opt(CONF_MAX_CHARGE_W, cur, DEFAULT_MAX_CHARGE_W): _num(500, 30000, 100, "W"),
            _opt(CONF_MAX_DISCHARGE_W, cur, DEFAULT_MAX_DISCHARGE_W): _num(500, 30000, 100, "W"),
            _opt(CONF_SOLCAST_TODAY, cur): _ent("sensor"),
            _opt(CONF_SOLCAST_TOMORROW, cur): _ent("sensor"),
            _opt(CONF_WEATHER, cur): _ent("weather"),
            _opt(CONF_OUTDOOR_TEMP, cur, required=False): _ent("sensor"),
        }
    )


def schema_tariff(cur: dict) -> vol.Schema:
    return vol.Schema(
        {
            _opt(CONF_TARIFF_WINDOWS, cur, DEFAULT_TARIFF): sel.TextSelector(
                sel.TextSelectorConfig(multiline=True)
            ),
            _opt(CONF_PRICE_NORMAL, cur, DEFAULT_PRICE_NORMAL): _num(0, 2, "any", "€/kWh"),
            _opt(CONF_BASE_FEE, cur, DEFAULT_BASE_FEE): _num(0, 200, 0.01, "€/Monat"),
            _opt(CONF_TARIFF_START, cur, DEFAULT_TARIFF_START): sel.DateSelector(),
        }
    )


def schema_devices(cur: dict) -> vol.Schema:
    return vol.Schema(
        {
            _opt(CONF_WALLBOXES, cur, DEFAULT_WALLBOXES, required=False): sel.TextSelector(),
            _opt(CONF_EV_NAME, cur, DEFAULT_EV_NAME, required=False): sel.TextSelector(),
            _opt(CONF_EV_SOC_SENSOR, cur, required=False): _ent("sensor"),
            _opt(CONF_EV_MAX_SOC_SENSOR, cur, required=False): _ent(["sensor", "number"]),
            _opt(CONF_EV2_NAME, cur, DEFAULT_EV2_NAME, required=False): sel.TextSelector(),
            _opt(CONF_EV2_SOC_SENSOR, cur, required=False): _ent("sensor"),
            _opt(CONF_EV2_MAX_SOC_SENSOR, cur, required=False): _ent(["sensor", "number"]),
            _opt(CONF_EV2_PLUG_SENSOR, cur, required=False): _ent("binary_sensor"),
            _opt(CONF_SG1, cur, required=False): _ent("switch"),
            _opt(CONF_SG2, cur, required=False): _ent("switch"),
            _opt(CONF_SG_SURPLUS_SENSOR, cur, required=False): _ent("sensor"),
            _opt(CONF_HP_OFFSET, cur, required=False): _ent(["number", "input_number"]),
            _opt(CONF_HP_MODEL, cur, DEFAULT_HP_MODEL): sel.TextSelector(),
        }
    )


def _validate_tariff(data: dict) -> dict[str, str]:
    try:
        w = planner.parse_tariff(data[CONF_TARIFF_WINDOWS])
        if not any(x.level == planner.LOW for x in w):
            return {CONF_TARIFF_WINDOWS: "no_low_window"}
    except Exception:  # noqa: BLE001
        return {CONF_TARIFF_WINDOWS: "invalid_tariff"}
    return {}


def _validate_devices(data: dict) -> dict[str, str]:
    try:
        planner.parse_model(data.get(CONF_HP_MODEL, ""))
    except Exception:  # noqa: BLE001
        return {CONF_HP_MODEL: "invalid_model"}
    return {}


class EnergiemanagerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_tariff()
        return self.async_show_form(step_id="user", data_schema=schema_basic({}))

    async def async_step_tariff(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            errors = _validate_tariff(user_input)
            if not errors:
                self._data.update(user_input)
                return await self.async_step_devices()
        return self.async_show_form(
            step_id="tariff", data_schema=schema_tariff(user_input or {}), errors=errors
        )

    async def async_step_devices(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            errors = _validate_devices(user_input)
            if not errors:
                self._data.update(user_input)
                return self.async_create_entry(title="Energiemanager", data=self._data)
        return self.async_show_form(
            step_id="devices", data_schema=schema_devices(user_input or {}), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EnergiemanagerOptionsFlow()


class EnergiemanagerOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._opts: dict[str, Any] = {}

    @property
    def _cur(self) -> dict:
        return {**self.config_entry.data, **self.config_entry.options, **self._opts}

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["basic", "tariff", "devices"])

    async def async_step_basic(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self._cur, **user_input})
        return self.async_show_form(step_id="basic", data_schema=schema_basic(self._cur))

    async def async_step_tariff(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            errors = _validate_tariff(user_input)
            if not errors:
                return self.async_create_entry(data={**self._cur, **user_input})
        return self.async_show_form(
            step_id="tariff", data_schema=schema_tariff(self._cur), errors=errors
        )

    async def async_step_devices(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            errors = _validate_devices(user_input)
            if not errors:
                return self.async_create_entry(data={**self._cur, **user_input})
        return self.async_show_form(
            step_id="devices", data_schema=schema_devices(self._cur), errors=errors
        )
