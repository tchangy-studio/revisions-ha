"""Boutons : un par comportement et par enfant (bonus / malus), 15 minutes de plus, débloquer le profil,
plus « lot le plus ancien donné »."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RevisionsConfigEntry, RevisionsCoordinator
from .entity import RevisionsEntity


async def async_setup_entry(hass: HomeAssistant, entry: RevisionsConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities([LotDonneButton(coordinator)])
    connus: set[tuple[str, str]] = set()

    enfants_vus: set[str] = set()

    @callback
    def ajouter() -> None:   # un comportement ajouté dans Révisions devient un bouton tout seul
        cles = [(e, c["code"]) for e in coordinator.enfants() for c in coordinator.data.get("comportements", [])]
        nouveaux = [k for k in cles if k not in connus]
        connus.update(nouveaux)
        enfants = [e for e in coordinator.enfants() if e not in enfants_vus]
        enfants_vus.update(enfants)
        async_add_entities([ComportementButton(coordinator, e, code) for e, code in nouveaux] + [TempsEnPlusButton(coordinator, e) for e in enfants]
                           + [DebloquerProfilButton(coordinator, e) for e in enfants])

    ajouter()
    entry.async_on_unload(coordinator.async_add_listener(ajouter))


class ComportementButton(RevisionsEntity, ButtonEntity):
    def __init__(self, coordinator: RevisionsCoordinator, enfant: str, code: str) -> None:
        super().__init__(coordinator, enfant, f"comportement_{code}")
        self.code = code
        c = self._comportement or {}
        self._attr_name = c.get("nom", code)

    @property
    def _comportement(self) -> dict | None:
        return next((c for c in (self.coordinator.data or {}).get("comportements", []) if c["code"] == self.code), None)

    @property
    def available(self) -> bool:   # comportement supprimé dans Révisions : le bouton devient indisponible
        return super().available and self._comportement is not None

    @property
    def icon(self) -> str:
        return "mdi:thumb-up" if (self._comportement or {}).get("xp", 0) > 0 else "mdi:thumb-down"

    @property
    def extra_state_attributes(self) -> dict:
        c = self._comportement or {}
        return {"xp": c.get("xp"), "sens": "bonus" if c.get("xp", 0) > 0 else "malus", "code": self.code}

    async def async_press(self) -> None:
        await self.coordinator.api.comportement(self.enfant, self.code)
        await self.coordinator.async_request_refresh()


class TempsEnPlusButton(RevisionsEntity, ButtonEntity):
    """15 minutes de plus pour aujourd'hui (Révisions 0.7+)."""
    _attr_name = "15 minutes de plus"
    _attr_icon = "mdi:timer-plus-outline"

    def __init__(self, coordinator: RevisionsCoordinator, enfant: str) -> None:
        super().__init__(coordinator, enfant, "temps_en_plus")

    @property
    def available(self) -> bool:   # serveur plus ancien (sans temps) ou enfant sans limite
        return super().available and self.infos.get("temps_max_min") is not None

    async def async_press(self) -> None:
        await self.coordinator.api.temps_en_plus(self.enfant, 15)
        await self.coordinator.async_request_refresh()


class DebloquerProfilButton(RevisionsEntity, ButtonEntity):
    """Rouvre le profil bloqué après trop d'erreurs de code secret, sans attendre la fin du délai (Révisions 0.7.7+)."""
    _attr_name = "Débloquer le profil"
    _attr_icon = "mdi:lock-open-variant-outline"

    def __init__(self, coordinator: RevisionsCoordinator, enfant: str) -> None:
        super().__init__(coordinator, enfant, "debloquer_profil")

    @property
    def available(self) -> bool:   # serveur sans code secret (avant 0.7) : rien à débloquer
        return super().available and "profil_bloque" in self.infos

    @property
    def extra_state_attributes(self) -> dict:
        return {"profil_bloque": bool(self.infos.get("profil_bloque")), "blocages_jour": self.infos.get("profil_blocages_jour")}

    async def async_press(self) -> None:
        await self.coordinator.api.debloquer_profil(self.enfant)
        await self.coordinator.async_request_refresh()


class LotDonneButton(RevisionsEntity, ButtonEntity):
    _attr_name = "lot le plus ancien donné"
    _attr_icon = "mdi:gift-open"

    def __init__(self, coordinator: RevisionsCoordinator) -> None:
        super().__init__(coordinator, None, "lot_donne")

    @property
    def available(self) -> bool:
        return super().available and bool((self.coordinator.data or {}).get("achats_en_attente"))

    async def async_press(self) -> None:
        achats = (self.coordinator.data or {}).get("achats_en_attente") or []
        if achats:
            await self.coordinator.api.achat_fait(achats[0]["id"])
            await self.coordinator.async_request_refresh()
