"""Capteurs : tirelire, révisions du jour, récré et niveau de chaque enfant ; lots à préparer."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RevisionsConfigEntry, RevisionsCoordinator
from .entity import RevisionsEntity

RECRE = {"fermee": "fermée", "ouverte": "ouverte", "bonus": "bonus"}
ATTRIBUTS = ("nom", "classe", "avatar", "niveau", "xp_total", "xp_semaine", "xp_revisions_jour", "xp_max_jour",
             "objectif_recre", "recre", "recre_restante_min", "gagne_jour", "dernier",
             "temps_utilise_min", "temps_max_min", "temps_restant_min", "temps_raison")


async def async_setup_entry(hass: HomeAssistant, entry: RevisionsConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities([AchatsSensor(coordinator)])
    connus: set[str] = set()

    @callback
    def ajouter() -> None:   # un enfant ajouté dans Révisions apparaît tout seul
        nouveaux = [e for e in coordinator.enfants() if e not in connus]
        connus.update(nouveaux)
        async_add_entities([cls(coordinator, e) for e in nouveaux for cls in (PiecesSensor, RevisionsJourSensor, RecreSensor, NiveauSensor, TempsSensor, TempsRestantSensor)])

    ajouter()
    entry.async_on_unload(coordinator.async_add_listener(ajouter))


class PiecesSensor(RevisionsEntity, SensorEntity):
    _attr_name = "pièces"
    _attr_icon = "mdi:hand-coin"
    _attr_native_unit_of_measurement = "pièces"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RevisionsCoordinator, enfant: str) -> None:
        super().__init__(coordinator, enfant, "pieces")

    @property
    def native_value(self):
        return self.infos.get("pieces")

    @property
    def extra_state_attributes(self) -> dict:
        return {k: self.infos.get(k) for k in ATTRIBUTS}


class RevisionsJourSensor(RevisionsEntity, SensorEntity):
    _attr_name = "révisions du jour"
    _attr_icon = "mdi:school"
    _attr_native_unit_of_measurement = "XP"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RevisionsCoordinator, enfant: str) -> None:
        super().__init__(coordinator, enfant, "xp_jour")

    @property
    def native_value(self):
        return self.infos.get("xp_revisions_jour")

    @property
    def extra_state_attributes(self) -> dict:
        return {"maximum": self.infos.get("xp_max_jour"), "objectif_recre": self.infos.get("objectif_recre")}


class RecreSensor(RevisionsEntity, SensorEntity):
    _attr_name = "récré"
    _attr_icon = "mdi:gamepad-variant"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(RECRE.values())

    def __init__(self, coordinator: RevisionsCoordinator, enfant: str) -> None:
        super().__init__(coordinator, enfant, "recre")

    @property
    def native_value(self):
        return RECRE.get(self.infos.get("recre"))

    @property
    def extra_state_attributes(self) -> dict:
        return {"minutes_restantes": self.infos.get("recre_restante_min")}


class NiveauSensor(RevisionsEntity, SensorEntity):
    _attr_name = "niveau"
    _attr_icon = "mdi:star-circle"

    def __init__(self, coordinator: RevisionsCoordinator, enfant: str) -> None:
        super().__init__(coordinator, enfant, "niveau")

    @property
    def native_value(self):
        return self.infos.get("niveau")

    @property
    def extra_state_attributes(self) -> dict:
        return {"avatar": self.infos.get("avatar"), "xp_total": self.infos.get("xp_total"), "classe": self.infos.get("classe")}


class TempsSensor(RevisionsEntity, SensorEntity):
    """Temps passé dans l'appli aujourd'hui (Révisions 0.7+)."""
    _attr_name = "temps aujourd'hui"
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = "min"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: RevisionsCoordinator, enfant: str) -> None:
        super().__init__(coordinator, enfant, "temps")

    @property
    def native_value(self):
        return self.infos.get("temps_utilise_min")

    @property
    def extra_state_attributes(self) -> dict:
        i = self.infos
        return {"maximum": i.get("temps_max_min"), "restant": i.get("temps_restant_min"), "dont_en_plus": i.get("temps_bonus_min"),
                "fini": i.get("temps_bloque"), "raison": {"temps": "temps écoulé", "plage": "hors des heures d'ouverture"}.get(i.get("temps_raison")),
                "code_secret": i.get("code_actif"), "profil_bloque": i.get("profil_bloque"), "profil_blocages_jour": i.get("profil_blocages_jour")}


class TempsRestantSensor(RevisionsEntity, SensorEntity):
    """Minutes qui restent aujourd'hui (vide quand il n'y a pas de limite)."""
    _attr_name = "temps restant"
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator: RevisionsCoordinator, enfant: str) -> None:
        super().__init__(coordinator, enfant, "temps_restant")

    @property
    def native_value(self):
        return self.infos.get("temps_restant_min")


class AchatsSensor(RevisionsEntity, SensorEntity):
    _attr_name = "achats en attente"
    _attr_icon = "mdi:gift"

    def __init__(self, coordinator: RevisionsCoordinator) -> None:
        super().__init__(coordinator, None, "achats")

    @property
    def native_value(self):
        return self.infos.get("nb_achats_en_attente")

    @property
    def extra_state_attributes(self) -> dict:
        return {k: self.infos.get(k) for k in ("achats_en_attente", "classement", "podium")}
