"""Tableau de bord « Révisions » fourni par l'intégration (Configurer → Tableau de bord).

Une colonne par joueur (révisions du jour, récré, tirelire, dernier événement, boutons bonus / malus), plus les lots à
préparer et le classement de la semaine. Il est fabriqué à partir des joueurs et des bonus / malus du moment :
il se met à jour tout seul quand ils changent (ou après une mise à jour de l'intégration), tant qu'il n'a pas été
modifié à la main ; sinon « Refaire » le remplace.

Home Assistant n'a pas d'API publique pour qu'une intégration crée un tableau de bord : on fait comme le module lovelace
pour un tableau de bord créé à la main (configuration enregistrée par Home Assistant + panneau dans la barre latérale).
Le tableau reste modifiable dans l'interface. Si un jour ça ne marche plus, le modèle à coller (tableau.yaml) reste là.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
URL = "tableau-revisions"
IDENTIFIANT = "revisions_tableau"
ICONE = "mdi:school"
DELAI = 3   # secondes avant de refaire le tableau (les nouvelles entités doivent être enregistrées)

CARTE_JOUEUR = """{% set s = '__CAPTEUR__' %}{% if has_value(s) %}{% set x = state_attr(s, 'xp_revisions_jour') | int(0) %}\
{% set mx = state_attr(s, 'xp_max_jour') | int(200) %}{% set n = [10, (10 * x / mx) | int] | min if mx else 0 %}\
{% set r = state_attr(s, 'recre') %}{% set d = state_attr(s, 'dernier') %}
## {{ state_attr(s, 'avatar') }} {{ state_attr(s, 'nom') }} · niveau {{ state_attr(s, 'niveau') }}
**Révisions du jour** : {{ x }} / {{ mx }} XP
{{ '🟩' * n }}{{ '⬜' * (10 - n) }}

🎮 **Récré** : {% if r == 'fermee' %}encore {{ state_attr(s, 'objectif_recre') | int(0) - x }} XP\
{% elif state_attr(s, 'recre_restante_min') | int(0) <= 0 %}finie pour aujourd'hui{% else %}\
{{ 'ouverte + bonus 🎉' if r == 'bonus' else 'ouverte' }} · {{ state_attr(s, 'recre_restante_min') }} min restantes{% endif %}
🐷 **Tirelire** : {{ states(s) }} pièces (+{{ state_attr(s, 'gagne_jour') }} aujourd'hui)
{% set tr = state_attr(s, 'temps_restant_min') %}{% if state_attr(s, 'temps_utilise_min') is not none %}⏱️ **Temps** : \
{% if state_attr(s, 'temps_raison') == 'plage' %}hors des heures d'ouverture{% elif tr is none %}{{ state_attr(s, 'temps_utilise_min') }} min, sans limite\
{% else %}{{ state_attr(s, 'temps_utilise_min') }} / {{ state_attr(s, 'temps_max_min') }} min{{ ' · fini pour aujourd\'hui' if tr == 0 else '' }}{% endif %}
{% endif %}{% if d %}🕑 {{ d.raison }} ({{ '+' if d.delta > 0 else '' }}{{ d.delta }} XP){% endif %}
{% else %}Révisions est injoignable.{% endif %}
"""
LOTS = """{% set l = state_attr('__CAPTEUR__', 'achats_en_attente') or [] %}{% for a in l %}\
- {{ a.ico }} **{{ a.nom }}** pour {{ a.enfant_nom }} · {{ a.prix }} pièces · {{ a.ts[8:10] }}/{{ a.ts[5:7] }}
{% else %}Rien à préparer 🎉{% endfor %}
"""
CLASSEMENT = """{% for p in state_attr('__CAPTEUR__', 'podium') or [] %}\
{{ ['🥇', '🥈', '🥉'][loop.index0] if loop.index0 < 3 else '▫️' }} {{ p.avatar }} {{ p.nom }} : {{ p.xp_semaine }} XP
{% endfor %}
"""


def _empreinte(config: Any) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _memoire(hass: HomeAssistant) -> Store:
    """Empreinte du dernier tableau fabriqué : s'il a changé depuis, c'est qu'il a été modifié à la main."""
    return Store(hass, 1, f"{DOMAIN}.tableau")


