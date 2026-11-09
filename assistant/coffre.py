"""Lecture du coffre : index, arborescence, recherche, resolution des liens.

Le coffre est un parametre (DESIGN 4) : ce module ne connait aucun nom de
dossier, aucun type de page, aucune particularite de Recursion. Il lit ce qu'il
trouve et se passe du reste.

Lecture a chaud : l'index est reconstruit des qu'un fichier a change de date de
modification. Pas de cache a invalider, pas de redemarrage.
"""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import rendu

EXTENSION = ".md"
IGNORES = {".git", ".obsidian", ".trash", "node_modules", ".stfolder", "__pycache__"}


def variantes(terme: str) -> list[str]:
    """Le terme, et son singulier ou son pluriel simple.

    Sans cela, chercher « machines » ne trouve pas la page « Le Lien (humain
    et machine) », qui parle pourtant de cela a chaque ligne. On ne va pas
    plus loin : un vrai lemmatiseur serait disproportionne ici.
    """
    formes = [terme]
    if len(terme) > 3 and terme[-1] in "sx":
        formes.append(terme[:-1])
    else:
        formes.append(terme + "s")
    return formes


def plier(texte: str) -> str:
    """Minuscules, sans accents : pour chercher et comparer des noms de page."""
    decompose = unicodedata.normalize("NFD", texte)
    sans_accent = "".join(c for c in decompose if not unicodedata.combining(c))
    return sans_accent.lower().strip()


@dataclass
class Page:
    chemin: str  # relatif au coffre, separateurs "/", sans extension
    fichier: Path
    nom: str  # nom du fichier sans extension
    titre: str
    meta: dict = field(default_factory=dict)
    corps: str = ""
    mtime: float = 0.0

    @property
    def alias(self) -> list[str]:
        brut = self.meta.get("aliases") or self.meta.get("alias") or []
        if isinstance(brut, str):
            return [brut]
        return [str(a) for a in brut]

    @property
    def type(self) -> str:
        return str(self.meta.get("type") or "")

    @property
    def statut(self) -> str:
        return str(self.meta.get("statut") or "")

    @property
    def visibilite(self) -> str:
        # Sans metadonnee, une page est traitee comme visible par le MJ (DESIGN 6).
        return str(self.meta.get("visibilite") or "mj")

    @property
    def reserve_mj(self) -> bool:
        return plier(self.visibilite) != "joueurs"

    @property
    def dossier(self) -> str:
        return self.chemin.rsplit("/", 1)[0] if "/" in self.chemin else ""

    def resume(self) -> dict:
        return {
            "chemin": self.chemin,
            "nom": self.nom,
            "titre": self.titre,
            "type": self.type,
            "statut": self.statut,
            "visibilite": self.visibilite,
            "alias": self.alias,
            "reserve_mj": self.reserve_mj,
        }


class CoffreIntrouvable(Exception):
    pass


class HorsCoffre(Exception):
    """Un chemin demande sort du coffre : jamais servi."""


