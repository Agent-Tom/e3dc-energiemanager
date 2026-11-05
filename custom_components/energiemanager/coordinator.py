"""Koordinator: sammelt Daten, plant und steuert Akku, Wallboxen und Wärmepumpe."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import planner
from .const import (
    CONF_CAPACITY,
    CONF_BASE_FEE,
    CONF_BATTERY_CHARGE_ENERGY_SENSOR,
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
    CONF_HP_CURVE,
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
    DEFAULT_HP_CURVE,
    DEFAULT_HP_MODEL,
    DEFAULT_MAX_CHARGE_W,
    DEFAULT_MAX_DISCHARGE_W,
    DEFAULT_PRICE_NORMAL,
    DEFAULT_PV_ENERGY_SENSOR,
    DEFAULT_TARIFF,
    DEFAULT_TARIFF_START,
    DOMAIN,
    EV_DEFAULT_POWER_KW,
    EV_EFFICIENCY,
    EV_FINISH_BUFFER_MIN,
    EV_TOPUP_FROM_PCT,
    EV_TOPUP_POWER_FACTOR,
    POWER_MODE_REFRESH_S,
    PRICE_HISTORY_DAYS,
    PRICE_HISTORY_YEARS,
    PRICE_STATS_INTERVAL_MIN,
    SETTINGS_NUMBERS,
    SETTINGS_SWITCHES,
    SUMMER_CHARGE_MARGIN_W,
    SUMMER_CHARGE_STEP_W,
    SUMMER_HYST_PCT,
    SUMMER_MIN_CLIP_KWH,
    UPDATE_INTERVAL_S,
    WALLBOX_SURPLUS_MODES,
    WALLBOX_TOGGLE_COOLDOWN_S,
)

_LOGGER = logging.getLogger(__name__)

# e3dc_rscp power modes
PM_NORMAL, PM_IDLE, PM_DISCHARGE, PM_CHARGE, PM_GRID_CHARGE = 0, 1, 2, 3, 4


@dataclass
class BatteryCommand:
    power_mode: int = PM_NORMAL
    power_value: int = 0
    max_charge: int | None = None      # None = keine Begrenzung
    max_discharge: int | None = None


@dataclass
class EMState:
    level: str = planner.NORMAL
    price: float = 0.0
    soc: float | None = None
    plan: planner.ChargePlan | None = None
    preview: planner.ChargePlan | None = None
    battery_cmd: BatteryCommand = field(default_factory=BatteryCommand)
    battery_reason: str = ""
    charge_power: int = 0
    summer_clip_kwh: float | None = None       # erwartete PV-Energie über der AC-Grenze (Rest des Tages)
    summer_clip_start: datetime | None = None
    summer_clip_end: datetime | None = None
    summer_soc_ceiling: float | None = None
    summer_charge_limit: int | None = None     # Ladegrenze in W während Sperre und Spitze
    hp_offset: float | None = None
    hp_sg_state: int = 0
    wallbox_status: dict[str, str] = field(default_factory=dict)
    wallbox_state: dict[str, str | None] = field(default_factory=dict)  # ausgesteckt/angeschlossen/laedt
    wallbox_ev: dict[str, dict[str, Any]] = field(default_factory=dict)  # Zielladung zur Anzeige
    wallbox_car: dict[str, str | None] = field(default_factory=dict)  # erkanntes Auto je Wallbox
    profile_kw: list[float] = field(default_factory=list)
    price_stats: dict[str, planner.PriceStats | None] = field(default_factory=dict)  # day/month/year
    price_stats_at: datetime | None = None
    price_history: dict[str, list[tuple[datetime, float, float]]] = field(default_factory=dict)
    t_history: float | None = None
    last_error: str | None = None


def _f(hass: HomeAssistant, entity_id: str | None, default: float | None = None) -> float | None:
    if not entity_id:
        return default
    st = hass.states.get(entity_id)
    if st is None or st.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
        return default
    try:
        return float(st.state)
    except ValueError:
        return default


def _changes(rows: list[dict[str, Any]]) -> dict[Any, float]:
    """Statistikzeilen → {Beginn: Änderung}."""
    return {r["start"]: float(r.get("change") or 0.0) for r in rows}


def _kw(hass: HomeAssistant, entity_id: str | None) -> float | None:
    """Leistung in kW, egal ob Sensor W oder kW liefert."""
    val = _f(hass, entity_id)
    if val is None:
        return None
    st = hass.states.get(entity_id)
    unit = (st.attributes.get("unit_of_measurement") or "").lower() if st else ""
    return val / 1000 if unit == "w" else val


class EnergyCoordinator(DataUpdateCoordinator[EMState]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_S),
            config_entry=entry,
        )
        self.entry = entry
        cfg = {**entry.data, **entry.options}
        self.cfg = cfg
        self.windows = planner.parse_tariff(cfg.get(CONF_TARIFF_WINDOWS, DEFAULT_TARIFF))
        self.normal_price = float(cfg.get(CONF_PRICE_NORMAL, DEFAULT_PRICE_NORMAL))
        self.base_fee = float(cfg.get(CONF_BASE_FEE, DEFAULT_BASE_FEE))
        self.tariff_start = date.fromisoformat(str(cfg.get(CONF_TARIFF_START) or DEFAULT_TARIFF_START))
        self.grid_import_sensor = cfg.get(CONF_GRID_IMPORT_SENSOR, DEFAULT_GRID_IMPORT_SENSOR)
        # Energiezähler für den Netzanteil der Akkuladung (Wandlungsverluste)
        self.balance_sensors = {
            "battery": cfg.get(CONF_BATTERY_CHARGE_ENERGY_SENSOR, DEFAULT_BATTERY_CHARGE_ENERGY_SENSOR),
            "pv": cfg.get(CONF_PV_ENERGY_SENSOR, DEFAULT_PV_ENERGY_SENSOR),
            "house": cfg.get(CONF_HOUSE_ENERGY_SENSOR, DEFAULT_HOUSE_ENERGY_SENSOR),
        }
        self.capacity = float(cfg.get(CONF_CAPACITY, DEFAULT_CAPACITY))
        self.batt_max_charge = int(cfg.get(CONF_MAX_CHARGE_W, DEFAULT_MAX_CHARGE_W))
        self.batt_max_discharge = int(cfg.get(CONF_MAX_DISCHARGE_W, DEFAULT_MAX_DISCHARGE_W))
        self.hp_model = planner.parse_model(cfg.get(CONF_HP_MODEL, DEFAULT_HP_MODEL))
        self.hp_curve = planner.parse_curve(cfg.get(CONF_HP_CURVE, DEFAULT_HP_CURVE))
        self.wallboxes = [
            w.strip().lower()
            for w in str(cfg.get(CONF_WALLBOXES, "")).split(",")
            if w.strip()
        ]

        # Laufzeit-Einstellungen (von Number/Switch/Select-Entitäten gepflegt)
        self.settings: dict[str, Any] = {k: v[0] for k, v in SETTINGS_NUMBERS.items()}
        self.settings.update(SETTINGS_SWITCHES)
        self.wallbox_modes: dict[str, str] = {w: "ueberschuss_niedrigtarif" for w in self.wallboxes}
        # Autos für die Zielladung nach Ladestand; das zweite nur mit Ladestand-Sensor
        self.cars: dict[str, dict[str, Any]] = {
            str(cfg.get(CONF_EV_NAME) or DEFAULT_EV_NAME): {
                "soc": cfg.get(CONF_EV_SOC_SENSOR, DEFAULT_EV_SOC_SENSOR),
                "max": cfg.get(CONF_EV_MAX_SOC_SENSOR, DEFAULT_EV_MAX_SOC_SENSOR),
                "plug": None,
                "capacity": "ev_capacity_kwh",
            },
        }
        ev2_soc = cfg.get(CONF_EV2_SOC_SENSOR, DEFAULT_EV2_SOC_SENSOR)
        if ev2_soc:
            self.cars[str(cfg.get(CONF_EV2_NAME) or DEFAULT_EV2_NAME)] = {
                "soc": ev2_soc,
                "max": cfg.get(CONF_EV2_MAX_SOC_SENSOR, DEFAULT_EV2_MAX_SOC_SENSOR),
                "plug": cfg.get(CONF_EV2_PLUG_SENSOR, DEFAULT_EV2_PLUG_SENSOR),
                "capacity": "ev2_capacity_kwh",
            }
        names = list(self.cars)
        # Zielladung je Wallbox (von Switch/Time/Number/Select-Entitäten gepflegt)
        self.ev: dict[str, dict[str, Any]] = {
            w: {
                "ev_target": False,
                "ev_time": time(5, 30),
                "ev_soc": 100.0,
                "ev_kwh": 20.0,
                "ev_type": "ladestand" if self.cars[names[0]]["soc"] else "energie",
                # Vorgabe-Auto, wenn mehrere Wallboxen belegt sind: der Reihe nach
                "ev_car": names[min(i, len(names) - 1)],
            }
            for i, w in enumerate(self.wallboxes)
        }

        self.state = EMState()
        self._locked_plans: dict[str, planner.ChargePlan] = {}
        self._profile_at: datetime | None = None
        self._applied_cmd: BatteryCommand | None = None
        self._applied_at: datetime | None = None
        self._wb_last_toggle: dict[str, datetime] = {}
        self._ev_soc_ref: dict[str, tuple[float, float]] = {}
        self._temp_forecast: list[tuple[datetime, float]] = []
        self._temp_fc_at: datetime | None = None
        self._released = False
        self._summer_block_day: date | None = None

    # ------------------------------------------------------------ Hilfen
    @property
    def simulation(self) -> bool:
        return bool(self.settings["simulation"])

    def setting(self, key: str) -> Any:
        return self.settings[key]

    async def async_set_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value
        if key == "battery_loss_pct":
            self.state.price_stats_at = None
        if key == "simulation":
            # Beim Umschalten alles neu senden, sonst gilt der simulierte Stand als gesendet
            self._applied_cmd = None
            if value:
                # Zurück in die Simulation: Akku wieder dem E3DC überlassen
                self.settings["simulation"] = False
                self._released = False
                await self._async_release()
                self.settings["simulation"] = True
                self._released = False
        await self.async_request_refresh()

    async def async_set_wallbox_mode(self, wb: str, mode: str) -> None:
        self.wallbox_modes[wb] = mode
        await self.async_request_refresh()

    async def async_set_ev(self, wb: str, key: str, value: Any) -> None:
        self.ev[wb][key] = value
        await self.async_request_refresh()

    async def _call(self, domain: str, service: str, data: dict) -> None:
        if self.simulation:
            _LOGGER.debug("[Simulation] %s.%s %s", domain, service, data)
            return
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except Exception as err:  # noqa: BLE001
            self.state.last_error = f"{domain}.{service}: {err}"
            _LOGGER.warning("Aufruf %s.%s fehlgeschlagen: %s", domain, service, err)

    # ------------------------------------------------------------ Daten
    async def _async_load_history(self, now: datetime) -> None:
        """Stündliches Verbrauchsprofil und Temperaturmittel aus der Recorder-Statistik."""
        if self._profile_at and now - self._profile_at < timedelta(hours=6):
            return
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period

        days = int(self.settings["history_days"])
        start = dt_util.as_utc(now - timedelta(days=days))
        end = dt_util.as_utc(now)
        house = self.cfg.get(CONF_HOUSE_POWER_SENSOR)
        temp = self.cfg.get(CONF_OUTDOOR_TEMP)
        ids = {i for i in (house, temp) if i}
        if not ids:
            return
        try:
            stats = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period, self.hass, start, end, ids, "hour", None, {"mean"}
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Statistik konnte nicht geladen werden: %s", err)
            return

        st = self.hass.states.get(house) if house else None
        div = 1000 if st and (st.attributes.get("unit_of_measurement") or "").lower() == "w" else 1
        buckets: list[list[float]] = [[] for _ in range(24)]
        for row in stats.get(house, []):
            mean = row.get("mean")
            if mean is None:
                continue
            ts = row["start"]
            ts_dt = dt_util.utc_from_timestamp(ts) if isinstance(ts, (int, float)) else ts
            buckets[dt_util.as_local(ts_dt).hour].append(mean / div)
        all_vals = [v for b in buckets for v in b]
        fallback = sum(all_vals) / len(all_vals) if all_vals else 1.5
        self.state.profile_kw = [round(sum(b) / len(b), 3) if b else fallback for b in buckets]

        temps = [r["mean"] for r in stats.get(temp, []) if r.get("mean") is not None] if temp else []
        self.state.t_history = round(sum(temps) / len(temps), 1) if temps else None
        self._profile_at = now

    async def _async_load_price_stats(self, now: datetime) -> None:
        """Ø Strompreis für Tag, Monat und Jahr aus der Statistik des Netzbezugs.

        Volle Stunden kommen aus der Stundenstatistik, die laufende Stunde aus der
        5-Minuten-Statistik. Gerechnet wird mit dem eingestellten Tarif, frühestens
        ab Tarifbeginn. Netzstrom, der über den Hausakku geht, bekommt einen
        Aufschlag für die Wandlungsverluste; den Anteil liefert die Bilanz aus
        Akkuladung, PV und Hausverbrauch je Abschnitt.
        """
        at = self.state.price_stats_at
        if at and now - at < timedelta(minutes=PRICE_STATS_INTERVAL_MIN):
            return
        sensor = self.grid_import_sensor
        if not sensor:
            return
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period

        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tariff_start = midnight.replace(
            year=self.tariff_start.year, month=self.tariff_start.month, day=self.tariff_start.day
        )
        starts = {
            "day": midnight,
            "month": midnight.replace(day=1),
            "year": midnight.replace(month=1, day=1),
        }
        # Ab hier laden: genug für den Verlauf der Monate und Jahre
        first = max(starts["year"].replace(year=starts["year"].year - PRICE_HISTORY_YEARS), tariff_start)
        if max(starts["year"], tariff_start) > now:
            self.state.price_stats = {}
            self.state.price_history = {}
            self.state.price_stats_at = now
            return
        hour = now.replace(minute=0, second=0, microsecond=0)
        rec = get_instance(self.hass)
        ids = {sensor} | {e for e in self.balance_sensors.values() if e}
        rows: list[tuple[datetime, float, float]] = []
        try:
            for period, a, b in (("hour", first, hour), ("5minute", max(first, hour), now)):
                if a >= b:
                    continue
                stats = await rec.async_add_executor_job(
                    statistics_during_period,
                    self.hass, dt_util.as_utc(a), dt_util.as_utc(b), ids, period, None, {"change"},
                )
                by_start: dict[str, dict[Any, float]] = {
                    key: _changes(stats.get(ent, [])) for key, ent in self.balance_sensors.items() if ent
                }
                for ts, grid in _changes(stats.get(sensor, [])).items():
                    batt = planner.grid_to_battery(
                        grid,
                        by_start.get("battery", {}).get(ts, 0.0),
                        by_start.get("pv", {}).get(ts, 0.0),
                        by_start.get("house", {}).get(ts, 0.0),
                    )
                    ts_dt = dt_util.utc_from_timestamp(ts) if isinstance(ts, (int, float)) else ts
                    rows.append((dt_util.as_local(ts_dt), grid, batt))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Statistik des Netzbezugs konnte nicht geladen werden: %s", err)
            return
        loss = float(self.settings["battery_loss_pct"])
        self.state.price_stats = {
            key: planner.price_stats(
                rows, max(start, tariff_start), now, self.windows, self.normal_price, self.base_fee, loss
            )
            if max(start, tariff_start) <= now
            else None
            for key, start in starts.items()
        }
        hist = {
            key: planner.price_history(rows, self.windows, self.normal_price, loss, key)
            for key in ("day", "month", "year")
        }
        hist["day"] = hist["day"][-PRICE_HISTORY_DAYS:]
        self.state.price_history = hist
        self.state.price_stats_at = now

    async def _async_load_temp_forecast(self, now: datetime) -> None:
        if self._temp_fc_at and now - self._temp_fc_at < timedelta(minutes=30):
            return
        weather = self.cfg.get(CONF_WEATHER)
        if not weather:
            return
        try:
            resp = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": weather, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Wettervorhersage fehlgeschlagen: %s", err)
            return
        out = []
        for f in (resp or {}).get(weather, {}).get("forecast", []):
            d = dt_util.parse_datetime(str(f.get("datetime")))
            t = f.get("temperature")
            if d is not None and isinstance(t, (int, float)):
                out.append((dt_util.as_local(d), float(t)))
        self._temp_forecast = out
        self._temp_fc_at = now

    def _pv_forecast(self, key: str | None = None) -> list[tuple[datetime, float]]:
        if key is None:
            key = "pv_estimate10" if self.settings["pv_p10"] else "pv_estimate"
        out: list[tuple[datetime, float]] = []
        for ent in (self.cfg.get(CONF_SOLCAST_TODAY), self.cfg.get(CONF_SOLCAST_TOMORROW)):
            st = self.hass.states.get(ent) if ent else None
            if not st:
                continue
            for p in st.attributes.get("detailedHourly") or []:
                ps = p.get("period_start")
                d = ps if isinstance(ps, datetime) else dt_util.parse_datetime(str(ps))
                if d is not None:
                    out.append((dt_util.as_local(d), float(p.get(key, p.get("pv_estimate", 0)) or 0)))
        return out

    # ------------------------------------------------------------ Zyklus
    async def _async_update_data(self) -> EMState:
        now = dt_util.now()
        s = self.state
        s.last_error = None
        await self._async_load_history(now)
        await self._async_load_temp_forecast(now)
        await self._async_load_price_stats(now)

        s.level = planner.current_level(self.windows, now)
        s.price = planner.current_price(self.windows, now, self.normal_price)
        s.soc = _f(self.hass, self.cfg.get(CONF_SOC_SENSOR))

        self._update_plan(now)

        if not self.settings["control_active"]:
            await self._async_release()
            s.battery_reason = "Regelung aus"
            return s
        self._released = False

        await self._async_battery(now)
        await self._async_wallboxes(now)
        await self._async_heatpump(now)
        return s

    def _update_plan(self, now: datetime) -> None:
        s = self.state
        win = planner.relevant_low_window(self.windows, now)
        if win is None or not s.profile_kw:
            s.plan = s.preview = None
            return
        kwargs = dict(
            window=win,
            windows=self.windows,
            profile_kw=s.profile_kw,
            pv_forecast=self._pv_forecast(),
            temp_forecast=self._temp_forecast,
            t_history=s.t_history,
            hp_model=self.hp_model,
            capacity_kwh=self.capacity,
            safety=float(self.settings["safety_factor"]),
            buffer_pct=float(self.settings["buffer_pct"]),
            min_soc=float(self.settings["min_target_soc"]),
            max_soc=float(self.settings["max_target_soc"]),
        )
        if win.start <= now:
            # Im Fenster: Plan beim Eintritt einfrieren
            if win.key not in self._locked_plans:
                self._locked_plans = {win.key: planner.build_plan(**kwargs)}
            s.plan = self._locked_plans[win.key]
            s.preview = None
        else:
            s.plan = None
            s.preview = planner.build_plan(**kwargs)

    # ------------------------------------------------------------ Akku
    def _summer(self, now: datetime) -> tuple[int | None, float | None]:
        """(Ladegrenze in W, Entladen bis SoC) – jeweils None, wenn nichts zu tun ist.

        Greift nur, wenn die PV-Prognose (P50) heute noch über der AC-Grenze liegt.
        Bis zur Ladegrenze (100 % minus erwarteter Überschuss minus Reserve) lädt
        der Akku frei. Darüber lässt die Ladegrenze nur den PV-Anteil über der
        AC-Grenze in den Akku: vor der Spitze praktisch nichts, in der Spitze genau
        das, was sonst abgeregelt würde. Einmal erreicht, bleibt die Begrenzung bis
        zur Spitze stehen; in der Spitze fällt sie weg, sobald deutlich mehr Platz
        frei ist als noch gebraucht wird.

        Die aktive Entladung schafft vor der Spitze Platz bis zur Ladegrenze, abzüglich
        dessen, was das Haus bis dahin ohnehin aus dem Akku zieht.
        """
        s = self.state
        day_end = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        ac_kw = float(self.settings["summer_ac_limit_w"]) / 1000
        forecast = self._pv_forecast("pv_estimate")
        clip_kwh, clip_start, clip_end = planner.clipping(forecast, now, day_end, ac_kw, self.batt_max_charge / 1000)
        s.summer_clip_kwh = round(clip_kwh, 2)
        s.summer_clip_start = clip_start
        s.summer_clip_end = clip_end
        s.summer_soc_ceiling = None
        s.summer_charge_limit = None
        if clip_start is None or clip_kwh < SUMMER_MIN_CLIP_KWH:
            self._summer_block_day = None
            return None, None
        ceiling = planner.summer_soc_ceiling(clip_kwh, self.capacity, float(self.settings["summer_reserve_pct"]))
        s.summer_soc_ceiling = round(ceiling, 1)

        h = now.hour + now.minute / 60
        if not self.settings["summer_mode"] or h < self.settings["summer_morning_start_h"]:
            self._summer_block_day = None
            return None, None
        if s.soc is None:
            return None, None
        if s.soc >= ceiling:
            self._summer_block_day = now.date()
        elif now >= clip_start and s.soc < ceiling - SUMMER_HYST_PCT:
            self._summer_block_day = None
        if self._summer_block_day != now.date():
            return None, None

        pv_kw = _kw(self.hass, self.cfg.get(CONF_PV_POWER_SENSOR))
        if pv_kw is None:
            pv_kw = next((kw for p, kw in forecast if p <= now < p + timedelta(hours=1)), 0.0)
        limit = planner.peak_charge_limit_w(
            pv_kw, ac_kw, self.batt_max_charge, SUMMER_CHARGE_MARGIN_W, SUMMER_CHARGE_STEP_W
        )
        s.summer_charge_limit = limit

        discharge_to = None
        if now < clip_start and self.settings["summer_active_discharge"]:
            drain = planner.deficit(s.profile_kw, forecast, now, clip_start) if s.profile_kw else 0.0
            discharge_to = max(
                min(100.0, ceiling + drain / self.capacity * 100),
                float(self.settings["summer_morning_target_soc"]),
            )
            if s.soc <= discharge_to:
                discharge_to = None
        return limit, discharge_to

    def _summer_text(self, now: datetime) -> str:
        s = self.state
        if s.summer_clip_start is None:
            return ""
        if now < s.summer_clip_start:
            return f"ab {s.summer_clip_start:%H:%M} {s.summer_clip_kwh:.1f} kWh über der AC-Grenze"
        return f"noch {s.summer_clip_kwh:.1f} kWh über der AC-Grenze bis {s.summer_clip_end:%H:%M}"

    async def _async_battery(self, now: datetime) -> None:
        s = self.state
        cmd = BatteryCommand()
        reason = "Normalbetrieb (E3DC regelt selbst)"
        s.charge_power = 0
        # Immer rechnen, damit der Sensor auch im Niedrigtarif aktuell bleibt
        limit, discharge_to = self._summer(now)
        peak = self._summer_text(now)
        limit_text = f", Laden max. {limit} W ({peak})" if limit is not None else ""

        if s.level == planner.LOW and s.plan is not None and s.soc is not None:
            # Was die PV bis Fensterende über den Hausverbrauch hinaus liefert, nicht aus dem Netz laden
            pv_rest = (
                planner.surplus(s.profile_kw, self._pv_forecast(), now, s.plan.window_end) if s.profile_kw else 0.0
            )
            grid_target = planner.grid_charge_target(s.plan.target_soc, pv_rest, self.capacity)
            pv_text = f" (Rest {pv_rest:.1f} kWh aus PV)" if pv_rest >= 0.1 else ""
            if s.soc >= s.plan.target_soc - 1:
                status = f"Niedrigtarif: Ziel {s.plan.target_soc} % erreicht"
            elif s.soc >= grid_target - 1:
                status = f"Niedrigtarif: Ziel {s.plan.target_soc} % kommt aus PV{pv_text}"
            else:
                status = f"Niedrigtarif: Ziel {s.plan.target_soc} % nicht erreicht (Netzladung aus)"
            if self.settings["grid_charging"] and s.soc < grid_target - 1:
                pv_kw = _kw(self.hass, self.cfg.get(CONF_PV_POWER_SENSOR)) or 0
                house_kw = _kw(self.hass, self.cfg.get(CONF_HOUSE_POWER_SENSOR)) or 0
                p = planner.charge_power_w(
                    soc=s.soc,
                    target_soc=grid_target,
                    capacity_kwh=self.capacity,
                    now=now,
                    window_end=s.plan.window_end,
                    min_w=float(self.settings["grid_charge_min_w"]),
                    max_w=float(self.settings["grid_charge_max_w"]),
                    pv_surplus_w=max(pv_kw - house_kw, 0) * 1000,
                )
                cmd = BatteryCommand(power_mode=PM_GRID_CHARGE, power_value=p)
                s.charge_power = p
                reason = (
                    f"Netzladung {p} W: SoC {s.soc:.0f} % → {grid_target:.0f} %, "
                    f"Ziel {s.plan.target_soc} %{pv_text}"
                )
            elif self.settings["hold_in_low"]:
                cmd = BatteryCommand(max_discharge=0, max_charge=limit)
                reason = f"{status}, Entladung gesperrt{limit_text}"
            else:
                cmd = BatteryCommand(max_charge=limit)
                reason = f"{status}{limit_text}"
        elif discharge_to is not None:
            p = int(self.settings["summer_discharge_w"])
            # Grenze mitsenden, damit sie beim Wechsel zur Sperre nicht neu geschrieben wird
            cmd = BatteryCommand(power_mode=PM_DISCHARGE, power_value=p, max_charge=limit)
            reason = f"Sommer: entladen ({p} W) bis {discharge_to:.0f} %, {peak}"
        elif limit == 0:
            cmd = BatteryCommand(max_charge=0)
            reason = f"Sommer: Ladesperre bei {s.summer_soc_ceiling:.0f} %, {peak}"
        elif limit is not None:
            cmd = BatteryCommand(max_charge=limit)
            reason = f"Sommer: nur PV über der AC-Grenze laden (max. {limit} W), {peak}"

        s.battery_cmd = cmd
        s.battery_reason = reason
        await self._async_apply_battery(cmd, now)

    async def _async_apply_battery(self, cmd: BatteryCommand, now: datetime) -> None:
        dev = self.cfg.get(CONF_E3DC_DEVICE)
        if not dev:
            return
        prev = self._applied_cmd
        limits_changed = prev is None or (prev.max_charge, prev.max_discharge) != (
            cmd.max_charge,
            cmd.max_discharge,
        )
        mode_changed = (
            prev is None
            or prev.power_mode != cmd.power_mode
            or abs(prev.power_value - cmd.power_value) >= 300
        )
        refresh_due = (
            cmd.power_mode != PM_NORMAL
            and self._applied_at is not None
            and (now - self._applied_at).total_seconds() >= POWER_MODE_REFRESH_S
        )

        if limits_changed:
            if cmd.max_charge is None and cmd.max_discharge is None:
                await self._call("e3dc_rscp", "clear_power_limits", {"device_id": dev})
            else:
                await self._call(
                    "e3dc_rscp",
                    "set_power_limits",
                    {
                        "device_id": dev,
                        "max_charge": self.batt_max_charge if cmd.max_charge is None else cmd.max_charge,
                        "max_discharge": self.batt_max_discharge
                        if cmd.max_discharge is None
                        else cmd.max_discharge,
                    },
                )
        if mode_changed or refresh_due:
            data = {"device_id": dev, "power_mode": str(cmd.power_mode)}
            if cmd.power_mode != PM_NORMAL:
                data["power_value"] = max(cmd.power_value, 100)
            await self._call("e3dc_rscp", "set_power_mode", data)
            self._applied_at = now
        self._applied_cmd = cmd

    async def _async_release(self) -> None:
        if self._released:
            return
        dev = self.cfg.get(CONF_E3DC_DEVICE)
        if dev:
            await self._call("e3dc_rscp", "set_power_mode", {"device_id": dev, "power_mode": "0"})
            await self._call("e3dc_rscp", "clear_power_limits", {"device_id": dev})
        self._applied_cmd = None
        self._released = True

    async def async_shutdown_control(self) -> None:
        self._released = False
        await self._async_release()

    # ------------------------------------------------------------ Wallboxen
    async def _async_wallboxes(self, now: datetime) -> None:
        low = self.state.level == planner.LOW
        self.state.wallbox_car = planner.assign_cars(
            [w for w in self.wallboxes if self.hass.states.is_state(f"binary_sensor.{w}_plug", STATE_ON)],
            {name: self._car_plugged(car) for name, car in self.cars.items()},
            {w: self.ev[w]["ev_car"] for w in self.wallboxes},
        )
        for wb in self.wallboxes:
            mode = self.wallbox_modes.get(wb, "aus")
            sun_sw = f"switch.{wb}_sun_mode"
            toggle = f"button.{wb}_toggle_charging"
            charging = self.hass.states.is_state(f"binary_sensor.{wb}_charging", STATE_ON)
            plug = self.hass.states.get(f"binary_sensor.{wb}_plug")
            plugged = plug is not None and plug.state == STATE_ON
            if plug is None or plug.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self.state.wallbox_state[wb] = None
            else:
                self.state.wallbox_state[wb] = "laedt" if charging else "angeschlossen" if plugged else "ausgesteckt"

            if mode == "netzladen":
                want_sun, want_charge = False, True
            elif mode == "niedrigtarif":
                want_sun, want_charge = False, low
            elif mode == "ueberschuss_niedrigtarif":
                want_sun, want_charge = (not low), True
            elif mode == "nur_pv":
                want_sun, want_charge = True, True
            else:
                want_sun, want_charge = True, False

            status = f"{mode}: {'lädt' if charging else 'lädt nicht'}"
            ev = self.ev[wb]
            self.state.wallbox_ev[wb] = {}
            # Zielladung ersetzt die Netzladung des Modus; „Sofort laden“ hat Vorrang
            if ev["ev_target"] and mode != "netzladen":
                if not plugged:
                    self.state.wallbox_ev[wb] = {"begruendung": "wartet auf Auto"}
                else:
                    plan, surplus_ok, info = self._ev_plan(wb, now)
                    self.state.wallbox_ev[wb] = info
                    if plan is not None:
                        if plan.charge_now:
                            want_sun, want_charge = False, True
                        else:
                            want_sun = True
                            want_charge = surplus_ok and mode in WALLBOX_SURPLUS_MODES
                        status = f"Zielladung: {plan.reason}, {'lädt' if charging else 'lädt nicht'}"

            if not plugged:
                self.state.wallbox_status[wb] = f"{mode}: kein Auto"
                continue

            sun_on = self.hass.states.is_state(sun_sw, STATE_ON)
            if self.hass.states.get(sun_sw) is not None and sun_on != want_sun:
                await self._call("switch", "turn_on" if want_sun else "turn_off", {"entity_id": sun_sw})

            # Im Überschussmodus entscheidet E3DC selbst, ob geladen wird
            if not (want_sun and want_charge) and charging != want_charge:
                last = self._wb_last_toggle.get(wb)
                if last is None or (now - last).total_seconds() > WALLBOX_TOGGLE_COOLDOWN_S:
                    await self._call("button", "press", {"entity_id": toggle})
                    self._wb_last_toggle[wb] = now
                    status += " → umgeschaltet"
            self.state.wallbox_status[wb] = status

    def _ev_power_kw(self, wb: str) -> float:
        """Ladeleistung der Wallbox aus Ladestrom und Phasen."""
        amps = _f(self.hass, f"number.{wb}_max_charge_current")
        phases = _f(self.hass, f"sensor.{wb}_phases")
        if amps and phases:
            return amps * phases * 0.23
        return EV_DEFAULT_POWER_KW

    def _car_plugged(self, car: dict[str, Any]) -> bool | None:
        """Ladekabel des Autos: True/False, None ohne (lesbaren) Sensor."""
        st = self.hass.states.get(car["plug"]) if car["plug"] else None
        if st is None or st.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        return st.state == STATE_ON

    def _ev_soc(self, wb: str, car: dict[str, Any], charged: float) -> float | None:
        """Ladestand des Autos, zwischen zwei Meldungen um die geladene Energie fortgeschrieben.

        Der Fahrzeugsensor meldet nur gelegentlich; ohne Fortschreibung würde die
        Planung mit einem veralteten Stand zu lange laden.
        """
        soc = _f(self.hass, car["soc"])
        if soc is None:
            return None
        ref = self._ev_soc_ref.get(wb)
        if ref is None or ref[0] != soc or charged < ref[1]:
            self._ev_soc_ref[wb] = (soc, charged)
            return soc
        cap = float(self.settings[car["capacity"]])
        return min(100.0, soc + (charged - ref[1]) * EV_EFFICIENCY / cap * 100)

    def _ev_plan(self, wb: str, now: datetime) -> tuple[planner.EvPlan | None, bool, dict[str, Any]]:
        """Zielladung: Plan, ob PV-Überschuss zusätzlich laden darf, Anzeige-Attribute."""
        ev = self.ev[wb]
        deadline = planner.next_deadline(now, ev["ev_time"])
        power = self._ev_power_kw(wb)
        # Zähler der Wallbox: geladene Energie seit dem Anstecken
        charged = _f(self.hass, f"sensor.{wb}_energy_all", 0.0) or 0.0
        buffer = timedelta(minutes=EV_FINISH_BUFFER_MIN)
        info: dict[str, Any] = {
            "fertig_um": deadline.isoformat(),
            "ladeleistung_kw": round(power, 1),
            "geladen_kwh": round(charged, 1),
        }
        if ev["ev_type"] == "ladestand":
            name = self.state.wallbox_car.get(wb)
            info["fahrzeug"] = name
            if name is None:
                info["begruendung"] = "Fahrzeug nicht erkannt"
                return None, False, info
            car = self.cars[name]
            soc = self._ev_soc(wb, car, charged)
            if soc is None:
                info["begruendung"] = f"Ladestand {name} unbekannt"
                return None, False, info
            target = float(ev["ev_soc"])
            car_max = _f(self.hass, car["max"])
            if car_max:
                target = min(target, car_max)
            bulk_to = min(target, EV_TOPUP_FROM_PCT)
            cap = float(self.settings[car["capacity"]])
            bulk = max(0.0, bulk_to - soc) / 100 * cap
            top = max(0.0, target - max(soc, bulk_to)) / 100 * cap
            eff = power * EV_EFFICIENCY
            plan = planner.ev_plan(
                now, deadline, bulk, top, eff, eff * EV_TOPUP_POWER_FACTOR, self.windows, self.normal_price, buffer
            )
            surplus_ok = soc < bulk_to
            info.update(ziel=f"{target:.0f} %", ladestand=round(soc), fehlt_kwh=round(bulk + top, 1))
            if car_max and car_max < float(ev["ev_soc"]):
                info["hinweis"] = f"Auto begrenzt auf {car_max:.0f} %"
        else:
            rest = max(0.0, float(ev["ev_kwh"]) - charged)
            plan = planner.ev_plan(now, deadline, rest, 0.0, power, power, self.windows, self.normal_price, buffer)
            surplus_ok = True
            info.update(ziel=f"{float(ev['ev_kwh']):.0f} kWh", fehlt_kwh=round(rest, 1))
        info.update(
            begruendung=plan.reason,
            start=plan.start.isoformat() if plan.start else None,
            restladung_ab=plan.top_start.isoformat() if plan.top_start else None,
        )
        return plan, surplus_ok, info

    # ------------------------------------------------------------ Wärmepumpe
    async def _async_heatpump(self, now: datetime) -> None:
        s = self.state
        if not self.settings["hp_control"]:
            return
        sg1, sg2 = self.cfg.get(CONF_SG1), self.cfg.get(CONF_SG2)
        surplus = False
        sens = self.cfg.get(CONF_SG_SURPLUS_SENSOR)
        if sens and self.settings["hp_sg_on_surplus"]:
            surplus = self.hass.states.is_state(sens, "released")

        if s.level == planner.LOW or (surplus and s.level != planner.HIGH):
            sg = 3
        elif s.level == planner.HIGH and self.settings["hp_block_in_high"]:
            sg = 1
        else:
            sg = 0
        s.hp_sg_state = sg
        if sg1 and sg2:
            # SG-Ready: 0 = normal (aus/aus), 1 = Sperre (an/aus), 3 = Empfehlung (aus/an)
            want1, want2 = {0: (False, False), 1: (True, False), 3: (False, True)}[sg]
            for ent, want in ((sg1, want1), (sg2, want2)):
                if self.hass.states.get(ent) is not None and self.hass.states.is_state(ent, STATE_ON) != want:
                    await self._call("switch", "turn_on" if want else "turn_off", {"entity_id": ent})

        # Temperaturanhebung: Grundwert aus Prognose (morgen 07:00), im Niedrigtarif + Boost
        t_ref = None
        target_t = (now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
        if now.hour < 7:
            target_t = now.replace(hour=7, minute=0, second=0, microsecond=0)
        for d, t in self._temp_forecast:
            if d >= target_t:
                t_ref = t
                break
        if t_ref is None:
            t_ref = _f(self.hass, self.cfg.get(CONF_OUTDOOR_TEMP))
        base = planner.hp_base_offset(t_ref, self.hp_curve)
        offset = base + (float(self.settings["hp_boost_k"]) if s.level == planner.LOW else 0)
        s.hp_offset = offset
        num = self.cfg.get(CONF_HP_OFFSET)
        cur = _f(self.hass, num)
        if num and cur is not None and abs(cur - offset) > 0.01:
            await self._call("number", "set_value", {"entity_id": num, "value": offset})
