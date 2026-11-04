"""Zielzeit der Zielladung je Wallbox."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import EMEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = entry.runtime_data
    async_add_entities(EvTime(coord, wb) for wb in coord.wallboxes)


class EvTime(EMEntity, TimeEntity, RestoreEntity):
    def __init__(self, coordinator, wb: str):
        super().__init__(coordinator, f"ev_time_{wb}")
        self._wb = wb
        self._attr_translation_key = "ev_time"
        self._attr_translation_placeholders = {"wallbox": wb.capitalize()}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            try:
                self.coordinator.ev[self._wb]["ev_time"] = time.fromisoformat(last.state)
            except ValueError:
                pass

    @property
    def native_value(self) -> time:
        return self.coordinator.ev[self._wb]["ev_time"]

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_ev(self._wb, "ev_time", value)
        self.async_write_ha_state()
