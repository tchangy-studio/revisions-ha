"""Mise à jour de Révisions depuis Home Assistant (Paramètres → Mises à jour), Révisions 0.7.1+.

Révisions a un petit service de mise à jour (git pull, reconstruction, retour arrière si la nouvelle version ne démarre
pas) : cette entité montre la version installée et la dernière, avec les nouveautés, et lance la mise à jour."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RevisionsConfigEntry, RevisionsCoordinator
from .entity import RevisionsEntity

ATTENTE = 5          # secondes entre deux nouvelles pendant la mise à jour
DUREE_MAX = 20 * 60  # une construction Docker peut prendre plusieurs minutes


async def async_setup_entry(hass: HomeAssistant, entry: RevisionsConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([RevisionsMiseAJour(entry.runtime_data)])


def _notes(maj: dict) -> str:
    return "\n\n".join(f"## {n['version']}\n{n['texte']}" for n in maj.get("nouveautes") or [])


class RevisionsMiseAJour(RevisionsEntity, UpdateEntity):
    _attr_name = "mise à jour"
    _attr_title = "Révisions"
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES

    def __init__(self, coordinator: RevisionsCoordinator) -> None:
        super().__init__(coordinator, None, "mise_a_jour")
        self._installe_en_cours = False

    @property
    def _maj(self) -> dict:
        return (self.coordinator.data or {}).get("maj") or {}

    @property
    def available(self) -> bool:   # Révisions trop ancien, ou service de mise à jour pas installé
        return super().available and bool(self._maj.get("disponible"))

    @property
    def installed_version(self) -> str | None:
        return self._maj.get("actuelle")

    @property
    def latest_version(self) -> str | None:
        m = self._maj
        return m.get("derniere") if m.get("maj") and m.get("derniere") else m.get("actuelle")

    @property
    def in_progress(self) -> bool:
        return self._installe_en_cours or bool(self._maj.get("en_cours"))

    @property
    def release_summary(self) -> str | None:
        texte = _notes(self._maj)
        return (texte[:250] + "…") if len(texte) > 251 else (texte or None)

    async def async_release_notes(self) -> str | None:
        return _notes(self._maj) or None

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Lance la mise à jour puis attend la fin (Révisions redémarre au milieu : on patiente)."""
        api = self.coordinator.api
        self._installe_en_cours = True
        self.async_write_ha_state()
        try:
            await api.lancer_maj()
            fin, etat = time.monotonic() + DUREE_MAX, None
            while time.monotonic() < fin:
                await asyncio.sleep(ATTENTE)
                try:
                    etat = await api.maj()
                except HomeAssistantError:   # Révisions redémarre
                    continue
                if not etat.get("en_cours"):
                    break
            resultat = (etat or {}).get("resultat") or {}
            if not resultat.get("ok"):
                raise HomeAssistantError(resultat.get("texte") or "la mise à jour de Révisions n'a pas pu être vérifiée")
        finally:
            self._installe_en_cours = False
            await self.coordinator.async_request_refresh()
