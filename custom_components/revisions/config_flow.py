"""Écran de configuration : l'adresse du serveur Révisions."""
from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import RevisionsApi
from .const import DOMAIN


class RevisionsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        erreurs: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                url = "http://" + url
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_configured()
            try:
                donnees = await RevisionsApi(async_get_clientsession(self.hass), url).lire()
                if "enfants" not in donnees:
                    raise ValueError
            except (aiohttp.ClientError, TimeoutError):
                erreurs["base"] = "injoignable"
            except (ValueError, KeyError, aiohttp.ContentTypeError):
                erreurs["base"] = "pas_revisions"
            else:
                return self.async_create_entry(title="Révisions", data={CONF_URL: url})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Required(CONF_URL, default="http://"): str}), errors=erreurs)
