"""Konstanten für den Energiemanager."""
from __future__ import annotations

DOMAIN = "energiemanager"
PLATFORMS = ["sensor", "switch", "number", "select", "time"]

# --- Grundkonfiguration ---
CONF_E3DC_DEVICE = "e3dc_device"
CONF_SOC_SENSOR = "soc_sensor"
CONF_HOUSE_POWER_SENSOR = "house_power_sensor"
CONF_PV_POWER_SENSOR = "pv_power_sensor"
CONF_CAPACITY = "battery_capacity_kwh"
CONF_MAX_CHARGE_W = "battery_max_charge_w"
CONF_MAX_DISCHARGE_W = "battery_max_discharge_w"
CONF_SOLCAST_TODAY = "solcast_today"
CONF_SOLCAST_TOMORROW = "solcast_tomorrow"
CONF_WEATHER = "weather_entity"
CONF_OUTDOOR_TEMP = "outdoor_temp_sensor"

# --- Tarif ---
CONF_TARIFF_WINDOWS = "tariff_windows"
CONF_PRICE_NORMAL = "price_normal"
CONF_BASE_FEE = "base_fee"
CONF_TARIFF_START = "tariff_start"
CONF_GRID_IMPORT_SENSOR = "grid_import_sensor"
CONF_BATTERY_CHARGE_ENERGY_SENSOR = "battery_charge_energy_sensor"
CONF_PV_ENERGY_SENSOR = "pv_energy_sensor"
CONF_HOUSE_ENERGY_SENSOR = "house_energy_sensor"

# --- Wallboxen ---
CONF_WALLBOXES = "wallboxes"
CONF_EV_SOC_SENSOR = "ev_soc_sensor"
CONF_EV_MAX_SOC_SENSOR = "ev_max_soc_sensor"

# --- Wärmepumpe ---
CONF_SG1 = "sg_ready_1_switch"
CONF_SG2 = "sg_ready_2_switch"
CONF_SG_SURPLUS_SENSOR = "sg_surplus_sensor"
CONF_HP_OFFSET = "hp_offset_number"
CONF_HP_CURVE = "hp_offset_curve"
CONF_HP_MODEL = "hp_consumption_model"

# --- Defaults (aus Thomas' Setup) ---
DEFAULT_TARIFF = "02:00-06:00=low@0.1825; 12:00-16:00=low@0.1825; 18:00-21:00=high@0.3026"
DEFAULT_PRICE_NORMAL = 0.2525
DEFAULT_BASE_FEE = 21.04  # €/Monat
DEFAULT_TARIFF_START = "2026-09-01"
DEFAULT_GRID_IMPORT_SENSOR = "sensor.s10e_pro_consumption_from_grid_today"
DEFAULT_BATTERY_CHARGE_ENERGY_SENSOR = "sensor.s10e_pro_battery_charge_today"
DEFAULT_PV_ENERGY_SENSOR = "sensor.s10e_pro_solar_production_today"
DEFAULT_HOUSE_ENERGY_SENSOR = "sensor.s10e_pro_house_consumption_today"
DEFAULT_CAPACITY = 32.6
DEFAULT_MAX_CHARGE_W = 12000
DEFAULT_MAX_DISCHARGE_W = 12000
DEFAULT_WALLBOXES = "garage, carport"
DEFAULT_EV_SOC_SENSOR = "sensor.el6_battery_state_of_charge"
DEFAULT_EV_MAX_SOC_SENSOR = "sensor.el6_maximum_state_of_charge"
DEFAULT_HP_CURVE = "0:2, 5:1"
# Tagesverbrauch ≈ base + max(min_hp, a − b·T)
DEFAULT_HP_MODEL = "35, 54.3, 3.2, 8"

LEVEL_LOW = "low"
LEVEL_NORMAL = "normal"
LEVEL_HIGH = "high"

