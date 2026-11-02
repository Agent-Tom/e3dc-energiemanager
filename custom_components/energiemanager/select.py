"""Wallbox-Modus je Wallbox."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .const import WALLBOX_MODES
from .entity import EMEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = entry.runtime_data
    async_add_entities(WallboxModeSelect(coord, wb) for wb in coord.wallboxes)


class WallboxModeSelect(EMEntity, SelectEntity, RestoreEntity):
    _attr_options = WALLBOX_MODES

    def __init__(self, coordinator, wb: str):
        super().__init__(coordinator, f"wallbox_mode_{wb}")
        self._wb = wb
        self._attr_translation_key = "wallbox_mode"
        self._attr_translation_placeholders = {"wallbox": wb.capitalize()}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in WALLBOX_MODES:
            self.coordinator.wallbox_modes[self._wb] = last.state

    @property
    def current_option(self) -> str:
        return self.coordinator.wallbox_modes.get(self._wb, "aus")

    @property
    def extra_state_attributes(self):
        return {"status": self.coordinator.state.wallbox_status.get(self._wb)}

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_wallbox_mode(self._wb, option)
        self.async_write_ha_state()
