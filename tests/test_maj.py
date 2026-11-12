"""Mise à jour de Révisions depuis Home Assistant (Révisions 0.7.1+)."""
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

URL = "http://10.0.0.86:8010"
HA = {"enfants": {}, "classement": [], "podium": [], "achats_en_attente": [], "nb_achats_en_attente": 0}
MAJ = {"disponible": True, "actuelle": "0.7.1", "derniere": "0.7.2", "maj": True, "en_cours": False, "erreur": None,
       "nouveautes": [{"version": "0.7.2", "texte": "- Un nouveau jeu."}], "journal": [], "resultat": None, "fin": None}


def serveur(m, maj=MAJ, statut=200):
    m.clear_requests()
    m.get(URL + "/api/ha", json=HA)
    m.get(URL + "/api/comportements", json=[])
    m.get(URL + "/api/parent/maj", json=maj, status=statut)


async def installer(hass, m, **k):
    serveur(m, **k)
    r = await hass.config_entries.flow.async_init("revisions", context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"url": URL, "token": "x"})
    await hass.async_block_till_done()
    return r["result"]


async def test_mise_a_jour_proposee_et_installee(hass: HomeAssistant, aioclient_mock):
    from custom_components.revisions import update
    update.ATTENTE = 0
    entry = await installer(hass, aioclient_mock)
    s = hass.states.get("update.revisions_mise_a_jour")
    assert s.state == "on" and s.attributes["installed_version"] == "0.7.1" and s.attributes["latest_version"] == "0.7.2"
    assert "Un nouveau jeu" in s.attributes["release_summary"]
    serveur(aioclient_mock, maj={**MAJ, "actuelle": "0.7.2", "maj": False, "resultat": {"ok": True, "texte": "Révisions 0.7.2 est installé."}})
    aioclient_mock.post(URL + "/api/parent/maj", json={"ok": True})
    await hass.services.async_call("update", "install", {"entity_id": "update.revisions_mise_a_jour"}, blocking=True)
    assert any(c[0] == "POST" and str(c[1]).endswith("/api/parent/maj") for c in aioclient_mock.mock_calls)
    await entry.runtime_data.async_refresh(); await hass.async_block_till_done()
    assert hass.states.get("update.revisions_mise_a_jour").state == "off"


async def test_echec_signale(hass: HomeAssistant, aioclient_mock):
    from custom_components.revisions import update
    update.ATTENTE = 0
    await installer(hass, aioclient_mock)
    serveur(aioclient_mock, maj={**MAJ, "resultat": {"ok": False, "texte": "La mise à jour vers 0.7.2 n'a pas marché : la version 0.7.1 a été remise."}})
    aioclient_mock.post(URL + "/api/parent/maj", json={"ok": True})
    with pytest.raises(HomeAssistantError, match="a été remise"):
        await hass.services.async_call("update", "install", {"entity_id": "update.revisions_mise_a_jour"}, blocking=True)


async def test_revisions_ancien(hass: HomeAssistant, aioclient_mock):
    await installer(hass, aioclient_mock, maj={"detail": "introuvable"}, statut=404)
    assert hass.states.get("update.revisions_mise_a_jour").state == "unavailable"
