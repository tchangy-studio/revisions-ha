"""Révisions : l'appli de révisions des enfants (tirelire, récré, bonus / malus) dans Home Assistant."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, EVENT_ACHAT

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]
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


class RevisionsCoordinator(DataUpdateCoordinator[dict]):
    """Relit Révisions toutes les minutes ; prévient (événement) quand un enfant achète un lot."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: RevisionsApi) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=INTERVALLE)
        self.api = api
        self._achats_vus: set[int] | None = None

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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RevisionsConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
