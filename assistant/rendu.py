"""Rendu Markdown -> HTML, sans dependance.

Couvre ce qu'un coffre Obsidian utilise reellement : metadonnees en tete de
page, titres, listes, tableaux, encadres `> [!type]`, blocs de code, liens
`[[...]]` et liens Markdown ordinaires.

Le rendu est volontairement sans etat global : la resolution des liens
`[[...]]` est passee en parametre, pour que ce module ne sache rien du coffre.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

# --------------------------------------------------------------- metadonnees

_SEPARATEUR = re.compile(r"^---\s*$")


def separer_entete(texte: str) -> tuple[dict, str]:
    """Detache les metadonnees YAML en tete de page du corps du document."""
    lignes = texte.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lignes or not _SEPARATEUR.match(lignes[0]):
        return {}, texte
    for i in range(1, len(lignes)):
        if _SEPARATEUR.match(lignes[i]):
            return _lire_yaml(lignes[1:i]), "\n".join(lignes[i + 1 :])
    return {}, texte


def _lire_yaml(lignes: Iterable[str]) -> dict:
    """Sous-ensemble de YAML : `cle: valeur`, listes en ligne et listes a tirets."""
    meta: dict = {}
    cle_courante: str | None = None
    for ligne in lignes:
        if not ligne.strip():
            continue
        tiret = re.match(r"^\s*-\s+(.*)$", ligne)
        if tiret and cle_courante:
            meta.setdefault(cle_courante, [])
            if isinstance(meta[cle_courante], list):
                meta[cle_courante].append(_nettoyer_valeur(tiret.group(1)))
            continue
        paire = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", ligne)
        if not paire:
            continue
        cle, valeur = paire.group(1).strip(), paire.group(2).strip()
        cle_courante = cle
        if not valeur:
            meta[cle] = []
        elif valeur.startswith("[") and valeur.endswith("]"):
            elements = [e.strip() for e in valeur[1:-1].split(",")]
            meta[cle] = [_nettoyer_valeur(e) for e in elements if e.strip()]
        else:
            meta[cle] = _nettoyer_valeur(valeur)
    return meta


def _nettoyer_valeur(valeur: str) -> str:
    valeur = valeur.strip()
    if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in "\"'":
        return valeur[1:-1]
    return valeur


# ------------------------------------------------------------------- en ligne

_CODE = re.compile(r"`([^`]+)`")
_WIKI = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")
_LIEN = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_GRAS = re.compile(r"\*\*([^*]+)\*\*")
_ITAL = re.compile(r"(?<![\*\w])\*([^*\n]+)\*(?!\*)")
_BARRE = re.compile(r"~~([^~]+)~~")

# Resolveur de lien : nom -> (url, existe) ; None pour ne pas rendre de lien.
Resolveur = Callable[[str], tuple[str, bool] | None]


def rendre_en_ligne(texte: str, resoudre: Resolveur | None = None) -> str:
    """Echappe le texte puis applique le balisage en ligne, code d'abord."""
    morceaux: list[str] = []

    def garder(fragment: str) -> str:
        morceaux.append(fragment)
        return "\x00%d\x00" % (len(morceaux) - 1)

    # Le code en ligne est mis de cote : rien ne doit etre interprete dedans.
    texte = _CODE.sub(lambda m: garder("<code>" + html.escape(m.group(1)) + "</code>"), texte)

    def wiki(m: re.Match) -> str:
        cible = m.group(1).strip()
        affiche = (m.group(2) or cible).strip()
        # Obsidian autorise une ancre : [[Page#Section]].
        base = cible.split("#", 1)[0].strip() or cible
        if resoudre is None:
            return garder("<span class=\"wiki\">" + html.escape(affiche) + "</span>")
        resultat = resoudre(base)
        if resultat is None:
            return garder(
                '<span class="lien-casse" title="Aucune page de ce nom dans le coffre">'
                + html.escape(affiche)
                + "</span>"
            )
        url, existe = resultat
        classe = "lien-interne" if existe else "lien-casse"
        return garder(
            '<a class="%s" href="%s">%s</a>' % (classe, html.escape(url, quote=True), html.escape(affiche))
        )

    texte = _WIKI.sub(wiki, texte)

    def lien(m: re.Match) -> str:
        libelle, url = m.group(1), m.group(2)
        externe = url.startswith(("http://", "https://"))
        attrs = ' target="_blank" rel="noreferrer noopener"' if externe else ""
        classe = "lien-externe" if externe else "lien-interne"
        return garder(
            '<a class="%s" href="%s"%s>%s</a>'
            % (classe, html.escape(url, quote=True), attrs, html.escape(libelle))
        )

    texte = _LIEN.sub(lien, texte)

    texte = html.escape(texte)
    texte = _GRAS.sub(r"<strong>\1</strong>", texte)
    texte = _ITAL.sub(r"<em>\1</em>", texte)
    texte = _BARRE.sub(r"<del>\1</del>", texte)

    return re.sub(r"\x00(\d+)\x00", lambda m: morceaux[int(m.group(1))], texte)


