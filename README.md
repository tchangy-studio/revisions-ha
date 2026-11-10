# Révisions pour Home Assistant

Intégration Home Assistant de **Révisions**, l'appli de révisions des enfants (tirelire, récré, bonus / malus).
Elle ne contient que le lien avec Home Assistant : il faut un serveur Révisions (version 0.5.1 ou plus) sur le réseau de la maison.

🚧 Version 0.x : en construction.

## Installation (HACS)

1. HACS → ⋮ → **Dépôts personnalisés** → adresse `https://github.com/tchangy-studio/revisions-ha`, catégorie **Intégration**.
2. Cherche **Révisions** dans HACS → Télécharger, puis redémarre Home Assistant.
3. Paramètres → Appareils et services → Ajouter une intégration → **Révisions** → adresse du serveur, par ex. `http://192.168.1.20:8010`.

Utilise l'adresse **directe** du serveur (IP et port), pas une adresse qui passe par un proxy.
Pour que les boutons de bonus / malus soient acceptés, l'adresse IP de Home Assistant doit être dans `HA_IPS` du fichier `revisions.conf` de Révisions.

## Ce que ça crée

Un appareil par enfant (les comptes de test sont ignorés) :

| Entité | Contenu |
|---|---|
| `sensor.revisions_<prénom>_pieces` | tirelire (pièces), avec en attributs XP, niveau, avatar, classe, récré, dernière action |
| `sensor.revisions_<prénom>_revisions_du_jour` | XP de révisions du jour (maximum et objectif de récré en attributs) |
| `sensor.revisions_<prénom>_recre` | `fermée`, `ouverte` ou `bonus` (minutes restantes en attribut) |
| `sensor.revisions_<prénom>_niveau` | niveau de progression |
| `button.revisions_<prénom>_<comportement>` | un bouton par comportement réglé dans l'espace parents (bonus ou malus) |

Et un appareil **Révisions** :

| Entité | Contenu |
|---|---|
| `sensor.revisions_achats_en_attente` | nombre de lots à préparer, liste détaillée et classement de la semaine en attributs |
| `button.revisions_lot_le_plus_ancien_donne` | marque le plus ancien achat comme donné |

Un enfant ou un comportement ajouté dans Révisions apparaît tout seul dans Home Assistant (en moins d'une minute) ;
un comportement supprimé rend son bouton indisponible.

## Être prévenu quand un enfant achète un lot

L'intégration envoie l'événement `revisions_nouvel_achat` (`enfant_nom`, `nom`, `ico`, `prix`, `id`). Exemple d'automatisation :

```yaml
triggers:
  - trigger: event
    event_type: revisions_nouvel_achat
actions:
  - action: notify.mobile_app_mon_telephone
    data:
      title: "🛍️ Révisions"
      message: "{{ trigger.event.data.enfant_nom }} a acheté {{ trigger.event.data.ico }} {{ trigger.event.data.nom }} : à préparer !"
```

## Tableau de bord

Les boutons s'utilisent comme n'importe quelle entité. Par exemple une tuile verte avec confirmation :

```yaml
type: tile
entity: button.revisions_raph_met_la_table
color: green
tap_action:
  action: perform-action
  perform_action: button.press
  target:
    entity_id: button.revisions_raph_met_la_table
  confirmation:
    text: "Raph : Met la table ?"
```
