"""Essais de l'outil, sans reseau et sans cle d'API.

    py -m assistant.essais              sur un coffre temporaire fabrique ici
    py -m assistant.essais --coffre ... en plus, sur un vrai coffre

Le DESIGN demande explicitement deux verifications avant de s'en servir a la
table (risques 3 et 5) : que le mode joueurs ne laisse fuir aucun secret, et
que l'outil fonctionne sur un dossier de notes quelconque. C'est l'objet
principal de ce fichier.
"""

from __future__ import annotations

import json as _json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from . import rendu
from .assistant_mj import AssistantMJ, INSTRUCTIONS_GENERIQUES
from .coffre import HorsCoffre, Index
from .modele import Modele

PAGES_ESSAI = {
    "Accueil.md": "# Accueil\n\nUn lien vers [[Secrete]] et vers [[Rien du tout]].\n",
    "Publique.md": (
        "---\ntype: regle\nstatut: canon\nvisibilite: joueurs\naliases: [\"La Publique\"]\n---\n\n"
        "# Page publique\n\nUn **tableau** :\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        "> [!mj]- Reserve au MJ\n> MOT-SECRET-ENCADRE\n\n"
        "Fin de la page.\n"
    ),
    "Secrete.md": (
        "---\ntype: pnj\nvisibilite: mj\n---\n\n"
        "# Page secrete\n\nMOT-SECRET-DE-PAGE\n"
    ),
    "Dossier/Imbriquee.md": "# Imbriquee\n\n- un point\n- un autre\n",
}


class ModeleMuet(Modele):
    """Capte ce qui serait envoye au modele, sans rien appeler."""

    fournisseur = "muet"

    def __init__(self, outils=True):
        super().__init__("muet")
        self._outils = outils
        self.systeme = None
        self.messages = None

    @property
    def outils_natifs(self):
        return self._outils

    def repondre(self, systeme, messages, outils=None, executer=None):
        self.systeme = systeme
        self.messages = messages
        yield {"type": "texte", "texte": "ok"}
        yield {"type": "fin", "usage": {}}


class Rapport:
    def __init__(self):
        self.ok = 0
        self.echecs: list[str] = []

    def verifie(self, intitule: str, condition, detail: str = "") -> None:
        if condition:
            self.ok += 1
            print("  ok   %s" % intitule)
        else:
            self.echecs.append(intitule + ((" — " + detail) if detail else ""))
            print("  ECHEC %s %s" % (intitule, detail))


def fabriquer_coffre(dossier: Path) -> None:
    for nom, contenu in PAGES_ESSAI.items():
        cible = dossier / nom
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(contenu, encoding="utf-8")


