"""L'assistant : construction du contexte, outils, et conduite de la conversation.

Le contexte envoye au modele a chaque message (DESIGN 9) :

 1. CLAUDE.md du coffre comme instructions systeme, avec une consigne de
    citation propre a l'outil ;
 2. l'index : la liste des pages, leur chemin, leur titre, leur type ;
 3. les pages pertinentes, en entier ;
 4. l'historique de la conversation en cours.

Avec Claude, le modele demande lui-meme les pages dont il a besoin, par leur
nom. Avec un modele local sans outils, l'outil envoie les pages dont le titre
ou les alias apparaissent dans la question, plus les pages epinglees.
"""

from __future__ import annotations

import urllib.parse
from typing import Iterator

from . import rendu
from .coffre import Index, Page, plier
from .modele import Modele

LIMITE_PAGES_AUTO = 6
LIMITE_CARACTERES_OUTIL = 60000

# Budget de contexte pour un modele sans outils, en caracteres (~4 par token).
# Le coffre de Recursion fait environ 134 000 caracteres : il tient donc en
# entier, ce que DESIGN 3 anticipait. A baisser pour un petit modele local.
CONTEXTE_MAX = 200000

INSTRUCTIONS_GENERIQUES = """\
Tu assistes la personne qui mene une partie de jeu de role. Le coffre de notes
ci-dessous est la seule source de verite : appuie-toi sur lui, cite tes sources,
et n'invente jamais une regle sans dire clairement que tu improvises.
"""

CONSIGNE_CITATION = """\
# Citer tes sources dans cet outil

Tu reponds dans une application web locale qui affiche le coffre. Les citations
doivent y etre cliquables, ce qui remplace la consigne de citation du coffre.

- Cite chaque page par un lien Markdown vers l'outil, sous la forme
  `[Titre affiche](/page/<chemin de la page, encode>)`.
  Exemple : `[Le Reve](/page/03%20Regles/Le%20Reve)`.
- Le chemin est celui donne dans l'index ci-dessous, sans l'extension `.md`,
  avec les espaces encodes en `%20`.
- N'utilise jamais la syntaxe `[[...]]` dans tes reponses : elle ne s'affiche
  pas comme un lien ici.
- Cite une page des que tu t'appuies sur elle, au fil du texte, pas seulement
  en fin de reponse.
- Quand tu improvises parce que le coffre ne couvre pas la situation, dis-le en
  une phrase avant de proposer ta decision.
"""

# Avec outils : le modele demande lui-meme les pages dont il a besoin.
CONSIGNE_OUTILS = """\
- Pour consulter une page, utilise l'outil `lire_page`. Ne devine jamais le
  contenu d'une page que tu n'as pas lue.
"""

# Sans outils : le modele ne peut rien demander. Lui dire d'aller lire une page
# le ferait s'arreter en annoncant une consultation qui n'arrivera jamais.
CONSIGNE_SANS_OUTILS = """\
- Tu n'as aucun outil et tu ne peux demander aucune page : les pages du coffre
  te sont fournies ci-dessous, en entier. Reponds a partir d'elles.
- N'annonce jamais que tu vas consulter, lire ou verifier une page : tu ne le
  peux pas, et la reponse s'arreterait la. Reponds directement.
- S'il te manque vraiment un element, dis-le en une phrase, puis reponds au
  mieux avec ce que tu as.
"""

CONSIGNE_MODE_JOUEURS = """\
# Mode joueurs actif

L'ecran est tourne vers les joueurs. Tu ne disposes que des pages dont la
visibilite est `joueurs`, et les encadres reserves au MJ ont ete retires du
contexte. N'evoque aucun secret, meme par allusion, et ne reclame pas une page
reservee au MJ : dis simplement qu'elle n'est pas disponible dans ce mode.
"""