def cle(coordinator) -> tuple:
    """Ce qui change le tableau : les joueurs, les bonus / malus, et le temps d'utilisation (Révisions 0.7+)."""
    donnees = coordinator.data or {}
    return (tuple(sorted((k, v.get("nom"), v.get("temps_max_min") is not None) for k, v in coordinator.enfants().items())),
            tuple((c.get("code"), c.get("nom"), c.get("xp")) for c in donnees.get("comportements", [])), "temps" in donnees)


def _appuyer(bouton: str, question: str) -> dict[str, Any]:
    return {"action": "perform-action", "perform_action": "button.press", "target": {"entity_id": bouton},
            "confirmation": {"text": question}}


def generer(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Le tableau pour les joueurs et les bonus / malus du moment (entités retrouvées dans le registre, même renommées)."""
    registre, coordinator, eid = er.async_get(hass), entry.runtime_data, entry.entry_id
    entite = lambda plateforme, cle: registre.async_get_entity_id(plateforme, DOMAIN, f"{eid}_{cle}")   # noqa: E731
    comportements = sorted((coordinator.data or {}).get("comportements", []), key=lambda c: -c.get("xp", 0))
    sections: list[dict[str, Any]] = []
    for code, joueur in sorted(coordinator.enfants().items(), key=lambda kv: kv[1].get("nom", kv[0]).lower()):
        capteur = entite("sensor", f"{code}_pieces")
        if not capteur:
            continue
        nom = joueur.get("nom", code)
        cartes: list[dict[str, Any]] = [{"type": "markdown", "content": CARTE_JOUEUR.replace("__CAPTEUR__", capteur)}]
        plus = entite("button", f"{code}_temps_en_plus")
        if plus:   # 15 minutes de plus, seulement quand l'enfant a une limite
            cartes.append({"type": "tile", "entity": plus, "name": "15 minutes de plus", "icon": "mdi:timer-plus-outline", "color": "blue",
                           "hide_state": True, "tap_action": _appuyer(plus, f"15 minutes de plus pour {nom} aujourd'hui ?"),
                           "icon_tap_action": _appuyer(plus, f"15 minutes de plus pour {nom} aujourd'hui ?"),
                           "visibility": [{"condition": "state", "entity": plus, "state_not": "unavailable"}]})
        for titre, bonus in (("👍 Bonus", True), ("👎 Malus", False)):
            boutons = [(c, entite("button", f"{code}_comportement_{c['code']}")) for c in comportements if (c.get("xp", 0) > 0) == bonus]
            boutons = [(c, b) for c, b in boutons if b]
            if boutons:
                cartes.append({"type": "heading", "heading": titre, "heading_style": "subtitle"})
            for c, bouton in boutons:
                libelle = f"{c['nom']} ({'+' if c.get('xp', 0) > 0 else ''}{c.get('xp', 0)} XP)"
                action = _appuyer(bouton, f"{nom} : {libelle} ?")
                cartes.append({"type": "tile", "entity": bouton, "name": libelle, "icon": "mdi:thumb-up" if bonus else "mdi:thumb-down",
                               "color": "green" if bonus else "red", "hide_state": True, "tap_action": action, "icon_tap_action": action})
        sections.append({"type": "grid", "cards": cartes})
    achats, lot = entite("sensor", "maison_achats"), entite("button", "maison_lot_donne")
    if achats:
        cartes = [{"type": "heading", "heading": "Lots à préparer", "icon": "mdi:gift"},
                  {"type": "markdown", "content": LOTS.replace("__CAPTEUR__", achats)}]
        if lot:
            cartes.append({"type": "button", "icon": "mdi:gift-open", "name": "Le plus ancien est donné", "show_state": False,
                           "tap_action": _appuyer(lot, "Marquer le plus ancien lot comme donné ?"),
                           "visibility": [{"condition": "numeric_state", "entity": achats, "above": 0}]})
        cartes += [{"type": "heading", "heading": "Classement de la semaine", "icon": "mdi:podium"},
                   {"type": "markdown", "content": CLASSEMENT.replace("__CAPTEUR__", achats)}]
        sections.append({"type": "grid", "cards": cartes})
    return {"views": [{"title": "Révisions", "path": "revisions", "icon": ICONE, "type": "sections", "max_columns": 4,
                       "sections": sections}]}


async def afficher(hass: HomeAssistant, entry: ConfigEntry, titre: str, refaire: bool = False) -> bool:
    """Met le tableau dans la barre latérale ; le fabrique s'il n'existe pas encore, ou si on le refait.
    Rend False si Home Assistant ne le permet pas (version trop différente) : le modèle à coller reste la solution."""
    try:
        from homeassistant.components import frontend
        from homeassistant.components.lovelace.const import LOVELACE_DATA
        from homeassistant.components.lovelace.dashboard import LovelaceStorage
        from homeassistant.exceptions import HomeAssistantError

        donnees = hass.data.get(LOVELACE_DATA)
        if donnees is None:
            return False
        tableau = donnees.dashboards.get(URL)
        if tableau is None:
            tableau = LovelaceStorage(hass, {"id": IDENTIFIANT, "url_path": URL, "title": titre, "icon": ICONE,
                                             "show_in_sidebar": True, "require_admin": False, "mode": "storage"})
            donnees.dashboards[URL] = tableau
        elif not isinstance(tableau, LovelaceStorage):   # un autre tableau de bord a déjà cette adresse : on n'y touche pas
            _LOGGER.warning("Le tableau de bord %s existe déjà et n'est pas celui de Révisions", URL)
            return False
        try:
            existant = await tableau.async_load(False)
        except HomeAssistantError:   # pas encore de configuration enregistrée
            existant = None
        if refaire or not existant:
            nouveau = generer(hass, entry)
            await tableau.async_save(nouveau)
            await _memoire(hass).async_save({"empreinte": _empreinte(nouveau)})
        reglages = {"sidebar_title": titre, "sidebar_icon": ICONE, "frontend_url_path": URL, "config": {"mode": "storage"},
                    "require_admin": False}
        try:
            frontend.async_register_built_in_panel(hass, "lovelace", **reglages)
        except ValueError:   # déjà dans la barre latérale
            frontend.async_register_built_in_panel(hass, "lovelace", **reglages, update=True)
        return True
    except Exception:  # noqa: BLE001 — jamais bloquant pour le reste de l'intégration
        _LOGGER.exception("Impossible de créer le tableau de bord Révisions")
        return False


async def mettre_a_jour(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Refait le tableau quand les joueurs ou les bonus / malus ont changé, sauf s'il a été modifié à la main.
    Rend « fait », « inchange », « modifie_a_la_main » ou « absent »."""
    await asyncio.sleep(DELAI)
    if not entry.options.get("tableau"):
        return "absent"
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA
        from homeassistant.components.lovelace.dashboard import LovelaceStorage
        from homeassistant.exceptions import HomeAssistantError

        donnees = hass.data.get(LOVELACE_DATA)
        tableau = donnees.dashboards.get(URL) if donnees is not None else None
        if not isinstance(tableau, LovelaceStorage):
            return "absent"
        try:
            existant = await tableau.async_load(False)
        except HomeAssistantError:
            existant = None
        memoire = _memoire(hass)
        connu = (await memoire.async_load() or {}).get("empreinte")
        nouveau = generer(hass, entry)
        if existant == nouveau:
            if connu != _empreinte(nouveau):
                await memoire.async_save({"empreinte": _empreinte(nouveau)})
            return "inchange"
        if existant and connu and connu != _empreinte(existant):   # modifié à la main : on n'y touche pas (Configurer → Refaire)
            return "modifie_a_la_main"
        await tableau.async_save(nouveau)
        await memoire.async_save({"empreinte": _empreinte(nouveau)})
        _LOGGER.info("Tableau de bord Révisions mis à jour (joueurs ou bonus / malus changés)")
        return "fait"
    except Exception:  # noqa: BLE001 — jamais bloquant
        _LOGGER.exception("Impossible de mettre à jour le tableau de bord Révisions")
        return "absent"


def masquer(hass: HomeAssistant) -> None:
    """Retire le tableau de la barre latérale ; sa configuration est gardée (il revient tel quel si on le réaffiche)."""
    try:
        from homeassistant.components import frontend
        from homeassistant.components.lovelace.const import LOVELACE_DATA

        frontend.async_remove_panel(hass, URL, warn_if_unknown=False)
        donnees = hass.data.get(LOVELACE_DATA)
        if donnees is not None:
            donnees.dashboards.pop(URL, None)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Impossible de retirer le tableau de bord Révisions")