def essais_sur(racine: Path, r: Rapport, temporaire: bool) -> None:
    idx = Index(racine)
    idx.rafraichir()
    print("\n== coffre : %s (%d pages) ==" % (racine, len(idx.pages)))
    r.verifie("le coffre est lu", len(idx.pages) > 0)

    # -------------------------------------------------- liens et resolution
    def resoudre(nom):
        page = idx.resoudre(nom)
        return ("/page/" + page.chemin, True) if page else None

    accueil = idx.accueil()
    r.verifie("une page d'accueil est choisie", accueil is not None)

    if temporaire:
        r.verifie("resolution par le nom de fichier", idx.resoudre("Secrete") is not None)
        r.verifie("resolution par un alias", idx.resoudre("La Publique") is not None)
        r.verifie("resolution sans accent ni casse", idx.resoudre("page publique") is not None)
        r.verifie("un lien inexistant n'est pas resolu", idx.resoudre("Rien du tout") is None)

        page = idx.page("Accueil")
        sortie = rendu.rendre(page.corps, resoudre)
        r.verifie("les liens casses sont signales", sortie.liens_casses == ["Rien du tout"],
                  str(sortie.liens_casses))
        r.verifie("les liens valides deviennent des liens", 'class="lien-interne"' in sortie.html)

        publique = idx.page("Publique")
        vue_mj = rendu.rendre(publique.corps, resoudre, mode_joueurs=False)
        r.verifie("les tableaux sont rendus", "<table>" in vue_mj.html)

        # Un `|` qui appartient a un lien ne doit pas couper la cellule.
        r.verifie(
            "un lien [[A|B]] dans un tableau ne casse pas les cellules",
            rendu._cellules("| Les machines | [[Erosion|Erosion]] puis [[Echos|Echos]] |")
            == ["Les machines", "[[Erosion|Erosion]] puis [[Echos|Echos]]"],
        )
        r.verifie(
            "une barre echappee reste dans la cellule",
            rendu._cellules("| a \\| b | c |") == ["a | b", "c"],
        )
        r.verifie(
            "une barre dans du code en ligne ne separe pas",
            rendu._cellules("| `x | y` | z |") == ["`x | y`", "z"],
        )
        r.verifie("le gras est rendu", "<strong>" in vue_mj.html)
        r.verifie("l'arborescence reelle est reprise",
                  [d["nom"] for d in idx.arbre()["dossiers"]] == ["Dossier"])

    # ------------------------------------------------ protection des secrets
    print("\n  -- mode joueurs (DESIGN, risque 3) --")

    # 1. Une page reservee au MJ ne doit jamais etre rendue en mode joueurs.
    pages_mj = [p for p in idx.pages.values() if p.reserve_mj]
    r.verifie("des pages reservees au MJ existent dans ce coffre", bool(pages_mj),
              "aucune page `visibilite: mj` : ce test ne prouve rien ici")

    # 2. Les encadres MJ disparaissent du HTML et du texte envoye au modele.
    fuites_html, fuites_texte, encadres_vus = [], [], 0
    for page in idx.pages.values():
        avec = rendu.rendre(page.corps, resoudre, mode_joueurs=False)
        sans = rendu.rendre(page.corps, resoudre, mode_joueurs=True)
        if avec.secrets:
            encadres_vus += avec.secrets
            if "encadre-secret" in sans.html:
                fuites_html.append(page.chemin)
            if "[!mj]" in rendu.retirer_secrets(page.corps):
                fuites_texte.append(page.chemin)
    r.verifie("des encadres MJ existent dans ce coffre", encadres_vus > 0,
              "aucun encadre `> [!mj]` : ce test ne prouve rien ici")
    r.verifie("aucun encadre MJ dans le HTML en mode joueurs", not fuites_html, str(fuites_html))
    r.verifie("aucun encadre MJ dans le texte envoye au modele", not fuites_texte, str(fuites_texte))

    # 3. L'arborescence et la recherche filtrent les pages MJ.
    def toutes(noeud):
        liste = list(noeud["pages"])
        for sous in noeud["dossiers"]:
            liste += toutes(sous)
        return liste

    visibles = toutes(idx.arbre(mode_joueurs=True))
    r.verifie("l'arborescence ne montre aucune page MJ",
              all(not p["reserve_mj"] for p in visibles))
    resultats = idx.chercher("e", mode_joueurs=True)
    r.verifie("la recherche ne renvoie aucune page MJ",
              all(not x["reserve_mj"] for x in resultats))

    # 4. L'assistant lui-meme perd l'acces aux pages MJ.
    muet = ModeleMuet()
    assistant = AssistantMJ(idx, muet, mode_joueurs=True)
    epingles = [p.chemin for p in pages_mj[:1]]
    list(assistant.repondre("question", [], epingles))
    contexte = muet.systeme or ""
    r.verifie("le contexte annonce le mode joueurs", "Mode joueurs actif" in contexte)
    r.verifie("l'index envoye ne contient aucune page MJ",
              "visibilite : mj" not in contexte.split("# Index du coffre", 1)[-1])
    r.verifie("une page MJ epinglee n'est pas envoyee",
              "Pages epinglees" not in contexte)
    if pages_mj:
        refus = assistant.executer("lire_page", {"page": pages_mj[0].chemin})
        r.verifie("l'outil refuse de lire une page MJ", "reservee au MJ" in refus, refus[:80])
    if temporaire:
        r.verifie("aucun secret de page dans le contexte", "MOT-SECRET-DE-PAGE" not in contexte)
        r.verifie("aucun secret d'encadre dans le contexte", "MOT-SECRET-ENCADRE" not in contexte)

    # ------------------------------------------------- contexte en mode MJ
    print("\n  -- contexte en mode MJ --")
    muet_mj = ModeleMuet()
    mj = AssistantMJ(idx, muet_mj, mode_joueurs=False)
    cible = (pages_mj or list(idx.pages.values()))[0].chemin
    evenements = list(mj.repondre("question", [], [cible]))
    contexte_mj = muet_mj.systeme or ""
    r.verifie("l'index du coffre est envoye", "# Index du coffre" in contexte_mj)
    r.verifie("la consigne de citation est envoyee",
              "Citer tes sources dans cet outil" in contexte_mj)
    r.verifie("une page epinglee est envoyee en entier",
              "Pages epinglees par le MJ" in contexte_mj)
    r.verifie("les sources sont rapportees",
              any(e["type"] == "sources" for e in evenements))
    attendu = INSTRUCTIONS_GENERIQUES.strip()[:40]
    if idx.instructions() is None:
        r.verifie("instructions generiques faute de CLAUDE.md", attendu in contexte_mj)
    else:
        r.verifie("le CLAUDE.md du coffre sert d'instructions",
                  attendu not in contexte_mj)

    # ------------------------------------------------------------ les outils
    print("\n  -- outils de l'assistant --")
    page_test = idx.page(cible)
    r.verifie("lire_page cite l'URL de la page",
              "/page/" in mj.executer("lire_page", {"page": cible}))
    r.verifie("lire_page signale une page inexistante",
              "Aucune page" in mj.executer("lire_page", {"page": "Zzz Inexistant Zzz"}))
    r.verifie("chercher renvoie des resultats",
              "page(s) trouvee(s)" in mj.executer("chercher", {"requete": page_test.titre}))

    # --------------------------------------------------------- lecture a chaud
    if temporaire:
        print("\n  -- lecture a chaud --")
        nouvelle = racine / "Ajoutee a chaud.md"
        nouvelle.write_text("# Ajoutee\n\nxylophone\n", encoding="utf-8")
        idx.rafraichir()
        r.verifie("une page ajoutee apparait sans redemarrage",
                  "Ajoutee a chaud" in idx.pages)
        r.verifie("elle est immediatement cherchable",
                  [x["chemin"] for x in idx.chercher("xylophone")] == ["Ajoutee a chaud"])
        nouvelle.unlink()
        idx.rafraichir()
        r.verifie("une page supprimee disparait", "Ajoutee a chaud" not in idx.pages)

    # ------------------------------------- consignes selon le modele
    print("\n  -- consignes adaptees au modele --")

    class _Sans(Modele):
        outils_natifs = property(lambda self: False)

    class _Avec(Modele):
        outils_natifs = property(lambda self: True)

    question = "Un personnage peut-il se lier a plusieurs machines ?"
    sans = AssistantMJ(idx, _Sans("x"), False)
    contexte_sans = sans.systeme([])
    # Le CLAUDE.md du coffre ne nous appartient pas : on verifie ce qu'on ajoute.
    ajoute = contexte_sans.split("# Citer tes sources", 1)[-1]
    r.verifie(
        "un modele sans outils ne s'entend jamais parler d'outils",
        "lire_page" not in ajoute,
        "il annoncerait une lecture impossible, puis s'arreterait",
    )
    r.verifie(
        "il lui est dit de ne pas annoncer de consultation",
        "N'annonce jamais que tu vas consulter" in contexte_sans,
    )
    avec = AssistantMJ(idx, _Avec("x"), False)
    contexte_avec = avec.systeme([])
    r.verifie("un modele avec outils garde la consigne lire_page",
              "lire_page" in contexte_avec)
    r.verifie("et pas la consigne inverse",
              "N'annonce jamais que tu vas consulter" not in contexte_avec)

    # -------------------------------------- pages fournies sans outils
    print("\n  -- pages fournies a un modele sans outils --")
    visibles = len(sans.pages_visibles())
    fournies = sans.pages_a_fournir(question, set())
    r.verifie("tout le coffre est fourni quand il tient dans le budget",
              sans.coffre_entier and len(fournies) == visibles,
              "%d page(s) sur %d" % (len(fournies), visibles))

    serre = AssistantMJ(idx, _Sans("x"), False, contexte_max=12000)
    limitees = serre.pages_a_fournir(question, set())
    poids = sum(len(p.corps) for p in limitees)
    r.verifie("un budget serre est respecte", poids <= 12000 + 3000, "%d caracteres" % poids)
    r.verifie("et il reste au moins une page", len(limitees) >= 1)

    deja = {fournies[0].chemin} if fournies else set()
    r.verifie("une page deja epinglee n'est pas envoyee deux fois",
              all(p.chemin not in deja for p in sans.pages_a_fournir(question, deja)))

    if pages_mj:
        joueurs = AssistantMJ(idx, _Sans("x"), True)
        r.verifie("en mode joueurs, aucune page MJ n'est fournie d'office",
                  all(not p.reserve_mj for p in joueurs.pages_a_fournir(question, set())))

    # ------------------------------------------- rendu complet du coffre
    print("\n  -- rendu de toutes les pages --")
    import re as _re

    brutes, liens = [], 0
    for page in idx.pages.values():
        html = rendu.rendre(page.corps, resoudre).html
        liens += html.count('class="lien-interne"')
        # Entre backticks, `[[...]]` est du code : il doit rester litteral.
        hors_code = _re.sub(r"<code>.*?</code>", "", html, flags=_re.S)
        if "[[" in hors_code or "]]" in hors_code:
            brutes.append(page.chemin)
    r.verifie(
        "aucun lien [[...]] laisse en clair dans le HTML",
        not brutes,
        "pages concernees : " + ", ".join(brutes[:5]),
    )
    r.verifie("des liens ont bien ete rendus", liens > 0, "%d liens" % liens)

    # ------------------------------------------------------------- etancheite
    print("\n  -- etancheite du coffre --")
    try:
        idx.fichier_sur(os.path.join("..", "..", "ailleurs.txt"))
        r.verifie("un chemin sortant du coffre est refuse", False, "il a ete accepte")
    except HorsCoffre:
        r.verifie("un chemin sortant du coffre est refuse", True)