# ------------------------------------------------------------------ par bloc

_TITRE = re.compile(r"^(#{1,6})\s+(.*)$")
_PUCE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUM = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_CITATION = re.compile(r"^>\s?(.*)$")
_ENCADRE = re.compile(r"^\[!([A-Za-z0-9_\-]+)\]([-+])?\s*(.*)$")
_CLOTURE = re.compile(r"^\s*(```+|~~~+)\s*([A-Za-z0-9_+-]*)\s*$")
_REGLE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


@dataclass
class Rendu:
    html: str
    titres: list[tuple[int, str, str]] = field(default_factory=list)
    liens_casses: list[str] = field(default_factory=list)
    secrets: int = 0


def rendre(
    corps: str,
    resoudre: Resolveur | None = None,
    mode_joueurs: bool = False,
    types_secrets: tuple[str, ...] = ("mj",),
) -> Rendu:
    """Rend le corps d'une page. En mode joueurs, les encadres secrets sautent."""
    lignes = corps.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sortie: list[str] = []
    resultat = Rendu(html="")
    casses: list[str] = []

    def resoudre_et_noter(nom: str):
        if resoudre is None:
            return None
        trouve = resoudre(nom)
        if trouve is None:
            casses.append(nom)
        return trouve

    res = resoudre_et_noter if resoudre is not None else None
    i = 0
    n = len(lignes)

    while i < n:
        ligne = lignes[i]

        if not ligne.strip():
            i += 1
            continue

        # Bloc de code cloture.
        cloture = _CLOTURE.match(ligne)
        if cloture:
            marque, langue = cloture.group(1), cloture.group(2)
            i += 1
            contenu: list[str] = []
            while i < n and not re.match(r"^\s*" + marque[0] * len(marque) + r"\s*$", lignes[i]):
                contenu.append(lignes[i])
                i += 1
            i += 1
            classe = ' class="langue-%s"' % html.escape(langue, quote=True) if langue else ""
            sortie.append(
                "<pre><code%s>%s</code></pre>" % (classe, html.escape("\n".join(contenu)))
            )
            continue

        if _REGLE.match(ligne):
            sortie.append("<hr>")
            i += 1
            continue

        titre = _TITRE.match(ligne)
        if titre:
            niveau = len(titre.group(1))
            texte = titre.group(2).strip()
            ancre = ancrer(texte)
            resultat.titres.append((niveau, texte, ancre))
            sortie.append(
                '<h%d id="%s">%s</h%d>'
                % (niveau, html.escape(ancre, quote=True), rendre_en_ligne(texte, res), niveau)
            )
            i += 1
            continue

        # Tableau : une ligne de cellules suivie d'une ligne de separation.
        if "|" in ligne and i + 1 < n and _TABLE_SEP.match(lignes[i + 1]):
            entete = _cellules(ligne)
            i += 2
            corps_table: list[list[str]] = []
            while i < n and "|" in lignes[i] and lignes[i].strip():
                corps_table.append(_cellules(lignes[i]))
                i += 1
            sortie.append(_table_html(entete, corps_table, res))
            continue

        # Citation ou encadre.
        if _CITATION.match(ligne):
            bloc: list[str] = []
            while i < n and _CITATION.match(lignes[i]):
                bloc.append(_CITATION.match(lignes[i]).group(1))
                i += 1
            rendu_bloc, secrets = _citation_html(bloc, res, mode_joueurs, types_secrets)
            resultat.secrets += secrets
            if rendu_bloc:
                sortie.append(rendu_bloc)
            continue

        # Listes.
        if _PUCE.match(ligne) or _NUM.match(ligne):
            bloc_liste, i = _lire_liste(lignes, i)
            sortie.append(_liste_html(bloc_liste, res))
            continue

        # Paragraphe : jusqu'a la prochaine ligne vide ou le prochain bloc.
        para: list[str] = []
        while i < n and lignes[i].strip():
            courante = lignes[i]
            if (
                _TITRE.match(courante)
                or _CITATION.match(courante)
                or _PUCE.match(courante)
                or _NUM.match(courante)
                or _CLOTURE.match(courante)
                or _REGLE.match(courante)
            ):
                break
            if "|" in courante and i + 1 < n and _TABLE_SEP.match(lignes[i + 1]):
                break
            para.append(courante.strip())
            i += 1
        if para:
            sortie.append("<p>" + rendre_en_ligne(" ".join(para), res) + "</p>")

    resultat.html = "\n".join(sortie)
    # Dedoublonne en conservant l'ordre d'apparition.
    resultat.liens_casses = list(dict.fromkeys(casses))
    return resultat


