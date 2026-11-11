"""Réglage : temps par jour de chaque enfant (Révisions 0.7+)."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RevisionsConfigEntry, RevisionsCoordinator
from .entity import RevisionsEntity


async def async_setup_entry(hass: HomeAssistant, entry: RevisionsConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    connus: set[str] = set()

    @callback
    def ajouter() -> None:
        nouveaux = [e for e in coordinator.enfants() if e not in connus]
        connus.update(nouveaux)
        async_add_entities([LimiteNumber(coordinator, e) for e in nouveaux])

    ajouter()
    entry.async_on_unload(coordinator.async_add_listener(ajouter))


class LimiteNumber(RevisionsEntity, NumberEntity):
    """Minutes par jour pour cet enfant (0 = sans limite). Sans réglage propre à l'enfant : le réglage général de Révisions."""
    _attr_name = "temps par jour"
    _attr_icon = "mdi:timer-cog-outline"
    _attr_native_unit_of_measurement = "min"
    _attr_native_min_value = 0
    _attr_native_max_value = 240
    _attr_native_step = 5
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: RevisionsCoordinator, enfant: str) -> None:
        super().__init__(coordinator, enfant, "temps_max")

    @property
    def available(self) -> bool:   # serveur plus ancien : pas de temps d'utilisation
        return super().available and "temps" in (self.coordinator.data or {})

    @property
    def native_value(self):
        perso = self.infos.get("limite_perso")
        return perso if perso is not None else ((self.coordinator.data or {}).get("temps") or {}).get("temps_max_minutes")

    @property
    def extra_state_attributes(self) -> dict:
        return {"reglage": "propre à l'enfant" if self.infos.get("limite_perso") is not None else "réglage général"}

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.api.limite(self.enfant, int(value))
        await self.coordinator.async_request_refresh()
