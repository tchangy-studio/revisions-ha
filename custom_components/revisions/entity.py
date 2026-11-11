"""Base commune : un appareil par enfant, plus un appareil « Révisions » pour la boutique."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RevisionsCoordinator
from .const import DOMAIN, FABRICANT


class RevisionsEntity(CoordinatorEntity[RevisionsCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: RevisionsCoordinator, enfant: str | None, cle: str) -> None:
        super().__init__(coordinator)
        self.enfant = enfant
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{enfant or 'maison'}_{cle}"
        if enfant:
            nom = coordinator.enfants().get(enfant, {}).get("nom", enfant)
            self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, f"{entry_id}_{enfant}")}, name=f"Révisions {nom}",
                                                manufacturer=FABRICANT, model="Joueur")
        else:
            self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)}, name="Révisions", manufacturer=FABRICANT,
                                                model="Appli de révisions", configuration_url=coordinator.api.url + "/parents")

    @property
    def infos(self) -> dict:
        return self.coordinator.enfants().get(self.enfant, {}) if self.enfant else (self.coordinator.data or {})

    @property
    def available(self) -> bool:
        return super().available and (self.enfant is None or self.enfant in self.coordinator.enfants())
