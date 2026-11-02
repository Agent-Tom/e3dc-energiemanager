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

from .coordinator import EMState, EnergyCoordinator
from .entity import EMEntity


def _plan(s: EMState):
    return s.plan or s.preview


@dataclass(frozen=True, kw_only=True)
class EMSensorDescription(SensorEntityDescription):
    value: Callable[[EMState], Any]
    attrs: Callable[[EMState, EnergyCoordinator], dict] | None = None


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
