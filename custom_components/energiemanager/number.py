"""Einstellbare Werte."""
from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import EntityCategory

from .const import SETTINGS_NUMBERS
from .entity import EMEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coord = entry.runtime_data
    async_add_entities(EMNumber(coord, key) for key in SETTINGS_NUMBERS)


class EMNumber(EMEntity, RestoreNumber):
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        _default, mn, mx, step, unit = SETTINGS_NUMBERS[key]
        self._attr_native_min_value = mn
        self._attr_native_max_value = mx
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self.coordinator.settings[self._key] = last.native_value

    @property
    def native_value(self) -> float:
        return float(self.coordinator.settings[self._key])

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_setting(self._key, value)
        self.async_write_ha_state()