def essais_interface(r: Rapport) -> None:
    """Garde-fou sur la feuille de style.

    `.amorce` et `.app` portent un `display`, qui ecrase le `display: none`
    de l'attribut `hidden` si rien ne l'en empeche : la carte de demarrage
    reste alors affichee par-dessus l'application, qui semble ne rien faire.
    Un essai Python ne peut pas peindre la page, mais il peut verifier que la
    regle qui protege de ce cas est bien la.
    """
    print("\n== interface ==")
    statique = Path(__file__).parent / "static"
    css = (statique / "style.css").read_text(encoding="utf-8")
    r.verifie(
        "l'attribut `hidden` l'emporte sur les `display` de la feuille de style",
        "[hidden]" in css and "display: none !important" in css,
        "sans cette regle, la carte de demarrage masque l'application",
    )
    html = (statique / "index.html").read_text(encoding="utf-8")
    for fichier in ("style.css", "app.js", "carte.js", "favicon.svg"):
        r.verifie("%s est present" % fichier, (statique / fichier).is_file())
    r.verifie("la page appelle la feuille de style", "/static/style.css" in html)
    r.verifie("la page appelle le script", "/static/app.js" in html)
    r.verifie("la page appelle la carte avant le script",
              0 <= html.find("/static/carte.js") < html.find("/static/app.js"))

    # Les controles de la barre du haut : les selecteurs portent un libelle
    # au-dessus, pas les boutons. Centrer la rangee les desaligne ; il faut
    # aligner sur le bas et leur donner la meme hauteur.
    r.verifie(
        "la barre du haut aligne ses controles sur le bas",
        "align-items: flex-end" in css.split(".barre-actions", 1)[-1][:120],
        "sans cela, les boutons flottent au-dessus des selects",
    )
    r.verifie(
        "selects et boutons de la barre partagent une hauteur",
        "--hauteur-controle" in css
        and css.count("height: var(--hauteur-controle)") >= 2,
    )

    # La page de parametres : ses champs doivent exister et etre cables.
    js = (statique / "app.js").read_text(encoding="utf-8")
    for champ in ("p-url", "p-modele-ollama", "p-modele-claude", "p-effort", "p-tester"):
        r.verifie("le champ %s existe dans la page" % champ, 'id="%s"' % champ in html)
        r.verifie("le champ %s est lu par le script" % champ, "#" + champ in js)
    r.verifie(
        "la cle d'API ne se saisit pas dans la page",
        "ANTHROPIC_API_KEY" in html and 'type="password"' not in html,
        "aucun champ de saisie ne doit demander la cle",
    )


