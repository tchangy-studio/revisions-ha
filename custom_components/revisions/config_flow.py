"""Écrans de configuration : adresse du serveur Révisions et jeton (espace parents → onglet Home Assistant)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import callback
from homeassistant.helpers.selector import (SelectSelector, SelectSelectorConfig, TextSelector, TextSelectorConfig,
                                            TextSelectorType)

from . import IpRefusee, JetonRefuse, RevisionsApi, tableau
from .const import DOMAIN

CHAMP_JETON = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _url(brute: str) -> str:
    url = brute.strip().rstrip("/")
    return url if url.startswith(("http://", "https://")) else "http://" + url


class RevisionsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _tester(self, url: str, jeton: str) -> str | None:
        try:
            donnees = await RevisionsApi(async_get_clientsession(self.hass), url, jeton).lire()
        except JetonRefuse:
            return "jeton"
        except IpRefusee:
            return "ip"
        except HomeAssistantError as err:
            return "pas_revisions" if "Révisions :" in str(err) else "injoignable"
        return None if isinstance(donnees, dict) and "enfants" in donnees else "pas_revisions"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        erreurs: dict[str, str] = {}
        if user_input is not None:
            url, jeton = _url(user_input[CONF_URL]), user_input.get(CONF_TOKEN, "").strip()
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_configured()
            if not (erreur := await self._tester(url, jeton)):
                return self.async_create_entry(title="Révisions", data={CONF_URL: url, CONF_TOKEN: jeton})
            erreurs["base"] = erreur
        schema = vol.Schema({vol.Required(CONF_URL, default="http://"): str, vol.Required(CONF_TOKEN): CHAMP_JETON})
        return self.async_show_form(step_id="user", data_schema=schema, errors=erreurs)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Révisions refuse le jeton (nouvelle version qui l'exige, ou jeton changé dans l'espace parents)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entree = self._get_reauth_entry()
        erreurs: dict[str, str] = {}
        if user_input is not None:
            jeton = user_input[CONF_TOKEN].strip()
            if not (erreur := await self._tester(entree.data[CONF_URL], jeton)):
                return self.async_update_reload_and_abort(entree, data_updates={CONF_TOKEN: jeton})
            erreurs["base"] = erreur
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({vol.Required(CONF_TOKEN): CHAMP_JETON}),
                                    errors=erreurs, description_placeholders={"url": entree.data[CONF_URL]})

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entree = self._get_reconfigure_entry()
        erreurs: dict[str, str] = {}
        if user_input is not None:
            url, jeton = _url(user_input[CONF_URL]), user_input.get(CONF_TOKEN, "").strip()
            if not (erreur := await self._tester(url, jeton)):
                return self.async_update_reload_and_abort(entree, data_updates={CONF_URL: url, CONF_TOKEN: jeton})
            erreurs["base"] = erreur
        schema = vol.Schema({vol.Required(CONF_URL, default=entree.data[CONF_URL]): str, vol.Required(CONF_TOKEN): CHAMP_JETON})
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=erreurs)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RevisionsOptionsFlow()


class RevisionsOptionsFlow(OptionsFlow):
    """Configurer → le tableau de bord « Révisions » : l'afficher, le refaire (nouveaux joueurs, bonus ou malus), le retirer."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        actuel = bool(self.config_entry.options.get("tableau"))
        schema = vol.Schema({vol.Required("action", default="refaire" if actuel else "afficher"): SelectSelector(
            SelectSelectorConfig(options=["afficher", "refaire", "retirer"], translation_key="action_tableau"))})
        if user_input is not None:
            if user_input["action"] == "retirer":
                tableau.masquer(self.hass)
                return self.async_create_entry(data={**self.config_entry.options, "tableau": False})
            if not await tableau.afficher(self.hass, self.config_entry, "Révisions", refaire=user_input["action"] == "refaire"):
                return self.async_abort(reason="tableau_impossible")
            return self.async_create_entry(data={**self.config_entry.options, "tableau": True})
        return self.async_show_form(step_id="init", data_schema=schema)
