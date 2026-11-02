"""Energiemanager (E3DC) – Tarif-, Akku-, Wallbox- und Wärmepumpensteuerung."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import EnergyCoordinator

type EMConfigEntry = ConfigEntry[EnergyCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EMConfigEntry) -> bool:
    coordinator = EnergyCoordinator(hass, entry)
    entry.runtime_data = coordinator
    # Plattformen zuerst laden, damit gespeicherte Einstellungen (Restore) gesetzt sind
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_config_entry_first_refresh()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EMConfigEntry) -> bool:
    await entry.runtime_data.async_shutdown_control()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: EMConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
