"""Tests de l'intégration Révisions avec un faux serveur Révisions."""
import copy
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import async_capture_events, async_fire_time_changed
from homeassistant.util import dt as dt_util
from datetime import timedelta

URL = "http://10.0.0.86:8010"
ENFANT = {"nom": "Raph", "xp_total": 40, "xp_jour": 12, "xp_semaine": 40, "niveau": 1, "avatar": "🐣", "tirelire": 7, "gagne_jour": 3,
          "xp_max_jour": 200, "pieces": 7, "dernier": {"raison": "Met la table", "delta": 5, "ts": "2026-11-10 15:00:00"}, "classe": "CE1",
          "test": False, "xp_revisions_jour": 120, "objectif_recre": 100, "recre_restante_min": 10, "recre": "ouverte"}
HA = {"enfants": {"raph": ENFANT, "papa": {**ENFANT, "nom": "Papa", "test": True}}, "classement": ["Raph"],
      "podium": [{"nom": "Raph", "avatar": "🐣", "xp_semaine": 40}], "achats_en_attente": [], "nb_achats_en_attente": 0}
COMP = [{"code": "met_table", "nom": "Met la table", "xp": 5}, {"code": "hurle", "nom": "Hurle", "xp": -5}]


def serveur(aioclient_mock, ha=HA, comp=COMP):
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL + "/api/ha", json=ha)
    aioclient_mock.get(URL + "/api/comportements", json=comp)


async def installer(hass, aioclient_mock):
    serveur(aioclient_mock)
    r = await hass.config_entries.flow.async_init("revisions", context={"source": config_entries.SOURCE_USER})
    assert r["type"] == "form"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"url": "10.0.0.86:8010/", "token": "jeton-secret"})
    assert r["type"] == "create_entry", r
    assert r["data"]["url"] == URL and r["data"]["token"] == "jeton-secret"
    await hass.async_block_till_done()
    return r["result"]



def appareil(reg, identifiant):
    """Appareil par identifiant, sans dépendre de la version de HA (async_get_device est déprécié depuis 2026.10)."""
    entree = identifiant[1].split("_", 1)[0]   # identifiant = (domaine, "<entry_id>" ou "<entry_id>_<joueur>")
    return next((d for d in dr.async_entries_for_config_entry(reg, entree) if identifiant in d.identifiers), None)

async def test_entites(hass: HomeAssistant, aioclient_mock):
    await installer(hass, aioclient_mock)
    s = hass.states.get("sensor.revisions_raph_pieces")
    assert s.state == "7" and s.attributes["xp_revisions_jour"] == 120 and s.attributes["classe"] == "CE1"
    assert hass.states.get("sensor.revisions_raph_revisions_du_jour").state == "120"
    assert hass.states.get("sensor.revisions_raph_recre").state == "ouverte"
    assert hass.states.get("sensor.revisions_raph_niveau").state == "1"
    assert hass.states.get("sensor.revisions_achats_en_attente").state == "0"
    assert hass.states.get("button.revisions_raph_met_la_table").attributes["sens"] == "bonus"
    assert hass.states.get("button.revisions_raph_hurle").attributes["icon"] == "mdi:thumb-down"
    assert hass.states.get("sensor.revisions_papa_pieces") is None   # compte de test ignoré
    assert hass.states.get("button.revisions_lot_le_plus_ancien_donne").state == "unavailable"
    print(sorted(e.entity_id for e in er.async_get(hass).entities.values()))


async def test_bouton_et_ajout_dynamique(hass: HomeAssistant, aioclient_mock):
    entry = await installer(hass, aioclient_mock)
    serveur(aioclient_mock, comp=COMP + [{"code": "aide_menage", "nom": "Aide au ménage", "xp": 5}])
    aioclient_mock.post(URL + "/api/comportement", json={"delta": 5})
    await hass.services.async_call("button", "press", {"entity_id": "button.revisions_raph_met_la_table"}, blocking=True)
    posts = [c for c in aioclient_mock.mock_calls if c[0] == "POST"]
    assert posts and posts[0][2] == {"enfant": "raph", "code": "met_table"}
    await hass.async_block_till_done()
    assert hass.states.get("button.revisions_raph_aide_au_menage") is not None   # nouveau comportement → nouveau bouton
    # comportement supprimé → indisponible
    serveur(aioclient_mock, comp=[COMP[0]])
    await entry.runtime_data.async_refresh(); await hass.async_block_till_done()
    assert hass.states.get("button.revisions_raph_hurle").state == "unavailable"


async def test_refus_403(hass: HomeAssistant, aioclient_mock):
    await installer(hass, aioclient_mock)
    aioclient_mock.post(URL + "/api/comportement", status=403, json={"detail": "réservé aux parents"})
    with pytest.raises(HomeAssistantError, match="HA_IPS"):
        await hass.services.async_call("button", "press", {"entity_id": "button.revisions_raph_hurle"}, blocking=True)