def essais_parametres(r: Rapport) -> None:
    """Les reglages du modele, tels que la page de parametres les envoie."""
    print("\n== parametres du modele ==")
    from .config import Config
    from .serveur import Application

    cfg = Config()
    app = Application(cfg)

    def regler(**champs):
        """Imite POST /api/modele sans passer par le reseau."""
        erreurs = []
        if champs.get("ollama_url"):
            url = champs["ollama_url"].strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                erreurs.append("url")
            else:
                cfg.ollama_url = url
        if champs.get("effort"):
            if champs["effort"] not in ("low", "medium", "high", "xhigh", "max"):
                erreurs.append("effort")
            else:
                cfg.effort = champs["effort"]
        if champs.get("modele_ollama"):
            cfg.modele_ollama = champs["modele_ollama"]
        if champs.get("modele_claude"):
            cfg.modele_claude = champs["modele_claude"]
        return erreurs

    r.verifie("une URL http est acceptee",
              regler(ollama_url="http://192.168.1.10:11434") == []
              and cfg.ollama_url == "http://192.168.1.10:11434")
    r.verifie("la barre finale est retiree de l'URL",
              regler(ollama_url="http://localhost:11434/") == []
              and cfg.ollama_url == "http://localhost:11434")
    r.verifie("une URL sans schema est refusee", regler(ollama_url="localhost:11434") == ["url"])
    r.verifie("un effort inconnu est refuse", regler(effort="enorme") == ["effort"])
    r.verifie("un effort connu est accepte",
              regler(effort="xhigh") == [] and cfg.effort == "xhigh")

    # Un nom de modele Ollama contient un deux-points : il doit survivre
    # a l'aller-retour par le fichier de configuration.
    regler(modele_ollama="llama3.1:8b", modele_claude="claude-opus-5-5")
    r.verifie("un nom de modele a deux-points est conserve",
              cfg.modele_ollama == "llama3.1:8b")

    # Changer de fournisseur ne doit pas effacer les reglages de l'autre.
    cfg.fournisseur = "claude"
    r.verifie("les reglages Ollama survivent au passage a Claude",
              cfg.modele_ollama == "llama3.1:8b" and cfg.ollama_url == "http://localhost:11434")

    r.verifie("l'etat ne divulgue jamais la cle d'API",
              _sans_cle(app.etat_complet()),
              "une valeur ressemblant a une cle a ete trouvee dans /api/etat")


