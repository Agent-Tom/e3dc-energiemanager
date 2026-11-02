"""Konstanten für den Energiemanager."""
from __future__ import annotations

DOMAIN = "energiemanager"
PLATFORMS = ["sensor", "switch", "number", "select"]

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

# --- Wallboxen ---
CONF_WALLBOXES = "wallboxes"

# --- Wärmepumpe ---
CONF_SG1 = "sg_ready_1_switch"
CONF_SG2 = "sg_ready_2_switch"
CONF_SG_SURPLUS_SENSOR = "sg_surplus_sensor"
CONF_HP_OFFSET = "hp_offset_number"
CONF_HP_CURVE = "hp_offset_curve"
CONF_HP_MODEL = "hp_consumption_model"

# --- Defaults (aus Thomas' Setup) ---
DEFAULT_TARIFF = "02:00-06:00=low@0.18; 12:00-16:00=low@0.18; 18:00-21:00=high@0.35"
DEFAULT_PRICE_NORMAL = 0.27
DEFAULT_CAPACITY = 32.6
DEFAULT_MAX_CHARGE_W = 12000
DEFAULT_MAX_DISCHARGE_W = 12000
DEFAULT_WALLBOXES = "garage, carport"
DEFAULT_HP_CURVE = "0:2, 5:1"
# Tagesverbrauch ≈ base + max(min_hp, a − b·T)
DEFAULT_HP_MODEL = "35, 54.3, 3.2, 8"

LEVEL_LOW = "low"
LEVEL_NORMAL = "normal"
LEVEL_HIGH = "high"

WALLBOX_MODES = ["aus", "netzladen", "niedrigtarif", "ueberschuss_niedrigtarif"]

# Einstellbare Werte (Number-Entitäten): key -> (default, min, max, step, unit)
SETTINGS_NUMBERS: dict[str, tuple[float, float, float, float, str | None]] = {
    "safety_factor": (1.5, 1.0, 3.0, 0.05, None),
    "buffer_pct": (10, 0, 50, 1, "%"),
    "min_target_soc": (25, 0, 100, 5, "%"),
    "max_target_soc": (95, 10, 100, 5, "%"),
    "grid_charge_max_w": (8500, 1000, 12000, 100, "W"),
    "grid_charge_min_w": (1500, 500, 6000, 100, "W"),
    "summer_pv_threshold_kwh": (40, 0, 150, 1, "kWh"),
    "summer_morning_start_h": (5, 0, 12, 1, "h"),
    "summer_morning_end_h": (11, 6, 15, 1, "h"),
    "summer_morning_target_soc": (30, 0, 100, 5, "%"),
    "summer_discharge_w": (3000, 500, 12000, 100, "W"),
    "hp_boost_k": (2, 0, 5, 0.5, "K"),
    "history_days": (14, 3, 60, 1, "d"),
}

# Schalter: key -> default
SETTINGS_SWITCHES: dict[str, bool] = {
    "control_active": True,
    "simulation": True,          # Erst nur rechnen und anzeigen, nichts schalten
    "grid_charging": True,
    "hold_in_low": True,         # Akku im Niedrigtarif nicht entladen
    "pv_p10": True,              # pessimistische Solcast-Prognose verwenden
    "summer_mode": False,        # Morgens Ladesperre für Platz zur Mittagsspitze
    "summer_active_discharge": False,
    "hp_control": True,
    "hp_sg_on_surplus": True,
    "hp_block_in_high": False,
}

UPDATE_INTERVAL_S = 30
POWER_MODE_REFRESH_S = 20
WALLBOX_TOGGLE_COOLDOWN_S = 180