WALLBOX_MODES = ["aus", "netzladen", "niedrigtarif", "nur_pv", "ueberschuss_niedrigtarif"]
# In diesen Modi lädt die Wallbox mit PV-Überschuss (E3DC-Sonnenmodus)
WALLBOX_SURPLUS_MODES = ("nur_pv", "ueberschuss_niedrigtarif")
WALLBOX_STATES = ["ausgesteckt", "angeschlossen", "laedt"]
EV_TARGET_TYPES = ["ladestand", "energie"]
# Zielladung je Wallbox: key -> (min, max, step, unit)
EV_NUMBERS: dict[str, tuple[float, float, float, str]] = {
    "ev_soc": (10, 100, 5, "%"),
    "ev_kwh": (1, 150, 1, "kWh"),
}

# Einstellbare Werte (Number-Entitäten): key -> (default, min, max, step, unit)
SETTINGS_NUMBERS: dict[str, tuple[float, float, float, float, str | None]] = {
    "safety_factor": (1.5, 1.0, 3.0, 0.05, None),
    "buffer_pct": (10, 0, 50, 1, "%"),
    "min_target_soc": (25, 0, 100, 5, "%"),
    "max_target_soc": (95, 10, 100, 5, "%"),
    "grid_charge_max_w": (8500, 1000, 12000, 100, "W"),
    "grid_charge_min_w": (1500, 500, 6000, 100, "W"),
    "summer_ac_limit_w": (12000, 1000, 30000, 100, "W"),
    "summer_reserve_pct": (5, 0, 30, 1, "%"),
    "summer_morning_start_h": (5, 0, 12, 1, "h"),
    "summer_morning_target_soc": (30, 0, 100, 5, "%"),
    "summer_discharge_w": (3000, 500, 12000, 100, "W"),
    "hp_boost_k": (2, 0, 5, 0.5, "K"),
    "ev_capacity_kwh": (90, 10, 200, 1, "kWh"),
    "battery_loss_pct": (10, 0, 30, 1, "%"),
    "history_days": (14, 3, 60, 1, "d"),
}

# Schalter: key -> default
SETTINGS_SWITCHES: dict[str, bool] = {
    "control_active": True,
    "simulation": True,          # Erst nur rechnen und anzeigen, nichts schalten
    "grid_charging": True,
    "hold_in_low": True,         # Akku im Niedrigtarif nicht entladen
    "pv_p10": True,              # pessimistische Solcast-Prognose verwenden
    "summer_mode": False,        # Morgens Ladesperre, wenn mittags PV über der AC-Grenze erwartet wird
    "summer_active_discharge": False,
    "hp_control": True,
    "hp_sg_on_surplus": True,
    "hp_block_in_high": False,
}

UPDATE_INTERVAL_S = 30
# Durchschnittspreise aus der Recorder-Statistik so oft neu rechnen
PRICE_STATS_INTERVAL_MIN = 15
# Verlauf der Durchschnittspreise: so viele Tage, und Monate/Jahre ab diesem Jahresabstand
PRICE_HISTORY_DAYS = 31
PRICE_HISTORY_YEARS = 2
POWER_MODE_REFRESH_S = 20
WALLBOX_TOGGLE_COOLDOWN_S = 180
# Erst ab dieser erwarteten Abregelungsenergie greift der Sommer-Modus
SUMMER_MIN_CLIP_KWH = 0.5
# Ladegrenze in der Spitze: PV − AC-Grenze + Aufschlag, in Stufen gerundet
SUMMER_CHARGE_MARGIN_W = 500
SUMMER_CHARGE_STEP_W = 500
# In der Spitze frei laden, wenn der SoC so weit unter der Ladegrenze liegt
SUMMER_HYST_PCT = 3
# Zielladung: bis hierhin in den günstigen Zeiten, der Rest kurz vor der Zielzeit
EV_TOPUP_FROM_PCT = 90
# Wallbox-Energie → Fahrzeugakku
EV_EFFICIENCY = 0.9
# Oberhalb EV_TOPUP_FROM_PCT lädt das Auto langsamer
EV_TOPUP_POWER_FACTOR = 0.7
# So viel früher als die Zielzeit soll das Ziel rechnerisch erreicht sein
EV_FINISH_BUFFER_MIN = 15
# Falls Ladestrom oder Phasen der Wallbox nicht lesbar sind
EV_DEFAULT_POWER_KW = 11.0
