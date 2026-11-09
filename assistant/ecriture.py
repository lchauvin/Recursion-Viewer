"""Ecrire dans le coffre : des propositions, validees par le MJ.

Le DESIGN (3 et 13) pose la regle « Obsidian ecrit, l'outil lit », avec une
exception envisagee : les notes de seance et de campagne. Ce module est cette
exception, et rien de plus :

- le modele ne fait que *proposer* ; rien n'est ecrit tant que le MJ n'a pas
  clique sur « Enregistrer » ;
- on n'ecrit que dans les dossiers declares pour ce coffre
  (`dossiers_ecriture`, par defaut le seul dossier de notes) ;
- jamais dans un dossier ou une page dont le nom commence par `_` ou `.`
  (les modeles, les dossiers caches), jamais dans une page de type `modele` ;
- une creation n'ecrase jamais une page ; une modification remplace un passage
  exact, qui doit encore figurer une seule fois au moment d'ecrire : si le MJ
  a modifie la page dans Obsidian entre-temps, l'ecriture est refusee plutot
  que d'ecraser son travail.

Comme le reste de l'outil, ce module ne connait aucun nom de dossier : les
dossiers autorises viennent de la configuration du coffre.

Deux facons de proposer, pour la meme validation :
- les outils `proposer_page` et `proposer_modification` (Claude) ;
- des blocs dans le texte de la reponse, pour un modele sans outils :

      ```page chemin="Dossier/Nouvelle page"
      ...contenu Markdown...
      ```

      ```ajout page="Dossier/Page existante" section="Titre de section"
      ...texte ajoute a la fin de la section (ou de la page)...
      ```
"""

from __future__ import annotations

import re
from pathlib import Path

from .coffre import Index, HorsCoffre, plier

EXTENSION = ".md"
TAILLE_MAX = 200_000
_INTERDITS = re.compile(r'[<>:"|?*\x00-\x1f]')
_TITRE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


class EcritureRefusee(Exception):
    """Une proposition qui ne respecte pas les regles : le message dit pourquoi."""


