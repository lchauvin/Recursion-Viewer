"""Les cartes : une page du coffre decrit des lieux, l'outil les dessine.

Une carte est une page ordinaire, de metadonnee `type: carte`. Ses lieux sont
les lignes de ses tableaux Markdown : lisibles et modifiables dans Obsidian,
sans format a apprendre. Comme ailleurs, ce module ne connait aucun nom de
lieu : il lit ce qu'il trouve (DESIGN 4).

Colonnes reconnues (sans accents ni casse, dans n'importe quel ordre) ; seule
`Lieu` est obligatoire :

    Lieu     le nom affiche, ou un lien [[Page|Nom]] vers la page du lieu
    Dans     le lieu parent ; vide pour un lieu a la racine
    Orbite   la distance au parent
    Angle    en degres : 0 a droite, 90 en haut ; vide pour repartir
    Taille   le rayon du lieu, dans les memes unites que l'orbite
    Forme    etoile, planete, lune, ceinture, anneau, region, zone, ruche, station,
             balise, flotte, signal, reve, lieu, continent, ville, quartier
    Couleur  #rrggbb ou un nom de couleur CSS
    Calque   vide pour le calque de base ; un nom pour un calque a part
    Relie    des lieux auxquels tracer un fil, separes par des virgules
    Note     une phrase affichee au survol ; a defaut, le debut de la page

La metadonnee `fond:` choisit le decor : `ciel` (etoiles, par defaut) ou
`brume` (un monde de songe, sans etoiles).

Les secrets suivent la regle du coffre : un tableau place dans un encadre
`> [!mj]` est reserve au MJ, et un lieu dont la page est reservee au MJ aussi.
En mode joueurs, ces lieux, leurs descendants et leurs fils ne sont pas
envoyes du tout.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import rendu
from .coffre import Index, Page, plier

TYPE_CARTE = "carte"

COLONNES = {
    "lieu": "nom",
    "nom": "nom",
    "dans": "parent",
    "parent": "parent",
    "orbite": "orbite",
    "distance": "orbite",
    "angle": "angle",
    "taille": "taille",
    "rayon": "taille",
    "forme": "forme",
    "couleur": "couleur",
    "calque": "calque",
    "plan": "calque",
    "relie": "relie",
    "liens": "relie",
    "note": "note",
    "resume": "note",
}

FORMES = {
    "etoile", "planete", "lune", "ceinture", "anneau", "zone", "ruche",
    "station", "balise", "flotte", "signal", "reve", "lieu", "region",
    "continent", "ville", "quartier",
}

# Le decor de fond, choisi par la metadonnee `fond:` de la page.
FONDS = {"ciel", "brume"}

# Les formes qui entourent leur parent au lieu de se poser a un point.
BANDES = {"ceinture", "anneau", "region"}

_COULEUR = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,24})$")
_WIKI_SEUL = re.compile(r"^\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]$")
_SEPARATION = re.compile(r"^\s*\|?\s*:?-{2,}")


@dataclass
class Lieu:
    id: str
    nom: str
    cible: str | None  # le nom de page vise par [[...]], s'il y en a un
    parent_brut: str
    orbite: float
    angle: float | None
    taille: float
    forme: str
    couleur: str
    calque: str
    relie_brut: list[str]
    note: str
    ligne: int
    page: Page | None = None
    parent: str | None = None
    enfants: list[str] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    secret: bool = False


# ------------------------------------------------------------------- lecture


def est_carte(page: Page) -> bool:
    return plier(page.type) == TYPE_CARTE


def cartes(index: Index, mode_joueurs: bool = False) -> list[Page]:
    index.rafraichir()
    trouvees = [
        p for p in index.pages.values()
        if est_carte(p) and not (mode_joueurs and p.reserve_mj)
    ]
    return sorted(trouvees, key=lambda p: plier(p.chemin))


def _texte_brut(cellule: str) -> str:
    """Le texte d'une cellule, sans balisage : [[A|B]] donne B."""
    texte = re.sub(
        r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]",
        lambda m: (m.group(2) or m.group(1).split("#", 1)[0]).strip(),
        cellule,
    )
    texte = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", texte)
    texte = re.sub(r"[*_`~]", "", texte)
    return re.sub(r"\s+", " ", texte).strip()


