"""Temps d'utilisation (Révisions 0.7+) : capteurs, réglage par enfant, 15 minutes de plus, profil bloqué."""
import copy

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_capture_events

URL = "http://10.0.0.86:8010"
ENFANT = {"nom": "Zoé", "xp_total": 40, "xp_semaine": 40, "niveau": 1, "avatar": "🐣", "gagne_jour": 3, "xp_max_jour": 200, "pieces": 7,
          "dernier": None, "classe": "CE1", "test": False, "xp_revisions_jour": 120, "objectif_recre": 100, "recre_restante_min": 10, "recre": "ouverte",
          "temps_utilise_min": 42, "temps_max_min": 60, "temps_restant_min": 18, "temps_bonus_min": 0, "temps_bloque": False, "temps_raison": None,
          "limite_perso": None, "code_actif": True, "profil_bloque": False, "profil_blocages_jour": 0, "profil_dernier_blocage": None}
HA = {"enfants": {"zoe": ENFANT}, "classement": ["Zoé"], "podium": [], "achats_en_attente": [], "nb_achats_en_attente": 0,
      "temps": {"temps_max_minutes": 60, "plage_debut": "08:00", "plage_fin": "19:30"}}


def serveur(m, ha=HA):
    m.clear_requests()
    m.get(URL + "/api/ha", json=ha)
    m.get(URL + "/api/comportements", json=[])


async def installer(hass, m):
    serveur(m)
    r = await hass.config_entries.flow.async_init("revisions", context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"url": URL, "token": "x"})
    await hass.async_block_till_done()
    return r["result"]


async def test_temps_reglage_et_rab(hass: HomeAssistant, aioclient_mock):
    entry = await installer(hass, aioclient_mock)
    t = hass.states.get("sensor.revisions_zoe_temps_aujourd_hui")
    assert t.state == "42" and t.attributes["maximum"] == 60 and t.attributes["restant"] == 18 and t.attributes["code_secret"] is True
    assert hass.states.get("sensor.revisions_zoe_temps_restant").state == "18"
    assert hass.states.get("sensor.revisions_zoe_pieces").attributes["temps_restant_min"] == 18
    n = hass.states.get("number.revisions_zoe_temps_par_jour")
    assert n.state == "60" and n.attributes["reglage"] == "réglage général"
    aioclient_mock.post(URL + "/api/parent/joueur/zoe/temps_max", json={"ok": True})
    aioclient_mock.post(URL + "/api/parent/temps/zoe/bonus", json={})
    await hass.services.async_call("number", "set_value", {"entity_id": "number.revisions_zoe_temps_par_jour", "value": 45}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": "button.revisions_zoe_15_minutes_de_plus"}, blocking=True)
    posts = [(str(c[1]), c[2]) for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert (URL + "/api/parent/joueur/zoe/temps_max", {"minutes": 45}) in posts
    assert (URL + "/api/parent/temps/zoe/bonus", {"minutes": 15}) in posts


async def test_profil_bloque_evenement(hass: HomeAssistant, aioclient_mock):
    entry = await installer(hass, aioclient_mock)
    evts = async_capture_events(hass, "revisions_profil_bloque")
    ha = copy.deepcopy(HA); ha["enfants"]["zoe"].update(profil_bloque=True, profil_blocages_jour=1, profil_dernier_blocage="2026-11-12T09:30:00")
    serveur(aioclient_mock, ha)
    await entry.runtime_data.async_refresh(); await hass.async_block_till_done()
    assert len(evts) == 1 and evts[0].data["enfant_nom"] == "Zoé"
    await entry.runtime_data.async_refresh(); await hass.async_block_till_done()
    assert len(evts) == 1


async def test_serveur_ancien_sans_temps(hass: HomeAssistant, aioclient_mock):
    """Révisions avant 0.7 : pas de temps, rien ne casse (entités vides ou indisponibles)."""
    vieux = copy.deepcopy(HA); vieux.pop("temps")
    for k in [k for k in ENFANT if k.startswith(("temps", "profil", "code", "limite"))]:
        vieux["enfants"]["zoe"].pop(k)
    serveur(aioclient_mock, vieux)
    r = await hass.config_entries.flow.async_init("revisions", context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"url": URL, "token": "x"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.revisions_zoe_temps_aujourd_hui").state == "unknown"
    assert hass.states.get("number.revisions_zoe_temps_par_jour").state == "unavailable"
    assert hass.states.get("button.revisions_zoe_15_minutes_de_plus").state == "unavailable"
