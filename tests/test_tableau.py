"""Configurer → tableau de bord « Révisions » : fabriqué avec les joueurs et les bonus / malus, gardé, refait, retiré."""
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

URL = "http://10.0.0.86:8010"
JOUEUR = {"nom": "Lina", "xp_total": 40, "xp_semaine": 40, "niveau": 1, "avatar": "🐣", "gagne_jour": 3, "xp_max_jour": 200,
          "pieces": 7, "dernier": None, "classe": "GS", "test": False, "xp_revisions_jour": 120, "objectif_recre": 100,
          "recre_restante_min": 10, "recre": "ouverte"}
HA = {"enfants": {"lina": JOUEUR, "test": {**JOUEUR, "nom": "Test", "test": True}}, "classement": ["Lina"],
      "podium": [{"nom": "Lina", "avatar": "🐣", "xp_semaine": 40}], "achats_en_attente": [], "nb_achats_en_attente": 0}
COMP = [{"code": "hurle", "nom": "Hurle", "xp": -5}, {"code": "met_table", "nom": "Met la table", "xp": 5}]


def serveur(m, ha=HA, comp=COMP):
    m.clear_requests()
    m.get(URL + "/api/ha", json=ha)
    m.get(URL + "/api/comportements", json=comp)


async def options(hass, entry, action):
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] == "form" and r["step_id"] == "init"
    return await hass.config_entries.options.async_configure(r["flow_id"], {"action": action})


async def test_tableau_de_bord(hass: HomeAssistant, aioclient_mock):
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from custom_components.revisions import tableau
    tableau.DELAI = 0
    assert await async_setup_component(hass, "lovelace", {})
    serveur(aioclient_mock)
    r = await hass.config_entries.flow.async_init("revisions", context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"url": URL, "token": "x"})
    entry = r["result"]
    await hass.async_block_till_done()

    r = await options(hass, entry, "afficher")
    assert r["type"] == "create_entry" and entry.options["tableau"] is True
    assert tableau.URL in hass.data["frontend_panels"]
    config = await hass.data[LOVELACE_DATA].dashboards[tableau.URL].async_load(False)
    sections = config["views"][0]["sections"]
    assert len(sections) == 2   # Lina (le compte de test n'a pas de colonne) + lots et classement
    texte = str(sections[0])
    assert "sensor.revisions_lina_pieces" in texte
    tuiles = [c for c in sections[0]["cards"] if c["type"] == "tile" and c["icon"].startswith("mdi:thumb")]
    assert [t["name"] for t in tuiles] == ["Met la table (+5 XP)", "Hurle (-5 XP)"]   # bonus d'abord, puis malus
    assert tuiles[0]["tap_action"]["target"]["entity_id"] == "button.revisions_lina_met_la_table"
    assert tuiles[0]["tap_action"]["confirmation"]["text"] == "Lina : Met la table (+5 XP) ?"
    assert "sensor.revisions_achats_en_attente" in str(sections[1]) and "button.revisions_lot_le_plus_ancien_donne" in str(sections[1])

    # un nouveau bonus : le tableau garde les modifications faites à la main… jusqu'à « Refaire »
    tableau_ha = hass.data[LOVELACE_DATA].dashboards[tableau.URL]
    await tableau_ha.async_save({"views": [{"title": "Perso"}]})
    serveur(aioclient_mock, comp=COMP + [{"code": "aide", "nom": "Aide les autres", "xp": 5}])
    await entry.runtime_data.async_refresh(); await hass.async_block_till_done()
    assert await tableau.afficher(hass, entry, "Révisions")
    assert (await tableau_ha.async_load(False))["views"][0]["title"] == "Perso"
    r = await options(hass, entry, "refaire")
    config = await hass.data[LOVELACE_DATA].dashboards[tableau.URL].async_load(False)
    assert "Aide les autres (+5 XP)" in str(config)

    # retirer : plus dans la barre latérale, réglage gardé dans les options
    r = await options(hass, entry, "retirer")
    assert entry.options["tableau"] is False and tableau.URL not in hass.data["frontend_panels"]


async def test_modele_a_coller_valide():
    """Le modèle à coller est un YAML valide, sans nom d'entité écrit en dur."""
    import os
    import yaml
    chemin = os.path.join(os.path.dirname(__file__), "..", "custom_components", "revisions", "tableau.yaml")
    with open(chemin, encoding="utf-8") as f:
        texte = f.read()
    config = yaml.safe_load(texte)
    assert config["views"][0]["type"] == "sections"
    assert "sensor.revisions_" not in texte and "integration_entities('revisions')" in texte


def test_traductions_sans_balise():
    """Home Assistant lit les textes comme des messages ICU : un « < » y provoque « Translation error »."""
    import glob
    import os
    for f in glob.glob(os.path.join(os.path.dirname(__file__), "..", "custom_components", "revisions", "**", "*.json"), recursive=True):
        assert "<" not in open(f, encoding="utf-8").read(), f


async def test_tableau_suit_tout_seul(hass: HomeAssistant, aioclient_mock):
    """Nouveau bonus : le tableau se refait tout seul… sauf s'il a été modifié à la main."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from custom_components.revisions import tableau
    tableau.DELAI = 0
    assert await async_setup_component(hass, "lovelace", {})
    serveur(aioclient_mock)
    r = await hass.config_entries.flow.async_init("revisions", context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"url": URL, "token": "x"})
    entry = r["result"]
    await hass.async_block_till_done()
    await options(hass, entry, "afficher")
    tableau_ha = hass.data[LOVELACE_DATA].dashboards[tableau.URL]
    serveur(aioclient_mock, comp=COMP + [{"code": "aide", "nom": "Aide les autres", "xp": 5}])
    await entry.runtime_data.async_refresh(); await hass.async_block_till_done()
    assert "Aide les autres (+5 XP)" in str(await tableau_ha.async_load(False))
    # modifié à la main : un nouveau bonus ne l'écrase pas
    await tableau_ha.async_save({"views": [{"title": "Perso"}]})
    serveur(aioclient_mock, comp=COMP + [{"code": "lit", "nom": "Lit une histoire", "xp": 5}])
    await entry.runtime_data.async_refresh(); await hass.async_block_till_done()
    assert (await tableau_ha.async_load(False))["views"][0]["title"] == "Perso"
