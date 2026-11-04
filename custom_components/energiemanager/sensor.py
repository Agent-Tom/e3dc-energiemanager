"""Sensoren: Tarif, Plan, Status."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower

from .const import WALLBOX_STATES
from .coordinator import EMState, EnergyCoordinator
from .entity import EMEntity


def _plan(s: EMState):
    return s.plan or s.preview


@dataclass(frozen=True, kw_only=True)
class EMSensorDescription(SensorEntityDescription):
    value: Callable[[EMState], Any]
    attrs: Callable[[EMState, EnergyCoordinator], dict] | None = None


def _avg_ct(s: EMState, key: str) -> float | None:
    p = s.price_stats.get(key)
    return round(p.avg * 100, 2) if p and p.avg is not None else None


def _avg_attrs(key: str) -> Callable[[EMState, EnergyCoordinator], dict]:
    def attrs(s: EMState, c: EnergyCoordinator) -> dict:
        p = s.price_stats.get(key)
        if p is None:
            return {}
        total = p.avg_total
        return {
            "netzbezug_kwh": round(p.kwh, 1),
            "arbeitskosten_eur": round(p.cost, 2),
            "ueber_akku_kwh": round(p.battery_kwh, 1),
            "verlustaufschlag_eur": round(p.loss_cost, 2),
            "grundpreis_eur": round(p.base_fee, 2),
            "kosten_gesamt_eur": round(p.cost + p.base_fee, 2),
            "mit_grundpreis_ct_kwh": round(total * 100, 2) if total is not None else None,
            "stand": s.price_stats_at.isoformat() if s.price_stats_at else None,
        }

    return attrs


def _plan_attrs(s: EMState, c: EnergyCoordinator) -> dict:
    p = _plan(s)
    if p is None:
        return {}
    return {
        "status": "aktiv" if s.plan else "Vorschau",
        "fenster_start": p.window_start.isoformat(),
        "fenster_ende": p.window_end.isoformat(),
        "deckung_bis": p.cover_end.isoformat(),
        "verbrauch_kwh": p.consumption_kwh,
        "temperaturfaktor": p.temp_factor,
        "temp_prognose": p.t_forecast,
        "temp_historie": p.t_history,
        "pv_kwh": p.pv_kwh,
        "bedarf_kwh": p.need_kwh,
        "begruendung": p.reason,
    }


SENSORS: tuple[EMSensorDescription, ...] = (
    EMSensorDescription(
        key="tariff_level",
        device_class=SensorDeviceClass.ENUM,
        options=["low", "normal", "high"],
        value=lambda s: s.level,
    ),
    EMSensorDescription(
        key="price",
        native_unit_of_measurement="EUR/kWh",
        suggested_display_precision=3,
        value=lambda s: s.price,
    ),
    *(
        EMSensorDescription(
            key=f"price_avg_{key}",
            native_unit_of_measurement="ct/kWh",
            suggested_display_precision=2,
            state_class=SensorStateClass.MEASUREMENT,
            value=lambda s, key=key: _avg_ct(s, key),
            attrs=_avg_attrs(key),
        )
        for key in ("day", "month", "year")
    ),
    EMSensorDescription(
        key="target_soc",
        native_unit_of_measurement=PERCENTAGE,
        value=lambda s: _plan(s).target_soc if _plan(s) else None,
        attrs=_plan_attrs,
    ),
    EMSensorDescription(
        key="need_kwh",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value=lambda s: _plan(s).need_kwh if _plan(s) else None,
    ),
    EMSensorDescription(
        key="charge_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda s: s.charge_power,
    ),
    EMSensorDescription(
        key="battery_action",
        value=lambda s: s.battery_reason[:255],
        attrs=lambda s, c: {
            "power_mode": s.battery_cmd.power_mode,
            "power_value": s.battery_cmd.power_value,
            "max_charge": s.battery_cmd.max_charge,
            "max_discharge": s.battery_cmd.max_discharge,
            "simulation": c.simulation,
            "letzter_fehler": s.last_error,
        },
    ),
    EMSensorDescription(
        key="summer_clip",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value=lambda s: s.summer_clip_kwh,
        attrs=lambda s, c: {
            "abregelung_ab": s.summer_clip_start.isoformat() if s.summer_clip_start else None,
            "abregelung_bis": s.summer_clip_end.isoformat() if s.summer_clip_end else None,
            "ladegrenze_soc": s.summer_soc_ceiling,
            "ladeleistung_max_w": s.summer_charge_limit,
        },
    ),
    EMSensorDescription(
        key="hp_offset",
        native_unit_of_measurement="K",
        value=lambda s: s.hp_offset,
        attrs=lambda s, c: {"sg_ready_status": s.hp_sg_state},
    ),
    EMSensorDescription(
        key="consumption_profile",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value=lambda s: round(sum(s.profile_kw) / 24, 2) if s.profile_kw else None,
        attrs=lambda s, c: {
            "stundenprofil_kw": s.profile_kw,
            "temperatur_mittel_historie": s.t_history,
        },
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coord = entry.runtime_data
    async_add_entities(EMSensor(coord, d) for d in SENSORS)
    async_add_entities(WallboxStateSensor(coord, wb) for wb in coord.wallboxes)


class EMSensor(EMEntity, SensorEntity):
    entity_description: EMSensorDescription

    def __init__(self, coordinator, description: EMSensorDescription):
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value(self.coordinator.state)

    @property
    def extra_state_attributes(self):
        fn = self.entity_description.attrs
        return fn(self.coordinator.state, self.coordinator) if fn else None


class WallboxStateSensor(EMEntity, SensorEntity):
    """Ausgesteckt, angeschlossen oder lädt; Attribute mit Modus und Zielladung."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = WALLBOX_STATES

    def __init__(self, coordinator, wb: str):
        super().__init__(coordinator, f"wallbox_state_{wb}")
        self._wb = wb
        self._attr_translation_key = "wallbox_state"
        self._attr_translation_placeholders = {"wallbox": wb.capitalize()}

    @property
    def native_value(self) -> str | None:
        return self.coordinator.state.wallbox_state.get(self._wb)

    @property
    def extra_state_attributes(self):
        s = self.coordinator.state
        ev = self.coordinator.ev[self._wb]
        return {
            "status": s.wallbox_status.get(self._wb),
            "zielladung_aktiv": ev["ev_target"],
            **{f"zielladung_{k}": v for k, v in s.wallbox_ev.get(self._wb, {}).items()},
        }