class Index:
    """Index en memoire des pages d'un coffre, reconstruit a la demande."""

    def __init__(self, racine: Path):
        self.racine = Path(racine)
        self.pages: dict[str, Page] = {}
        self._par_nom: dict[str, list[Page]] = {}
        self._signature: tuple | None = None
        self._verrou = threading.Lock()

    # -------------------------------------------------------------- lecture

    def rafraichir(self, force: bool = False) -> None:
        if not self.racine.is_dir():
            raise CoffreIntrouvable(str(self.racine))
        with self._verrou:
            fichiers = sorted(self._parcourir())
            signature = tuple((str(f), f.stat().st_mtime_ns) for f in fichiers)
            if not force and signature == self._signature:
                return
            pages: dict[str, Page] = {}
            for fichier in fichiers:
                page = self._lire(fichier, reutiliser=self.pages)
                if page is not None:
                    pages[page.chemin] = page
            self.pages = pages
            self._signature = signature
            self._reconstruire_noms()

    def _parcourir(self):
        for dossier, sous_dossiers, fichiers in os.walk(self.racine):
            sous_dossiers[:] = sorted(
                d for d in sous_dossiers if d not in IGNORES and not d.startswith(".")
            )
            for nom in sorted(fichiers):
                if nom.lower().endswith(EXTENSION):
                    yield Path(dossier) / nom

    def _lire(self, fichier: Path, reutiliser: dict[str, Page]) -> Page | None:
        try:
            relatif = fichier.relative_to(self.racine)
        except ValueError:
            return None
        chemin = relatif.as_posix()
        if chemin.lower().endswith(EXTENSION):
            chemin = chemin[: -len(EXTENSION)]
        try:
            mtime = fichier.stat().st_mtime
        except OSError:
            return None
        ancienne = reutiliser.get(chemin)
        if ancienne is not None and ancienne.mtime == mtime:
            return ancienne
        try:
            texte = fichier.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            try:
                texte = fichier.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        meta, corps = rendu.separer_entete(texte)
        nom = fichier.stem
        return Page(
            chemin=chemin,
            fichier=fichier,
            nom=nom,
            titre=_titre(corps, meta, nom),
            meta=meta,
            corps=corps,
            mtime=mtime,
        )

    def _reconstruire_noms(self) -> None:
        table: dict[str, list[Page]] = {}
        for page in self.pages.values():
            cles = {plier(page.nom), plier(page.titre), plier(page.chemin)}
            cles.update(plier(a) for a in page.alias)
            for cle in cles:
                if cle:
                    table.setdefault(cle, []).append(page)
        self._par_nom = table

    # ------------------------------------------------------------ recherche

    def page(self, chemin: str) -> Page | None:
        self.rafraichir()
        chemin = chemin.strip().strip("/")
        if chemin.lower().endswith(EXTENSION):
            chemin = chemin[: -len(EXTENSION)]
        direct = self.pages.get(chemin)
        if direct is not None:
            return direct
        # Tolerance : casse et accents.
        cible = plier(chemin)
        for page in self.pages.values():
            if plier(page.chemin) == cible:
                return page
        return self.resoudre(chemin)

    def resoudre(self, nom: str) -> Page | None:
        """Resout un `[[nom]]` vers une page : nom de fichier, titre, alias, chemin."""
        self.rafraichir()
        candidats = self._par_nom.get(plier(nom.strip()))
        if not candidats:
            return None
        # En cas d'ambiguite, la page la plus haute dans l'arborescence gagne.
        return sorted(candidats, key=lambda p: (p.chemin.count("/"), p.chemin))[0]

    def accueil(self) -> Page | None:
        """Page d'accueil : la premiere du coffre par ordre alphabetique (DESIGN 6)."""
        self.rafraichir()
        if not self.pages:
            return None
        racine = [p for p in self.pages.values() if not p.dossier]
        choix = racine or list(self.pages.values())
        return sorted(choix, key=lambda p: plier(p.chemin))[0]

    def instructions(self) -> str | None:
        """CLAUDE.md a la racine du coffre, s'il existe."""
        for nom in ("CLAUDE.md", "claude.md", "AGENTS.md"):
            fichier = self.racine / nom
            if fichier.is_file():
                try:
                    return fichier.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return None
        return None

    def arbre(self, mode_joueurs: bool = False) -> dict:
        """L'arborescence reelle des dossiers, telle quelle."""
        self.rafraichir()
        racine = {"nom": "", "chemin": "", "dossiers": {}, "pages": []}
        for page in sorted(self.pages.values(), key=lambda p: plier(p.chemin)):
            if mode_joueurs and page.reserve_mj:
                continue
            noeud = racine
            parties = page.chemin.split("/")[:-1]
            empile = []
            for partie in parties:
                empile.append(partie)
                noeud = noeud["dossiers"].setdefault(
                    partie,
                    {"nom": partie, "chemin": "/".join(empile), "dossiers": {}, "pages": []},
                )
            noeud["pages"].append(page.resume())
        return _aplatir(racine)

    def chercher(
        self,
        requete: str,
        type_: str = "",
        visibilite: str = "",
        mode_joueurs: bool = False,
        limite: int = 80,
        tous_les_termes: bool = True,
    ) -> list[dict]:
        """Recherche plein texte, sans accents ni casse (DESIGN 8).

        `tous_les_termes` a faux garde les pages qui ne contiennent qu'une
        partie des termes : utile pour deviner le sujet d'une question posee
        en langage courant, pas pour la barre de recherche.
        """
        self.rafraichir()
        termes = [plier(t) for t in requete.split() if t.strip()]
        resultats: list[dict] = []

        for page in self.pages.values():
            if mode_joueurs and page.reserve_mj:
                continue
            if type_ and plier(page.type) != plier(type_):
                continue
            if visibilite and plier(page.visibilite) != plier(visibilite):
                continue

            if not termes:
                resultats.append({**page.resume(), "score": 0, "extraits": []})
                continue

            titre_plie = plier(page.titre) + " " + plier(page.nom)
            alias_plie = " ".join(plier(a) for a in page.alias)
            corps = page.corps
            if mode_joueurs:
                corps = rendu.retirer_secrets(corps)
            corps_plie = plier(corps)

            chemin_plie = plier(page.chemin)
            score = 0
            manque = False
            for terme in termes:
                poids = 0
                # Le singulier et le pluriel comptent pour le meme terme ; on
                # retient la meilleure correspondance.
                for forme in variantes(terme):
                    if forme in titre_plie:
                        poids = max(poids, 100)
                    elif forme in alias_plie:
                        poids = max(poids, 60)
                    elif forme in chemin_plie:
                        poids = max(poids, 30)
                    elif forme in corps_plie:
                        # Une page qui parle vraiment du sujet le repete : sans
                        # cela, une simple mention vaut autant qu'un chapitre.
                        poids = max(
                            poids, 10 + min(corps_plie.count(forme) - 1, 15) * 2
                        )
                if poids == 0:
                    manque = True
                    if tous_les_termes:
                        break
                    continue
                score += poids
            if tous_les_termes and manque:
                continue
            if score == 0:
                continue

            resultats.append(
                {
                    **page.resume(),
                    "score": score,
                    "extraits": _extraits(corps, termes),
                }
            )

        resultats.sort(key=lambda r: (-r["score"], plier(r["chemin"])))
        return resultats[:limite]

    # --------------------------------------------------------------- divers

    def types(self) -> list[str]:
        self.rafraichir()
        trouves = {p.type for p in self.pages.values() if p.type}
        return sorted(trouves, key=plier)

    def liste_pour_modele(self, mode_joueurs: bool = False) -> str:
        """L'index envoye au modele : court, et suffisant pour savoir ce qui existe."""
        self.rafraichir()
        lignes = []
        for page in sorted(self.pages.values(), key=lambda p: plier(p.chemin)):
            if mode_joueurs and page.reserve_mj:
                continue
            details = [page.chemin]
            if page.titre and plier(page.titre) != plier(page.nom):
                details.append("titre : " + page.titre)
            if page.type:
                details.append("type : " + page.type)
            if page.visibilite:
                details.append("visibilite : " + page.visibilite)
            if page.alias:
                details.append("alias : " + ", ".join(page.alias))
            lignes.append("- " + " | ".join(details))
        return "\n".join(lignes)

    def fichier_sur(self, chemin_relatif: str) -> Path:
        """Resout un chemin relatif en refusant toute sortie du coffre."""
        cible = (self.racine / chemin_relatif).resolve()
        racine = self.racine.resolve()
        if cible != racine and racine not in cible.parents:
            raise HorsCoffre(chemin_relatif)
        return cible


def _titre(corps: str, meta: dict, repli: str) -> str:
    if meta.get("titre"):
        return str(meta["titre"])
    for ligne in corps.split("\n", 40)[:40]:
        trouve = re.match(r"^#\s+(.+?)\s*$", ligne)
        if trouve:
            return trouve.group(1).strip()
    return repli


def _aplatir(noeud: dict) -> dict:
    return {
        "nom": noeud["nom"],
        "chemin": noeud["chemin"],
        "dossiers": [
            _aplatir(sous) for sous in sorted(noeud["dossiers"].values(), key=lambda d: plier(d["nom"]))
        ],
        "pages": noeud["pages"],
    }


def _extraits(corps: str, termes: list[str], maximum: int = 3) -> list[dict]:
    """Les lignes qui contiennent un terme, avec leur numero."""
    sortie: list[dict] = []
    for numero, ligne in enumerate(corps.split("\n"), start=1):
        if len(sortie) >= maximum:
            break
        nue = ligne.strip()
        if not nue:
            continue
        pliee = plier(nue)
        if any(terme in pliee for terme in termes):
            sortie.append({"ligne": numero, "texte": nue[:280]})
    return sortie