def ancrer(texte: str) -> str:
    propre = re.sub(r"[^\w\s-]", "", texte, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s]+", "-", propre) or "section"


def _cellules(ligne: str) -> list[str]:
    """Decoupe une ligne de tableau sur ses `|` de separation.

    Un `|` qui appartient a un lien `[[Page|Titre affiche]]`, a du code en
    ligne, ou qui est echappe `\\|`, ne separe pas deux cellules : sans cela
    les liens d'Obsidian places dans un tableau seraient coupes en deux.
    """
    brut = ligne.strip()
    if brut.startswith("|"):
        brut = brut[1:]
    if brut.endswith("|") and not brut.endswith("\\|"):
        brut = brut[:-1]

    cellules: list[str] = []
    courant: list[str] = []
    dans_wiki = False
    dans_code = False
    i = 0
    n = len(brut)
    while i < n:
        caractere = brut[i]
        if caractere == "\\" and i + 1 < n and brut[i + 1] == "|":
            courant.append("|")
            i += 2
            continue
        if caractere == "`":
            dans_code = not dans_code
            courant.append(caractere)
            i += 1
            continue
        if not dans_code and not dans_wiki and brut.startswith("[[", i):
            dans_wiki = True
            courant.append("[[")
            i += 2
            continue
        if not dans_code and dans_wiki and brut.startswith("]]", i):
            dans_wiki = False
            courant.append("]]")
            i += 2
            continue
        if caractere == "|" and not dans_wiki and not dans_code:
            cellules.append("".join(courant).strip())
            courant = []
            i += 1
            continue
        courant.append(caractere)
        i += 1
    cellules.append("".join(courant).strip())
    return cellules


def _table_html(entete: list[str], corps: list[list[str]], res: Resolveur | None) -> str:
    colonnes = max([len(entete)] + [len(r) for r in corps] or [0])
    morceaux = ["<div class=\"table-enveloppe\"><table>", "<thead><tr>"]
    for idx in range(colonnes):
        cellule = entete[idx] if idx < len(entete) else ""
        morceaux.append("<th>" + rendre_en_ligne(cellule, res) + "</th>")
    morceaux.append("</tr></thead><tbody>")
    for rangee in corps:
        if not any(c.strip() for c in rangee):
            continue
        morceaux.append("<tr>")
        for idx in range(colonnes):
            cellule = rangee[idx] if idx < len(rangee) else ""
            morceaux.append("<td>" + rendre_en_ligne(cellule, res) + "</td>")
        morceaux.append("</tr>")
    morceaux.append("</tbody></table></div>")
    return "".join(morceaux)