def _nombre(cellule: str) -> float | None:
    brut = cellule.strip().replace(",", ".").rstrip("°").strip()
    if not brut:
        return None
    try:
        valeur = float(brut)
    except ValueError:
        return None
    return valeur if math.isfinite(valeur) else None


def _sans_citations(corps: str) -> str:
    """Les tableaux places dans un encadre restent des tableaux."""
    return "\n".join(re.sub(r"^\s*>\s?", "", l) for l in corps.split("\n"))


def lire_lignes(corps: str) -> tuple[list[dict], list[str]]:
    """Toutes les lignes des tableaux de lieux d'un corps de page."""
    lignes = _sans_citations(corps.replace("\r\n", "\n")).split("\n")
    rangees: list[dict] = []
    erreurs: list[str] = []
    i = 0
    while i < len(lignes):
        ligne = lignes[i]
        if (
            ligne.strip().startswith("|")
            and i + 1 < len(lignes)
            and _SEPARATION.match(lignes[i + 1])
        ):
            entete = [COLONNES.get(plier(_texte_brut(c))) for c in rendu._cellules(ligne)]
            i += 2
            if "nom" not in entete:
                # Un tableau ordinaire : on le saute.
                while i < len(lignes) and lignes[i].strip().startswith("|"):
                    i += 1
                continue
            while i < len(lignes) and lignes[i].strip().startswith("|"):
                cellules = rendu._cellules(lignes[i])
                rangee = {"_ligne": i + 1}
                for idx, cle in enumerate(entete):
                    if cle and idx < len(cellules):
                        rangee[cle] = cellules[idx]
                if rangee.get("nom", "").strip():
                    rangees.append(rangee)
                i += 1
            continue
        i += 1
    return rangees, erreurs


def _lieu(rangee: dict, ids: set[str]) -> Lieu:
    nom_brut = rangee.get("nom", "").strip()
    wiki = _WIKI_SEUL.match(nom_brut)
    cible = None
    if wiki:
        cible = wiki.group(1).split("#", 1)[0].strip() or None
        nom = (wiki.group(2) or wiki.group(1).split("#", 1)[0]).strip()
    else:
        nom = _texte_brut(nom_brut)

    base = re.sub(r"[^a-z0-9]+", "-", plier(nom)).strip("-") or "lieu"
    ident, n = base, 2
    while ident in ids:
        ident, n = "%s-%d" % (base, n), n + 1
    ids.add(ident)

    forme = plier(_texte_brut(rangee.get("forme", "")))
    couleur = _texte_brut(rangee.get("couleur", ""))
    relie = [
        _texte_brut(r) for r in re.split(r"[,;]", rangee.get("relie", "")) if _texte_brut(r)
    ]
    return Lieu(
        id=ident,
        nom=nom,
        cible=cible,
        parent_brut=_texte_brut(rangee.get("parent", "")),
        orbite=max(0.0, _nombre(rangee.get("orbite", "")) or 0.0),
        angle=_nombre(rangee.get("angle", "")),
        taille=max(0.0, _nombre(rangee.get("taille", "")) or 0.0),
        forme=forme if forme in FORMES else "lieu",
        couleur=couleur if _COULEUR.match(couleur) else "",
        calque=_texte_brut(rangee.get("calque", "")),
        relie_brut=relie,
        note=_texte_brut(rangee.get("note", ""))[:400],
        ligne=rangee["_ligne"],
    )


# --------------------------------------------------------------- construction


def _extrait(page: Page, mode_joueurs: bool) -> str:
    """Le premier paragraphe de texte d'une page, pour la note au survol."""
    corps = rendu.retirer_secrets(page.corps) if mode_joueurs else page.corps
    for bloc in re.split(r"\n\s*\n", corps):
        bloc = bloc.strip()
        if not bloc or bloc[0] in "#|>-*!`<" or bloc[0].isdigit() and ". " in bloc[:4]:
            continue
        texte = _texte_brut(bloc)
        if len(texte) < 40:
            continue
        if len(texte) > 260:
            coupe = texte.rfind(" ", 0, 250)
            texte = texte[: coupe if coupe > 0 else 250].rstrip(" ,;:") + "…"
        return texte
    return ""