CARTE_ESSAI = {
    "Carte.md": (
        "---\ntype: carte\nvisibilite: joueurs\n---\n\n# Ma carte\n\n"
        "Un tableau ordinaire, qui n'est pas une carte :\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        "| Lieu | Dans | Forme | Orbite | Angle | Taille | Relie | Note |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| Le centre |  | etoile | 0 |  | 5 |  | Au milieu. |\n"
        "| [[Publique\\|Planete]] | Le centre | planete | 10 | 0 | 1 | Cachee |  |\n"
        "| Lune | Planete | lune | 2 | 90 | 0.3 |  |  |\n"
        "| [[Secrete\\|Cachee]] | Le centre | ruche | 20 | 180 |  |  |  |\n"
        "| Sous-lieu | Cachee | lieu | 1 |  |  |  |  |\n"
        "| Orphelin | Nulle part | lieu | 3 |  |  |  |  |\n\n"
        "> [!mj]- Reserve au MJ\n"
        "> | Lieu | Dans | Forme | Orbite | Relie |\n"
        "> | --- | --- | --- | --- | --- |\n"
        "> | Repaire MOT-SECRET-CARTE | Planete | station | 0.5 | Lune |\n"
    ),
    "Publique.md": "---\nvisibilite: joueurs\n---\n\n# Publique\n\nUne page que les joueurs peuvent lire, assez longue pour servir de note.\n",
    "Secrete.md": "---\nvisibilite: mj\n---\n\n# Secrete\n\nMOT-SECRET-DE-PAGE.\n",
}


