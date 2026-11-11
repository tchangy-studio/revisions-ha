"""Révisions : l'appli de révisions des enfants (tirelire, récré, bonus / malus) dans Home Assistant."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import tableau
from .const import DOMAIN, EVENT_ACHAT, EVENT_PROFIL_BLOQUE, FABRICANT

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.NUMBER]
INTERVALLE = timedelta(seconds=60)


class JetonRefuse(HomeAssistantError):
    """Révisions refuse le jeton (absent, faux, ou changé dans l'espace parents)."""


class IpRefusee(HomeAssistantError):
    """Révisions ne connaît pas l'adresse IP de Home Assistant (HA_IPS)."""


class RevisionsApi:
    """Les quelques adresses de Révisions dont Home Assistant a besoin. Révisions exige l'adresse IP de Home Assistant (HA_IPS)
    et le jeton affiché dans l'espace parents (onglet Home Assistant)."""

    def __init__(self, session: aiohttp.ClientSession, url: str, jeton: str | None = None) -> None:
        self._session = session
        self.url = url.rstrip("/")
        self._entetes = {"Authorization": f"Bearer {jeton}"} if jeton else {}

    async def _appel(self, methode: str, chemin: str, corps: dict | None = None) -> Any:
        try:
            async with self._session.request(methode, self.url + chemin, json=corps, headers=self._entetes,
                                             timeout=aiohttp.ClientTimeout(total=10)) as r:
                donnees = await r.json(content_type=None)
                if r.status == 401:
                    raise JetonRefuse("Révisions refuse le jeton : recopie celui de l'espace parents (onglet Home Assistant).")
                if r.status == 403:
                    raise IpRefusee("Révisions refuse Home Assistant : ajoute son adresse IP dans HA_IPS (revisions.conf), puis redémarre Révisions.")
                if r.status >= 400:
                    raise HomeAssistantError(f"Révisions : {donnees.get('detail', r.reason) if isinstance(donnees, dict) else r.reason}")
                return donnees
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise HomeAssistantError(f"Révisions injoignable : {err}") from err

    async def _get(self, chemin: str) -> Any:
        return await self._appel("GET", chemin)

    async def _post(self, chemin: str, corps: dict) -> Any:
        return await self._appel("POST", chemin, corps)

    async def lire(self) -> dict:
        resume = await self._get("/api/ha")
        comportements = await self._get("/api/comportements")
        return {**resume, "comportements": comportements}

    async def comportement(self, enfant: str, code: str) -> Any:
        return await self._post("/api/comportement", {"enfant": enfant, "code": code})

    async def achat_fait(self, achat_id: int) -> Any:
        return await self._post(f"/api/achat/{int(achat_id)}/statut", {"statut": "fait"})

    async def temps_en_plus(self, enfant: str, minutes: int) -> Any:
        """Du temps en plus pour aujourd'hui (Révisions 0.7+)."""
        return await self._post(f"/api/parent/temps/{enfant}/bonus", {"minutes": int(minutes)})

    async def limite(self, enfant: str, minutes: int | None) -> Any:
        """Temps par jour de cet enfant (minutes, 0 = sans limite ; Révisions 0.7+)."""
        return await self._post(f"/api/parent/joueur/{enfant}/temps_max", {"minutes": minutes})


class RevisionsCoordinator(DataUpdateCoordinator[dict]):
    """Relit Révisions toutes les minutes ; prévient (événements) quand un enfant achète un lot ou bloque un profil."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: RevisionsApi) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=INTERVALLE)
        self.api = api
        self._achats_vus: set[int] | None = None
        self._blocages: dict[str, int] | None = None

    async def _async_update_data(self) -> dict:
        try:
            donnees = await self.api.lire()
        except JetonRefuse as err:
            raise ConfigEntryAuthFailed(str(err)) from err   # Home Assistant redemande le jeton
        except HomeAssistantError as err:
            raise UpdateFailed(str(err)) from err
        achats = donnees.get("achats_en_attente") or []
        ids = {a["id"] for a in achats}
        if self._achats_vus is not None:   # pas au démarrage : seulement les nouveaux achats
            for a in achats:
                if a["id"] not in self._achats_vus:
                    self.hass.bus.async_fire(EVENT_ACHAT, {k: a.get(k) for k in ("id", "enfant", "enfant_nom", "nom", "ico", "prix", "type", "ts")})
        self._achats_vus = ids
        # code secret raté 3 fois : le profil est bloqué quelques minutes (quelqu'un essaie le profil d'un autre ?)
        blocages = {k: int(v.get("profil_blocages_jour") or 0) for k, v in (donnees.get("enfants") or {}).items()}
        if self._blocages is not None:
            for k, n in blocages.items():
                if n > self._blocages.get(k, 0):
                    e = donnees["enfants"][k]
                    self.hass.bus.async_fire(EVENT_PROFIL_BLOQUE, {"enfant": k, "enfant_nom": e.get("nom", k), "blocages_jour": n, "ts": e.get("profil_dernier_blocage")})
        self._blocages = blocages
        return donnees

    def enfants(self) -> dict[str, dict]:
        """Les vrais joueurs (sans les comptes de test)."""
        return {k: v for k, v in (self.data or {}).get("enfants", {}).items() if not v.get("test")}


type RevisionsConfigEntry = ConfigEntry[RevisionsCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: RevisionsConfigEntry) -> bool:
    api = RevisionsApi(async_get_clientsession(hass), entry.data[CONF_URL], entry.data.get(CONF_TOKEN))
    coordinator = RevisionsCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    registre = dr.async_get(hass)
    maison = registre.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}, name="Révisions",
                                          manufacturer=FABRICANT, model="Appli de révisions", configuration_url=api.url + "/parents")

    @callback
    def relier() -> None:
        """Range l'appareil de chaque enfant sous l'appareil « Révisions » (via_device_id, à la place de l'ancien via_device)."""
        for appareil in dr.async_entries_for_config_entry(registre, entry.entry_id):
            if appareil.id != maison.id and appareil.via_device_id != maison.id:
                registre.async_update_device(appareil.id, via_device_id=maison.id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    relier()
    entry.async_on_unload(coordinator.async_add_listener(relier))   # joueur ajouté plus tard
    if entry.options.get("tableau"):   # tableau de bord « Révisions » demandé dans Configurer
        await tableau.afficher(hass, entry, "Révisions")
    vu: dict[str, Any] = {}

    @callback
    def suivre_tableau() -> None:
        """Joueur, bonus / malus ou temps qui change (et au démarrage, après une mise à jour) : le tableau suit."""
        k = tableau.cle(coordinator)
        if vu.get("cle") != k:
            vu["cle"] = k
            entry.async_create_background_task(hass, tableau.mettre_a_jour(hass, entry), "revisions_tableau")

    suivre_tableau()
    entry.async_on_unload(coordinator.async_add_listener(suivre_tableau))
    return True


async def async_remove_config_entry_device(hass: HomeAssistant, entry: RevisionsConfigEntry, appareil: dr.DeviceEntry) -> bool:
    """Supprimer l'appareil d'un joueur qui n'existe plus dans Révisions (Paramètres → Appareils → ⋮ → Supprimer).
    Un joueur encore présent, ou l'appareil « Révisions » lui-même, ne peut pas être supprimé."""
    ids = {i[1] for i in appareil.identifiers if i[0] == DOMAIN}
    encore_la = {entry.entry_id} | {f"{entry.entry_id}_{k}" for k in entry.runtime_data.enfants()}
    return not ids & encore_la


async def async_unload_entry(hass: HomeAssistant, entry: RevisionsConfigEntry) -> bool:
    if entry.options.get("tableau"):
        tableau.masquer(hass)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