OUTILS = [
    {
        "name": "lire_page",
        "description": (
            "Lit une page du coffre en entier. Donne soit le chemin exact tel qu'il "
            "apparait dans l'index (par exemple '03 Regles/Le Reve'), soit le nom ou "
            "le titre de la page (par exemple 'Le Reve'). Appelle cet outil pour "
            "chaque page sur laquelle tu veux t'appuyer, plusieurs a la fois si besoin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "string",
                    "description": "Chemin, nom de fichier, titre ou alias de la page.",
                }
            },
            "required": ["page"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "chercher",
        "description": (
            "Recherche plein texte dans tout le coffre, sans accents ni casse. "
            "Renvoie les pages trouvees avec leur chemin et les lignes qui "
            "contiennent les termes. Utile quand tu ne sais pas quelle page lire."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requete": {"type": "string", "description": "Les mots a chercher."},
                "type": {
                    "type": "string",
                    "description": "Filtre optionnel sur la metadonnee `type` d'une page.",
                },
            },
            "required": ["requete"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def url_de_page(chemin: str) -> str:
    return "/page/" + urllib.parse.quote(chemin)


# Mots trop courants pour designer une page : ils feraient remonter tout le coffre.
VIDES = {
    "avec", "sans", "dans", "pour", "cette", "cela", "celui", "elle", "elles",
    "nous", "vous", "ils", "mais", "donc", "quoi", "quel", "quelle", "quels",
    "quelles", "comment", "pourquoi", "est-ce", "peux", "peut", "faire", "fait",
    "dire", "dis", "donne", "donner", "explique", "expliquer", "phrase",
    "phrases", "mot", "mots", "page", "pages", "joueur", "joueurs", "partie",
    "quand", "alors", "aussi", "plus", "moins", "tout", "tous", "toute",
    "toutes", "entre", "chaque", "leur", "leurs", "etre", "avoir",
}


def _mots_utiles(question: str) -> str:
    """Retire la ponctuation, les elisions et les mots trop courants."""
    propre = "".join(c if c.isalnum() or c.isspace() else " " for c in question)
    gardes = []
    for mot in propre.split():
        # « l'Etincelle » a deja perdu son apostrophe : on jette le « l ».
        if len(mot) < 4:
            continue
        if plier(mot) in VIDES:
            continue
        gardes.append(mot)
    return " ".join(gardes)


class AssistantMJ:
    def __init__(
        self,
        index: Index,
        modele: Modele,
        mode_joueurs: bool = False,
        contexte_max: int = CONTEXTE_MAX,
    ):
        self.index = index
        self.modele = modele
        self.mode_joueurs = mode_joueurs
        self.contexte_max = max(2000, int(contexte_max))
        self.pages_lues: list[str] = []
        self.coffre_entier = False

    # ---------------------------------------------------------------- contexte

    def pages_visibles(self) -> list[Page]:
        self.index.rafraichir()
        pages = list(self.index.pages.values())
        if self.mode_joueurs:
            pages = [p for p in pages if not p.reserve_mj]
        return pages

    def page_autorisee(self, nom: str) -> Page | None:
        page = self.index.page(nom) or self.index.resoudre(nom)
        if page is None:
            return None
        if self.mode_joueurs and page.reserve_mj:
            return None
        return page

    def texte_de_page(self, page: Page) -> str:
        corps = page.corps
        if self.mode_joueurs:
            corps = rendu.retirer_secrets(corps)
        entete = ["# " + page.titre, "", "Chemin : " + page.chemin]
        if page.type:
            entete.append("Type : " + page.type)
        if page.statut:
            entete.append("Statut : " + page.statut)
        entete.append("Visibilite : " + page.visibilite)
        if page.alias:
            entete.append("Alias : " + ", ".join(page.alias))
        entete.append("Lien a citer : " + url_de_page(page.chemin))
        bloc = "\n".join(entete) + "\n\n" + corps.strip()
        if len(bloc) > LIMITE_CARACTERES_OUTIL:
            bloc = bloc[:LIMITE_CARACTERES_OUTIL] + "\n\n[page tronquee]"
        return bloc

    def systeme(self, epingles: list[str]) -> str:
        morceaux: list[str] = []

        instructions = self.index.instructions()
        morceaux.append((instructions or INSTRUCTIONS_GENERIQUES).strip())
        # La consigne depend de ce que le modele sait faire : lui parler d'un
        # outil qu'il n'a pas le pousse a annoncer une lecture impossible.
        supplement = (
            CONSIGNE_OUTILS if self.modele.outils_natifs else CONSIGNE_SANS_OUTILS
        )
        morceaux.append(CONSIGNE_CITATION.strip() + "\n" + supplement.strip())
        if self.mode_joueurs:
            morceaux.append(CONSIGNE_MODE_JOUEURS.strip())

        entete_index = (
            "Chaque ligne est une page consultable avec `lire_page`."
            if self.modele.outils_natifs
            else "La liste de ce qui existe dans le coffre, pour situer et pour "
            "citer. Le contenu des pages utiles t'est donne avec la question."
        )
        morceaux.append(
            "# Index du coffre\n\n"
            + entete_index
            + "\n\n"
            + self.index.liste_pour_modele(self.mode_joueurs)
        )

        blocs_epingles = []
        for chemin in epingles:
            page = self.page_autorisee(chemin)
            if page is not None:
                blocs_epingles.append(self.texte_de_page(page))
                self.pages_lues.append(page.chemin)
        if blocs_epingles:
            morceaux.append(
                "# Pages epinglees par le MJ\n\nElles sont toujours fournies, en "
                "entier.\n\n" + "\n\n---\n\n".join(blocs_epingles)
            )
        return "\n\n---\n\n".join(morceaux)

    # ------------------------------------------------------------------ outils

    def executer(self, nom: str, entree: dict) -> str:
        if nom == "lire_page":
            demande = str(entree.get("page") or "").strip()
            if not demande:
                return "Aucune page demandee."
            page = self.page_autorisee(demande)
            if page is None:
                existe = self.index.page(demande) or self.index.resoudre(demande)
                if existe is not None and self.mode_joueurs:
                    return (
                        "Page '%s' reservee au MJ : indisponible en mode joueurs."
                        % demande
                    )
                proches = self._suggerer(demande)
                message = "Aucune page nommee '%s' dans le coffre." % demande
                if proches:
                    message += " Pages proches : " + ", ".join(proches) + "."
                return message
            self.pages_lues.append(page.chemin)
            return self.texte_de_page(page)

        if nom == "chercher":
            requete = str(entree.get("requete") or "").strip()
            if not requete:
                return "Aucun terme de recherche."
            resultats = self.index.chercher(
                requete,
                type_=str(entree.get("type") or ""),
                mode_joueurs=self.mode_joueurs,
                limite=15,
            )
            if not resultats:
                return "Aucun resultat pour '%s'." % requete
            lignes = ["%d page(s) trouvee(s) pour '%s' :" % (len(resultats), requete), ""]
            for item in resultats:
                lignes.append("- %s (%s)" % (item["titre"], item["chemin"]))
                for extrait in item["extraits"]:
                    lignes.append("    l.%d : %s" % (extrait["ligne"], extrait["texte"]))
            return "\n".join(lignes)

        return "Outil inconnu : %s" % nom

    def _suggerer(self, demande: str, maximum: int = 5) -> list[str]:
        cible = plier(demande)
        mots = [m for m in cible.split() if len(m) > 2]
        trouves = []
        for page in self.pages_visibles():
            champ = plier(page.titre + " " + page.nom + " " + page.chemin)
            if cible and cible in champ:
                trouves.append(page.chemin)
            elif mots and any(m in champ for m in mots):
                trouves.append(page.chemin)
        return sorted(set(trouves))[:maximum]

    # ----------------------------------------------------------- conversation

    def pages_evoquees(self, question: str) -> list[Page]:
        """Les pages a fournir d'office a un modele qui n'a pas d'outils.

        D'abord celles dont le titre, le nom ou un alias apparait tel quel dans
        la question : c'est le cas sur. On complete ensuite par la recherche
        plein texte, sinon une question qui dit « l'Etincelle » ne trouverait
        pas la page « Etincelle et Percee », et le modele repondrait sans
        source.
        """
        plie = plier(question)
        trouvees: list[tuple[int, Page]] = []
        retenues: set[str] = set()

        for page in self.pages_visibles():
            noms = {page.titre, page.nom} | set(page.alias)
            for nom in noms:
                aplati = plier(nom)
                if len(aplati) >= 4 and aplati in plie:
                    trouvees.append((len(aplati), page))
                    retenues.add(page.chemin)
                    break
        trouvees.sort(key=lambda t: -t[0])
        pages = [page for _, page in trouvees[:LIMITE_PAGES_AUTO]]

        if len(pages) < LIMITE_PAGES_AUTO:
            for item in self.index.chercher(
                _mots_utiles(question),
                mode_joueurs=self.mode_joueurs,
                limite=LIMITE_PAGES_AUTO * 2,
                tous_les_termes=False,
            ):
                if len(pages) >= LIMITE_PAGES_AUTO:
                    break
                if item["chemin"] in retenues:
                    continue
                page = self.index.page(item["chemin"])
                if page is not None:
                    pages.append(page)
                    retenues.add(page.chemin)
        return pages

    def pages_a_fournir(self, question: str, deja: set[str]) -> list[Page]:
        """Les pages envoyees d'office a un modele sans outils.

        Le classement ne sert plus a choisir une poignee de pages, mais a les
        ordonner : on en met autant que le budget le permet, les plus utiles
        d'abord. Sur un coffre de la taille de Recursion, tout passe, ce qui
        supprime le risque qu'il manque justement la bonne page.
        """
        ordre: list[Page] = []
        vues: set[str] = set(deja)

        def ajouter(page: Page | None) -> None:
            if page is not None and page.chemin not in vues:
                vues.add(page.chemin)
                ordre.append(page)

        # 1. Les pages nommees dans la question.
        for page in self.pages_evoquees(question):
            ajouter(page)
        # 2. Les meilleurs resultats de la recherche plein texte.
        for item in self.index.chercher(
            _mots_utiles(question),
            mode_joueurs=self.mode_joueurs,
            limite=200,
            tous_les_termes=False,
        ):
            ajouter(self.index.page(item["chemin"]))
        # 3. Le reste du coffre, pour qu'aucune page ne manque si elle tient.
        for page in sorted(self.pages_visibles(), key=lambda p: plier(p.chemin)):
            ajouter(page)

        retenues: list[Page] = []
        taille = 0
        for page in ordre:
            cout = len(page.corps) + 300  # l'en-tete ajoute par texte_de_page
            if retenues and taille + cout > self.contexte_max:
                continue
            retenues.append(page)
            taille += cout

        visibles = len(self.pages_visibles())
        self.coffre_entier = len(retenues) + len(deja) >= visibles
        return retenues

    def repondre(
        self,
        question: str,
        historique: list[dict],
        epingles: list[str],
    ) -> Iterator[dict]:
        """Conduit un tour de conversation et emet les evenements du modele."""
        self.pages_lues = []
        systeme = self.systeme(epingles)

        messages = [
            {"role": m["role"], "content": m["contenu"]}
            for m in historique
            if m.get("role") in ("user", "assistant") and str(m.get("contenu") or "").strip()
        ]

        if self.modele.outils_natifs:
            messages.append({"role": "user", "content": question})
            outils = OUTILS
        else:
            # Variante sans outils : le modele ne peut rien demander, on lui
            # fournit donc les pages d'avance, autant que le budget permet.
            pages = self.pages_a_fournir(question, set(self.pages_lues))
            contexte = ""
            if pages:
                self.pages_lues += [p.chemin for p in pages]
                entete = (
                    "Voici l'integralite du coffre, page par page. Tout ce dont tu "
                    "as besoin est ici : reponds sans demander quoi que ce soit."
                    if self.coffre_entier
                    else "Pages du coffre les plus liees a la question, en entier. "
                    "Tu ne peux pas en demander d'autres."
                )
                contexte = (
                    entete
                    + "\n\n"
                    + "\n\n---\n\n".join(self.texte_de_page(p) for p in pages)
                    + "\n\n---\n\n"
                )
            messages.append({"role": "user", "content": contexte + "Question du MJ : " + question})
            outils = None

        for evenement in self.modele.repondre(systeme, messages, outils, self.executer):
            yield evenement

        # Les pages reellement consultees, pour les afficher sous la reponse.
        vues = list(dict.fromkeys(self.pages_lues))
        if vues:
            yield {
                "type": "sources",
                "pages": [
                    {"chemin": c, "titre": (self.index.page(c).titre if self.index.page(c) else c), "url": url_de_page(c)}
                    for c in vues
                ],
            }