class Ecriture:
    def __init__(self, index: Index, dossiers: list[str]):
        self.index = index
        self.racine = Path(index.racine)
        self.dossiers = [d.strip().strip("/\\").replace("\\", "/") for d in dossiers if d and d.strip()]

    # ------------------------------------------------------------ chemins

    def decrire_dossiers(self) -> str:
        return ", ".join("`%s/`" % d for d in self.dossiers) or "(aucun)"

    def _verifier(self, chemin: str) -> tuple[str, Path]:
        """Valide un chemin de page ; renvoie (chemin sans extension, fichier)."""
        brut = str(chemin or "").strip().replace("\\", "/").strip("/")
        if brut.lower().endswith(EXTENSION):
            brut = brut[: -len(EXTENSION)]
        if not brut:
            raise EcritureRefusee("Chemin vide.")
        if len(brut) > 240:
            raise EcritureRefusee("Chemin trop long.")
        parties = brut.split("/")
        for partie in parties:
            if not partie.strip() or partie.strip() in (".", ".."):
                raise EcritureRefusee("Chemin invalide : %s" % brut)
            if partie.startswith(("_", ".")):
                raise EcritureRefusee(
                    "« %s » commence par « %s » : les modeles et dossiers caches ne "
                    "s'ecrivent pas." % (partie, partie[0])
                )
            if _INTERDITS.search(partie) or partie != partie.strip() or partie.endswith("."):
                raise EcritureRefusee("Caractere interdit dans « %s »." % partie)
        if not self._autorise(parties):
            raise EcritureRefusee(
                "« %s » est hors des dossiers ou l'assistant peut ecrire : %s."
                % (brut, self.decrire_dossiers())
            )
        try:
            fichier = self.index.fichier_sur(brut + EXTENSION)
        except HorsCoffre:
            raise EcritureRefusee("Chemin hors du coffre : %s" % brut) from None
        return brut, fichier

    def _autorise(self, parties: list[str]) -> bool:
        for dossier in self.dossiers:
            prefixe = [plier(p) for p in dossier.split("/") if p]
            if prefixe and len(parties) > len(prefixe) and [plier(p) for p in parties[: len(prefixe)]] == prefixe:
                return True
        return False

    def _page_modifiable(self, nom: str):
        page = self.index.page(nom) or self.index.resoudre(nom)
        if page is None:
            raise EcritureRefusee("Aucune page « %s » dans le coffre." % nom)
        chemin, fichier = self._verifier(page.chemin)
        if plier(page.type) == "modele" or plier(page.statut) == "modele":
            raise EcritureRefusee("« %s » est un modele : on ne le modifie pas." % page.chemin)
        return page, chemin, fichier

    # -------------------------------------------------------- propositions

    def preparer_creation(self, chemin: str, contenu: str, resume: str = "") -> dict:
        chemin, fichier = self._verifier(chemin)
        contenu = pas_un_modele(_normaliser(contenu))
        if not contenu.strip():
            raise EcritureRefusee("Contenu vide.")
        if len(contenu) > TAILLE_MAX:
            raise EcritureRefusee("Contenu trop long.")
        if fichier.exists() or self.index.page(chemin) is not None:
            raise EcritureRefusee(
                "La page « %s » existe deja : propose une modification plutot." % chemin
            )
        return {"genre": "creation", "chemin": chemin, "contenu": contenu, "resume": _court(resume)}

    def preparer_modification(
        self, page: str, ancien: str, nouveau: str, resume: str = "", section: str = ""
    ) -> dict:
        objet, chemin, fichier = self._page_modifiable(page)
        nouveau = _normaliser(nouveau)
        ancien = _normaliser(ancien)
        if not nouveau.strip() and not ancien:
            raise EcritureRefusee("Rien a ecrire.")
        if len(nouveau) > TAILLE_MAX:
            raise EcritureRefusee("Texte trop long.")
        texte = _normaliser(_lire(fichier))
        if ancien:
            n = texte.count(ancien)
            if n == 0:
                raise EcritureRefusee(
                    "Le passage a remplacer ne figure pas tel quel dans « %s ». Relis la "
                    "page et recopie-le exactement." % chemin
                )
            if n > 1:
                raise EcritureRefusee(
                    "Le passage a remplacer figure %d fois dans « %s » : allonge-le pour "
                    "qu'il soit unique." % (n, chemin)
                )
        elif section.strip() and _bornes_section(texte, section) is None:
            raise EcritureRefusee("Aucune section « %s » dans « %s »." % (section, chemin))
        return {
            "genre": "modification",
            "chemin": chemin,
            "titre": objet.titre,
            "ancien": ancien,
            "nouveau": nouveau,
            "section": section.strip(),
            "resume": _court(resume),
        }

    # ------------------------------------------------------------ ecriture

    def appliquer(self, proposition: dict, contenu: str | None = None) -> str:
        """Ecrit une proposition validee. `contenu` remplace le texte propose
        (le MJ a pu le retoucher). Renvoie le chemin de la page ecrite."""
        if proposition.get("genre") == "creation":
            texte = proposition["contenu"] if contenu is None else contenu
            prete = self.preparer_creation(proposition["chemin"], texte)
            _, fichier = self._verifier(prete["chemin"])
            fichier.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(fichier, "x", encoding="utf-8", newline="\n") as f:
                    f.write(prete["contenu"].rstrip("\n") + "\n")
            except FileExistsError:
                raise EcritureRefusee("La page « %s » existe deja." % prete["chemin"]) from None
            return prete["chemin"]

        if proposition.get("genre") == "modification":
            nouveau = proposition["nouveau"] if contenu is None else contenu
            # On revalide contre la page telle qu'elle est maintenant.
            prete = self.preparer_modification(
                proposition["chemin"], proposition.get("ancien", ""), nouveau,
                section=proposition.get("section", ""),
            )
            _, chemin, fichier = self._page_modifiable(prete["chemin"])
            brut = _lire(fichier)
            crlf = "\r\n" in brut
            texte = _normaliser(brut)
            if prete["ancien"]:
                texte = texte.replace(prete["ancien"], prete["nouveau"], 1)
            else:
                texte = _ajouter(texte, prete["nouveau"], prete["section"])
            if crlf:
                texte = texte.replace("\n", "\r\n")
            temporaire = fichier.with_name(fichier.name + ".tmp-assistant")
            temporaire.write_bytes(texte.encode("utf-8"))
            temporaire.replace(fichier)
            return chemin

        raise EcritureRefusee("Proposition inconnue.")


# ------------------------------------------------------------------- blocs

