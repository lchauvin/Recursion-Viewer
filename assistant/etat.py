"""Etat par coffre : pages epinglees, mode joueurs, historique de conversation.

Range hors du coffre, dans le dossier de donnees de l'utilisateur (DESIGN 6) :
le coffre reste la seule source de verite, et l'outil n'y ecrit pas.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import dossier_donnees

MESSAGES_CONSERVES = 60


@dataclass
class EtatCoffre:
    cle: str
    epingles: list[str] = field(default_factory=list)
    mode_joueurs: bool = False
    conversation: list[dict] = field(default_factory=list)

    def vers_json(self) -> dict:
        return {
            "cle": self.cle,
            "epingles": self.epingles,
            "mode_joueurs": self.mode_joueurs,
            "conversation": self.conversation[-MESSAGES_CONSERVES:],
        }


class Etats:
    """Charge et enregistre l'etat de chaque coffre, un fichier JSON par coffre."""

    def __init__(self, dossier: Path | None = None):
        self.dossier = Path(dossier or dossier_donnees() / "etat")
        self._cache: dict[str, EtatCoffre] = {}
        self._verrou = threading.Lock()

    def _fichier(self, cle: str) -> Path:
        propre = "".join(c if c.isalnum() or c in "-_" else "_" for c in cle) or "coffre"
        return self.dossier / (propre + ".json")

    def pour(self, cle: str) -> EtatCoffre:
        with self._verrou:
            if cle in self._cache:
                return self._cache[cle]
            etat = EtatCoffre(cle=cle)
            fichier = self._fichier(cle)
            if fichier.is_file():
                try:
                    brut = json.loads(fichier.read_text(encoding="utf-8"))
                    etat.epingles = [str(e) for e in brut.get("epingles", [])]
                    etat.mode_joueurs = bool(brut.get("mode_joueurs", False))
                    conv = brut.get("conversation", [])
                    etat.conversation = [m for m in conv if isinstance(m, dict)]
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            self._cache[cle] = etat
            return etat

    def enregistrer(self, etat: EtatCoffre) -> None:
        with self._verrou:
            self._cache[etat.cle] = etat
            try:
                self.dossier.mkdir(parents=True, exist_ok=True)
                fichier = self._fichier(etat.cle)
                temporaire = fichier.with_suffix(".tmp")
                temporaire.write_text(
                    json.dumps(etat.vers_json(), ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
                temporaire.replace(fichier)
            except OSError:
                # L'outil doit continuer a marcher meme sans pouvoir ecrire son etat.
                pass

    # --------------------------------------------------------------- actions

    def basculer_epingle(self, cle: str, chemin: str) -> list[str]:
        etat = self.pour(cle)
        if chemin in etat.epingles:
            etat.epingles = [e for e in etat.epingles if e != chemin]
        else:
            etat.epingles = etat.epingles + [chemin]
        self.enregistrer(etat)
        return etat.epingles

    def definir_mode_joueurs(self, cle: str, actif: bool) -> bool:
        etat = self.pour(cle)
        etat.mode_joueurs = bool(actif)
        self.enregistrer(etat)
        return etat.mode_joueurs

    def ajouter_message(self, cle: str, role: str, contenu: str) -> None:
        etat = self.pour(cle)
        etat.conversation = (
            etat.conversation + [{"role": role, "contenu": contenu, "quand": time.time()}]
        )[-MESSAGES_CONSERVES:]
        self.enregistrer(etat)

    def vider_conversation(self, cle: str) -> None:
        etat = self.pour(cle)
        etat.conversation = []
        self.enregistrer(etat)
