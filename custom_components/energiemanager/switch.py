"""Schalter für Funktionen."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import SETTINGS_SWITCHES
from .entity import EMEntity

CONFIG_SWITCHES = {"pv_p10", "hp_sg_on_surplus", "hp_block_in_high"}


async def async_setup_entry(hass, entry, async_add_entities):
    coord = entry.runtime_data
    async_add_entities(EMSwitch(coord, key) for key in SETTINGS_SWITCHES)


class EMSwitch(EMEntity, SwitchEntity, RestoreEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        if key in CONFIG_SWITCHES:
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self.coordinator.settings[self._key] = last.state == "on"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.settings[self._key])

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_setting(self._key, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_setting(self._key, False)
        self.async_write_ha_state()