_BLOC = re.compile(
    r"^(?P<clotures>`{3,})(?P<genre>page|ajout)[ \t]+(?P<attrs>[^\n]*)\n(?P<corps>.*?)\n(?P=clotures)[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def blocs_de(texte: str) -> list[dict]:
    """Les propositions ecrites en blocs dans une reponse (modele sans outils)."""
    trouves = []
    for m in _BLOC.finditer(texte or ""):
        attrs = {k.lower(): v for k, v in _ATTR.findall(m.group("attrs"))}
        trouves.append({"genre": m.group("genre"), "attrs": attrs, "corps": m.group("corps")})
    return trouves


# ------------------------------------------------------------------ outils

def pas_un_modele(contenu: str) -> str:
    """Une page creee a partir d'un modele n'est pas un modele.

    Un modele se reconnait a `type: modele` (et souvent `modele_de: X`) ou a
    `statut: modele`. Recopie tel quel, il ferait de la nouvelle page un
    modele de plus, que l'assistant refuserait ensuite de completer. La page
    prend donc le type `X` du modele, et le statut `brouillon`.
    """
    m = re.match(r"---\n(.*?)\n---(\n|$)", contenu, re.DOTALL)
    if not m:
        return contenu
    lignes = m.group(1).split("\n")
    valeurs = {}
    for ligne in lignes:
        paire = re.match(r"\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$", ligne)
        if paire:
            valeurs[paire.group(1).lower()] = paire.group(2).strip("\"'")
    type_modele = plier(valeurs.get("type", "")) == "modele"
    statut_modele = plier(valeurs.get("statut", "")) == "modele"
    if not (type_modele or statut_modele or "modele_de" in valeurs):
        return contenu
    nouveau_type = valeurs.get("modele_de", "")
    sortie = []
    for ligne in lignes:
        cle = ligne.split(":", 1)[0].strip().lower()
        if cle == "modele_de":
            if not type_modele and "type" not in valeurs and nouveau_type:
                sortie.append("type: " + nouveau_type)
            continue
        if cle == "type" and type_modele:
            if nouveau_type:
                sortie.append("type: " + nouveau_type)
            continue
        if cle == "statut" and statut_modele:
            sortie.append("statut: brouillon")
            continue
        sortie.append(ligne)
    return "---\n" + "\n".join(sortie) + "\n---" + m.group(2) + contenu[m.end():]


def _normaliser(texte: str) -> str:
    return str(texte or "").replace("\r\n", "\n").replace("\r", "\n")


def _court(texte: str) -> str:
    return re.sub(r"\s+", " ", str(texte or "")).strip()[:240]


def _lire(fichier: Path) -> str:
    try:
        return fichier.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise EcritureRefusee("Page illisible : %s" % err) from None


def _bornes_section(texte: str, section: str) -> tuple[int, int] | None:
    """Lignes [debut, fin) du corps d'une section, titre exclu."""
    lignes = texte.split("\n")
    cible = plier(section.strip().lstrip("#").strip())
    for i, ligne in enumerate(lignes):
        m = _TITRE.match(ligne)
        if m and plier(m.group(2)) == cible:
            niveau = len(m.group(1))
            fin = len(lignes)
            for j in range(i + 1, len(lignes)):
                autre = _TITRE.match(lignes[j])
                if autre and len(autre.group(1)) <= niveau:
                    fin = j
                    break
            return i + 1, fin
    return None


def _ajouter(texte: str, ajout: str, section: str) -> str:
    """Ajoute a la fin d'une section (avant ses lignes vides finales), ou de la page."""
    ajout = ajout.strip("\n")
    bornes = _bornes_section(texte, section) if section else None
    if bornes is None:
        return texte.rstrip("\n") + "\n\n" + ajout + "\n"
    lignes = texte.split("\n")
    debut, fin = bornes
    while fin > debut and not lignes[fin - 1].strip():
        fin -= 1
    # Une ligne a puce ou de tableau laissee vide par un modele (« - », « | | |»)
    # est remplacee plutot que suivie.
    if fin > debut and re.fullmatch(r"\s*[-*]\s*|\s*(\|\s*)+", lignes[fin - 1]):
        fin -= 1
        del lignes[fin]
    separateur = [] if fin > debut and _meme_bloc(lignes[fin - 1], ajout) else [""]
    return "\n".join(lignes[:fin] + separateur + [ajout] + lignes[fin:])


def _meme_bloc(derniere: str, ajout: str) -> bool:
    """Une liste qui continue une liste, un tableau qui continue un tableau."""
    premiere = ajout.split("\n", 1)[0].lstrip()
    d = derniere.lstrip()
    return (d.startswith(("- ", "* ")) and premiere.startswith(("- ", "* "))) or (
        d.startswith("|") and premiere.startswith("|")
    )