def essais_carte(r: Rapport) -> None:
    """Les cartes : lecture des tableaux, placement, et secrets en mode joueurs."""
    print("\n== carte ==")
    from . import carte

    dossier = Path(tempfile.mkdtemp(prefix="essai-carte-"))
    try:
        for nom, contenu in CARTE_ESSAI.items():
            (dossier / nom).write_text(contenu, encoding="utf-8")
        idx = Index(dossier)
        page = idx.page("Carte")
        r.verifie("une page `type: carte` est reconnue", carte.est_carte(page))
        r.verifie("la liste des cartes la contient", [c.chemin for c in carte.cartes(idx)] == ["Carte"])

        mj = carte.construire(idx, page, mode_joueurs=False)
        par_nom = {n["nom"]: n for n in mj["noeuds"]}
        r.verifie("seuls les tableaux a colonne Lieu sont lus", "1" not in par_nom, str(list(par_nom)))
        r.verifie("les lieux des encadres sont lus en vue MJ", "Repaire MOT-SECRET-CARTE" in par_nom)
        r.verifie("un lien [[A\\|B]] donne nom et page",
                  par_nom["Planete"]["page"] == "Publique", str(par_nom.get("Planete")))
        r.verifie("le parent se designe par son nom affiche",
                  par_nom["Lune"]["parent"] == par_nom["Planete"]["id"])
        r.verifie("la position est relative au parent (angle 0 = a droite)",
                  abs(par_nom["Planete"]["x"] - 10) < 1e-6 and abs(par_nom["Planete"]["y"]) < 1e-6)
        r.verifie("90 degres = vers le haut",
                  abs(par_nom["Lune"]["x"] - 10) < 1e-6 and abs(par_nom["Lune"]["y"] + 2) < 1e-6)
        r.verifie("la portee couvre les enfants", par_nom["Planete"]["portee"] >= 2.3)
        r.verifie("sans note, le debut de la page sert de note",
                  par_nom["Planete"]["note"].startswith("Une page que les joueurs"))
        r.verifie("un lieu d'encadre MJ est marque secret", par_nom["Repaire MOT-SECRET-CARTE"]["secret"])
        r.verifie("un lieu dont la page est MJ est marque secret", par_nom["Cachee"]["secret"])
        r.verifie("un parent inconnu est signale", any("Nulle part" in e for e in mj["erreurs"]))
        r.verifie("les fils sont lus", len(mj["fils"]) == 2, str(mj["fils"]))

        joueurs = carte.construire(idx, page, mode_joueurs=True)
        texte = _json.dumps(joueurs, ensure_ascii=False)
        noms = {n["nom"] for n in joueurs["noeuds"]}
        r.verifie("mode joueurs : aucun lieu d'encadre MJ", "MOT-SECRET-CARTE" not in texte)
        r.verifie("mode joueurs : aucun lieu dont la page est MJ",
                  "Cachee" not in noms and "Secrete" not in texte, str(noms))
        r.verifie("mode joueurs : les descendants d'un secret disparaissent", "Sous-lieu" not in noms)
        r.verifie("mode joueurs : aucun fil vers un secret", joueurs["fils"] == [], str(joueurs["fils"]))
        r.verifie("mode joueurs : les erreurs ne sont pas envoyees", joueurs["erreurs"] == [])
        r.verifie("mode joueurs : les lieux publics restent", {"Le centre", "Planete", "Lune"} <= noms)

        r.verifie("une page publique est situee sur la carte",
                  (carte.situer(idx, "Publique") or {}).get("noeud") == par_nom["Planete"]["id"])
        r.verifie("une page MJ n'est pas situee en mode joueurs",
                  carte.situer(idx, "Secrete", mode_joueurs=True) is None)

        # Une carte reservee au MJ disparait de la liste en mode joueurs.
        (dossier / "Carte.md").write_text(
            CARTE_ESSAI["Carte.md"].replace("visibilite: joueurs", "visibilite: mj"), encoding="utf-8"
        )
        r.verifie("une carte MJ n'est pas listee en mode joueurs", carte.cartes(idx, mode_joueurs=True) == [])
    finally:
        shutil.rmtree(dossier, ignore_errors=True)


def _sans_cle(etat) -> bool:
    """Verifie qu'aucune valeur de l'etat ne ressemble a une cle d'API."""
    import json as _json

    texte = _json.dumps(etat, default=str)
    return "sk-ant" not in texte