def _lire_liste(lignes: list[str], i: int) -> tuple[list[tuple[int, bool, str]], int]:
    """Renvoie [(indentation, ordonnee, texte)] et l'indice de reprise."""
    elements: list[tuple[int, bool, str]] = []
    n = len(lignes)
    while i < n:
        ligne = lignes[i]
        if not ligne.strip():
            # Une ligne vide ne coupe la liste que si la suivante n'en fait pas partie.
            if i + 1 < n and (_PUCE.match(lignes[i + 1]) or _NUM.match(lignes[i + 1])):
                i += 1
                continue
            break
        puce = _PUCE.match(ligne)
        num = _NUM.match(ligne)
        if puce:
            elements.append((len(puce.group(1)), False, puce.group(2)))
        elif num:
            elements.append((len(num.group(1)), True, num.group(3)))
        elif elements and ligne.startswith((" ", "\t")):
            # Continuation de l'element precedent.
            indent, ordonnee, texte = elements[-1]
            elements[-1] = (indent, ordonnee, texte + " " + ligne.strip())
        else:
            break
        i += 1
    return elements, i


def _liste_html(elements: list[tuple[int, bool, str]], res: Resolveur | None) -> str:
    if not elements:
        return ""
    sortie: list[str] = []
    pile: list[tuple[int, str]] = []

    for indent, ordonnee, texte in elements:
        balise = "ol" if ordonnee else "ul"
        while pile and indent < pile[-1][0]:
            sortie.append("</li></%s>" % pile.pop()[1])
        if not pile:
            pile.append((indent, balise))
            sortie.append("<%s>" % balise)
        elif indent > pile[-1][0]:
            pile.append((indent, balise))
            sortie.append("<%s>" % balise)
        else:
            sortie.append("</li>")
        sortie.append("<li>" + rendre_en_ligne(texte, res))
    while pile:
        sortie.append("</li></%s>" % pile.pop()[1])
    return "".join(sortie)


def _citation_html(
    bloc: list[str],
    res: Resolveur | None,
    mode_joueurs: bool,
    types_secrets: tuple[str, ...],
) -> tuple[str, int]:
    """Rend une citation, ou un encadre `> [!type]` si la premiere ligne en est un."""
    if not bloc:
        return "", 0

    encadre = _ENCADRE.match(bloc[0].strip())
    if not encadre:
        interieur = rendre("\n".join(bloc), res, mode_joueurs, types_secrets)
        return "<blockquote>" + interieur.html + "</blockquote>", interieur.secrets

    genre = encadre.group(1).lower()
    pliage = encadre.group(2)
    titre = encadre.group(3).strip() or genre.upper()
    secret = genre in types_secrets

    if secret and mode_joueurs:
        # Mode joueurs : l'encadre n'est pas envoye au navigateur du tout.
        return "", 1

    interieur = rendre("\n".join(bloc[1:]), res, mode_joueurs, types_secrets)
    classes = "encadre encadre-%s" % html.escape(genre, quote=True)
    if secret:
        classes += " encadre-secret"
    ouvert = "" if pliage == "-" else " open"
    return (
        '<details class="%s"%s><summary>%s</summary><div class="encadre-corps">%s</div></details>'
        % (classes, ouvert, rendre_en_ligne(titre, res), interieur.html),
        interieur.secrets + (1 if secret else 0),
    )


def retirer_secrets(corps: str, types_secrets: tuple[str, ...] = ("mj",)) -> str:
    """Version texte du corps, encadres secrets retires.

    Sert a construire le contexte envoye au modele quand le MJ demande un texte
    destine aux joueurs (CLAUDE.md : proteger les secrets).
    """
    lignes = corps.replace("\r\n", "\n").split("\n")
    sortie: list[str] = []
    i = 0
    while i < len(lignes):
        citation = _CITATION.match(lignes[i])
        if citation:
            encadre = _ENCADRE.match(citation.group(1).strip())
            if encadre and encadre.group(1).lower() in types_secrets:
                while i < len(lignes) and _CITATION.match(lignes[i]):
                    i += 1
                continue
        sortie.append(lignes[i])
        i += 1
    return "\n".join(sortie)