def _lieux(index: Index, corps: str) -> tuple[list[Lieu], list[str]]:
    rangees, erreurs = lire_lignes(corps)
    ids: set[str] = set()
    lieux = [_lieu(r, ids) for r in rangees]
    for lieu in lieux:
        if lieu.cible:
            lieu.page = index.resoudre(lieu.cible)
            if lieu.page is None:
                erreurs.append("ligne %d : aucune page « %s »" % (lieu.ligne, lieu.cible))
    return lieux, erreurs


def _table_noms(lieux: list[Lieu]) -> dict[str, Lieu]:
    """Un lieu se designe par son nom affiche, ou par le nom, le titre ou un
    alias de sa page. Le premier declare gagne en cas de doublon."""
    table: dict[str, Lieu] = {}
    for lieu in lieux:
        cles = [lieu.nom, lieu.id]
        if lieu.page is not None:
            cles += [lieu.page.nom, lieu.page.titre, *lieu.page.alias]
        for cle in cles:
            table.setdefault(plier(cle), lieu)
    return table


def construire(index: Index, page: Page, mode_joueurs: bool = False) -> dict:
    """La carte prete a dessiner : lieux, positions absolues, fils, erreurs."""
    tous, erreurs = _lieux(index, page.corps)
    publics, _ = _lieux(index, rendu.retirer_secrets(page.corps))
    # Un lieu est secret s'il vient d'un encadre MJ (absent de la version
    # publique), ou si sa page est reservee au MJ.
    noms_publics = {(l.nom, l.parent_brut) for l in publics if not (l.page and l.page.reserve_mj)}
    lieux = publics if mode_joueurs else tous
    for lieu in lieux:
        lieu.secret = (lieu.nom, lieu.parent_brut) not in noms_publics

    table = _table_noms(lieux)
    for lieu in lieux:
        if not lieu.parent_brut:
            continue
        parent = table.get(plier(lieu.parent_brut))
        if parent is None:
            if not mode_joueurs:
                erreurs.append(
                    "ligne %d : « %s » est dans « %s », qui n'est pas sur la carte"
                    % (lieu.ligne, lieu.nom, lieu.parent_brut)
                )
            continue
        if parent is lieu:
            continue
        lieu.parent = parent.id

    par_id = {l.id: l for l in lieux}

    # Pas de boucle : un lieu qui serait son propre ancetre remonte a la racine.
    for lieu in lieux:
        vus, courant = {lieu.id}, lieu.parent
        while courant:
            if courant in vus:
                erreurs.append("ligne %d : « %s » tourne en rond" % (lieu.ligne, lieu.nom))
                lieu.parent = None
                break
            vus.add(courant)
            courant = par_id[courant].parent

    # Mode joueurs : un lieu secret disparait, et avec lui tout ce qu'il contient.
    if mode_joueurs:
        caches = {l.id for l in lieux if l.secret}
        changement = True
        while changement:
            changement = False
            for lieu in lieux:
                if lieu.id not in caches and lieu.parent in caches:
                    caches.add(lieu.id)
                    changement = True
        lieux = [l for l in lieux if l.id not in caches]
        par_id = {l.id: l for l in lieux}
        table = _table_noms(lieux)

    for lieu in lieux:
        if lieu.parent:
            par_id[lieu.parent].enfants.append(lieu.id)
    racines = [l for l in lieux if not l.parent]

    # Les angles laisses vides se repartissent entre freres.
    def repartir(freres: list[Lieu]) -> None:
        libres = [l for l in freres if l.angle is None]
        for n, lieu in enumerate(libres):
            lieu.angle = 90.0 + n * 360.0 / len(libres) + (17.0 if len(libres) > 1 else 0.0)

    def placer(lieu: Lieu, x0: float, y0: float) -> None:
        a = math.radians(lieu.angle or 0.0)
        lieu.x = x0 + lieu.orbite * math.cos(a)
        lieu.y = y0 - lieu.orbite * math.sin(a)
        enfants = [par_id[e] for e in lieu.enfants]
        repartir(enfants)
        for enfant in enfants:
            placer(enfant, lieu.x, lieu.y)

    repartir(racines)
    for racine in racines:
        placer(racine, 0.0, 0.0)

    # La portee d'un lieu : le rayon qui contient ce qu'il contient, pour
    # savoir a quel zoom montrer ses enfants et ou s'arreter quand on s'y rend.
    # Une ceinture ou un anneau entoure son parent : c'est son orbite qui
    # compte, pas la distance de son point d'etiquette.
    portees: dict[str, float] = {}

    def portee(lieu: Lieu) -> float:
        if lieu.id in portees:
            return portees[lieu.id]
        r = 0.0
        for e in lieu.enfants:
            enfant = par_id[e]
            if enfant.forme in BANDES:
                r = max(r, enfant.orbite + enfant.taille / 2)
            else:
                d = math.hypot(enfant.x - lieu.x, enfant.y - lieu.y)
                r = max(r, d + max(portee(enfant), enfant.taille))
        portees[lieu.id] = r
        return r

    for lieu in lieux:
        portee(lieu)

    fils = []
    vus_fils: set[tuple[str, str]] = set()
    for lieu in lieux:
        for nom in lieu.relie_brut:
            autre = table.get(plier(nom))
            if autre is None:
                if not mode_joueurs:
                    erreurs.append(
                        "ligne %d : « %s » est relie a « %s », qui n'est pas sur la carte"
                        % (lieu.ligne, lieu.nom, nom)
                    )
                continue
            cle = tuple(sorted((lieu.id, autre.id)))
            if autre is lieu or cle in vus_fils:
                continue
            vus_fils.add(cle)
            fils.append({"de": lieu.id, "vers": autre.id, "calque": lieu.calque or autre.calque})

    def profondeur(lieu: Lieu) -> int:
        n, courant = 0, lieu.parent
        while courant:
            n, courant = n + 1, par_id[courant].parent
        return n

    noeuds = []
    for lieu in lieux:
        parent = par_id.get(lieu.parent) if lieu.parent else None
        note = lieu.note
        if not note and lieu.page is not None:
            note = _extrait(lieu.page, mode_joueurs)
        noeuds.append(
            {
                "id": lieu.id,
                "nom": lieu.nom,
                "page": lieu.page.chemin if lieu.page else None,
                "titre_page": lieu.page.titre if lieu.page else None,
                "parent": lieu.parent,
                "enfants": lieu.enfants,
                "profondeur": profondeur(lieu),
                "x": round(lieu.x, 4),
                "y": round(lieu.y, 4),
                "cx": round(parent.x, 4) if parent else 0.0,
                "cy": round(parent.y, 4) if parent else 0.0,
                "orbite": lieu.orbite,
                "angle": lieu.angle,
                "taille": lieu.taille,
                "portee": round(portees[lieu.id], 4),
                "forme": lieu.forme,
                "couleur": lieu.couleur,
                "calque": lieu.calque,
                "note": note,
                "secret": lieu.secret,
            }
        )

    calques = []
    for lieu in lieux:
        if lieu.calque and lieu.calque not in calques:
            calques.append(lieu.calque)

    return {
        "chemin": page.chemin,
        "titre": page.titre,
        "fond": fond if (fond := plier(str(page.meta.get("fond") or ""))) in FONDS else "ciel",
        "noeuds": noeuds,
        "fils": fils,
        "calques": calques,
        # Les erreurs nomment des lieux : en mode joueurs, on ne les montre pas.
        "erreurs": [] if mode_joueurs else erreurs,
    }


def situer(index: Index, chemin: str, mode_joueurs: bool = False) -> dict | None:
    """La premiere carte ou figure la page `chemin`, et le lieu qui la porte."""
    for carte in cartes(index, mode_joueurs):
        if carte.chemin == chemin:
            continue
        donnees = construire(index, carte, mode_joueurs)
        for noeud in donnees["noeuds"]:
            if noeud["page"] == chemin:
                return {"carte": carte.chemin, "titre": carte.titre, "noeud": noeud["id"]}
    return None