def essais_secrets(r: Rapport) -> None:
    """Les cles d'API : lecture du .env, priorite, et non-divulgation.

    Le .env du projet n'est jamais ouvert ici : on en fabrique un, avec des
    valeurs factices.
    """
    print("\n== cles d'API ==")
    from . import config as cfgmod
    from .config import Config, lire_env, trouver_secret
    from .modele import ModeleOllama

    CLE_O = "cle-ollama-factice-ABC123"
    CLE_A = "sk-ant-factice-DEF456"

    dossier = Path(tempfile.mkdtemp(prefix="essai-env-"))
    anciennes = {
        nom: os.environ.pop(nom, None)
        for nom in cfgmod.NOMS_CLE_OLLAMA
        + cfgmod.NOMS_CLE_CLAUDE
        + ("ASSISTANT_ENV", "APPDATA", "LOCALAPPDATA")
    }
    try:
        (dossier / ".env").write_text(
            "# commentaire\n\n"
            "OLLAMA_API_KEY=%s\n"
            'export ANTHROPIC_API_KEY="%s"\n'
            "AVEC_COMMENTAIRE=valeur # ignore\n"
            "LIGNE_SANS_EGAL\n" % (CLE_O, CLE_A),
            encoding="utf-8",
        )
        valeurs = lire_env(dossier / ".env")
        r.verifie("le .env est analyse", valeurs.get("OLLAMA_API_KEY") == CLE_O)
        r.verifie("le prefixe export est accepte", valeurs.get("ANTHROPIC_API_KEY") == CLE_A)
        r.verifie("les guillemets sont retires", '"' not in (valeurs.get("ANTHROPIC_API_KEY") or '"'))
        r.verifie("un commentaire de fin de ligne est retire",
                  valeurs.get("AVEC_COMMENTAIRE") == "valeur")
        r.verifie("une ligne sans `=` est ignoree", "LIGNE_SANS_EGAL" not in valeurs)

        os.environ["ASSISTANT_ENV"] = str(dossier / ".env")
        os.environ["APPDATA"] = str(dossier / "faux-appdata")
        os.environ["LOCALAPPDATA"] = str(dossier / "faux-local")

        valeur, source = trouver_secret(cfgmod.NOMS_CLE_OLLAMA)
        r.verifie("la cle Ollama est trouvee dans le .env", valeur == CLE_O and ".env" in source)

        os.environ["OLLAMA_API_KEY"] = "venue-de-l-environnement"
        valeur, _ = trouver_secret(cfgmod.NOMS_CLE_OLLAMA)
        r.verifie("une variable d'environnement l'emporte sur le .env",
                  valeur == "venue-de-l-environnement")
        del os.environ["OLLAMA_API_KEY"]

        cfg = Config.charger([])
        r.verifie("la configuration charge la cle Ollama", cfg.cle_ollama == CLE_O)
        r.verifie("la configuration charge la cle Claude", cfg.cle_api == CLE_A)

        # Non-divulgation : ni par l'API, ni dans le fichier de configuration.
        from .serveur import Application

        etat = _json.dumps(Application(cfg).etat_complet(), default=str)
        r.verifie("aucune cle dans /api/etat", CLE_O not in etat and CLE_A not in etat)
        r.verifie("l'etat dit seulement que la cle existe",
                  '"presente": true' in etat.lower())
        cfg.ecrire()
        ecrit = cfgmod.fichier_config().read_text(encoding="utf-8")
        r.verifie("aucune cle recopiee dans config.toml",
                  CLE_O not in ecrit and CLE_A not in ecrit)

        # L'en-tete envoye a Ollama.
        avec = ModeleOllama("x", "http://127.0.0.1:1", CLE_O, delai=0.05)._entetes()
        sans = ModeleOllama("x", "http://127.0.0.1:1", None, delai=0.05)._entetes()
        r.verifie("la cle part en en-tete Bearer",
                  avec.get("Authorization") == "Bearer " + CLE_O)
        r.verifie("sans cle, aucun en-tete Authorization", "Authorization" not in sans)
    finally:
        for nom, valeur in anciennes.items():
            if valeur is None:
                os.environ.pop(nom, None)
            else:
                os.environ[nom] = valeur
        shutil.rmtree(dossier, ignore_errors=True)


def principal(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    r = Rapport()
    essais_interface(r)
    essais_parametres(r)
    essais_secrets(r)
    essais_carte(r)

    temporaire = Path(tempfile.mkdtemp(prefix="essai-coffre-"))
    try:
        fabriquer_coffre(temporaire)
        essais_sur(temporaire, r, temporaire=True)
    finally:
        shutil.rmtree(temporaire, ignore_errors=True)

    # Un vrai coffre, si on en donne un.
    for i, arg in enumerate(argv):
        if arg in ("--coffre", "-c") and i + 1 < len(argv):
            racine = Path(argv[i + 1]).expanduser().resolve()
            if racine.is_dir():
                essais_sur(racine, r, temporaire=False)
            else:
                print("\n(coffre introuvable : %s)" % racine)

    print("\n%d verification(s) passee(s), %d echec(s)." % (r.ok, len(r.echecs)))
    for echec in r.echecs:
        print("  - " + echec)
    return 1 if r.echecs else 0


if __name__ == "__main__":
    raise SystemExit(principal())