async def test_achat_evenement_et_lot_donne(hass: HomeAssistant, aioclient_mock):
    entry = await installer(hass, aioclient_mock)
    evts = async_capture_events(hass, "revisions_nouvel_achat")
    ha = copy.deepcopy(HA); ha["achats_en_attente"] = [{"id": 12, "enfant": "raph", "enfant_nom": "Raph", "nom": "Figurine", "ico": "🦖", "prix": 200, "type": "jouet", "ts": "2026-11-10 15:10:00"}]
    ha["nb_achats_en_attente"] = 1
    serveur(aioclient_mock, ha=ha)
    await entry.runtime_data.async_refresh(); await hass.async_block_till_done()
    assert len(evts) == 1 and evts[0].data["nom"] == "Figurine" and evts[0].data["enfant_nom"] == "Raph"
    await entry.runtime_data.async_refresh(); await hass.async_block_till_done()
    assert len(evts) == 1   # pas de doublon
    aioclient_mock.post(URL + "/api/achat/12/statut", json={"ok": True})
    await hass.services.async_call("button", "press", {"entity_id": "button.revisions_lot_le_plus_ancien_donne"}, blocking=True)
    assert any(c[0] == "POST" and str(c[1]).endswith("/api/achat/12/statut") for c in aioclient_mock.mock_calls)


async def test_flux_erreurs(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(URL + "/api/ha", status=404)
    r = await hass.config_entries.flow.async_init("revisions", context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"url": URL, "token": "x"})
    assert r["type"] == "form" and r["errors"]["base"] in ("injoignable", "pas_revisions")


async def test_jeton_envoye_et_erreurs_claires(hass: HomeAssistant, aioclient_mock):
    await installer(hass, aioclient_mock)
    entetes = [c[3] for c in aioclient_mock.mock_calls if str(c[1]).endswith("/api/ha")]
    assert entetes and all(h.get("Authorization") == "Bearer jeton-secret" for h in entetes)
    # à l'installation : jeton faux et IP non autorisée donnent chacun leur message
    for statut, attendu in ((401, "jeton"), (403, "ip")):
        aioclient_mock.clear_requests()
        aioclient_mock.get(f"http://10.0.0.{statut % 250}:8010/api/ha", status=statut, json={"detail": "refus"})
        r = await hass.config_entries.flow.async_init("revisions", context={"source": config_entries.SOURCE_USER})
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {"url": f"http://10.0.0.{statut % 250}:8010", "token": "x"})
        assert r.get("errors") == {"base": attendu}, r


@pytest.mark.parametrize("expected_lingering_tasks", [True])   # la mise à jour différée du tableau peut rester en attente
async def test_jeton_change_redemande(hass: HomeAssistant, aioclient_mock):
    entry = await installer(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL + "/api/ha", status=401, json={"detail": "jeton Home Assistant absent ou incorrect"})
    await entry.runtime_data.async_refresh(); await hass.async_block_till_done()
    flux = [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == "reauth"]
    assert len(flux) == 1
    r = await hass.config_entries.flow.async_configure(flux[0]["flow_id"], {"token": "faux"})
    assert r["errors"] == {"base": "jeton"}
    serveur(aioclient_mock)
    r = await hass.config_entries.flow.async_configure(flux[0]["flow_id"], {"token": "nouveau"})
    assert r["type"] == "abort" and r["reason"] == "reauth_successful" and entry.data["token"] == "nouveau"


async def test_appareils_ranges_sous_revisions(hass: HomeAssistant, aioclient_mock):
    """Chaque enfant est rangé sous l'appareil « Révisions », y compris un joueur ajouté plus tard (sans via_device, déprécié)."""
    from homeassistant.helpers import device_registry as dr
    entry = await installer(hass, aioclient_mock)
    reg = dr.async_get(hass)
    maison = appareil(reg, ("revisions", entry.entry_id))
    raph = appareil(reg, ("revisions", f"{entry.entry_id}_raph"))
    assert maison and raph and raph.via_device_id == maison.id
    serveur(aioclient_mock, ha={**HA, "enfants": {**HA["enfants"], "zoe": {**ENFANT, "nom": "Zoé"}}})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=122))
    await hass.async_block_till_done()
    zoe = appareil(reg, ("revisions", f"{entry.entry_id}_zoe"))
    assert zoe and zoe.via_device_id == maison.id


async def test_supprimer_un_joueur_parti(hass: HomeAssistant, aioclient_mock):
    """L'appareil d'un joueur supprimé dans Révisions peut être retiré de Home Assistant ; pas celui d'un joueur présent."""
    from homeassistant.helpers import device_registry as dr
    from custom_components.revisions import async_remove_config_entry_device
    entry = await installer(hass, aioclient_mock)
    reg = dr.async_get(hass)
    maison = appareil(reg, ("revisions", entry.entry_id))
    raph = appareil(reg, ("revisions", f"{entry.entry_id}_raph"))
    assert not await async_remove_config_entry_device(hass, entry, raph)
    assert not await async_remove_config_entry_device(hass, entry, maison)
    serveur(aioclient_mock, ha={**HA, "enfants": {"papa": HA["enfants"]["papa"]}})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert await async_remove_config_entry_device(hass, entry, raph)
