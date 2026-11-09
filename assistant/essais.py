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


ECRITURE_ESSAI = {
    "Campagnes/_Modele/Campagne.md": (
        "---\ntype: campagne\nstatut: brouillon\n---\n\n# Campagne : (nom)\n\n"
        "## Les personnages joueurs\n\n- \n\n## Les seances\n\n| N | Resume |\n| --- | --- |\n"
    ),
    "Campagnes/Existante/Campagne.md": (
        "---\ntype: campagne\n---\r\n\r\n# Campagne existante\r\n\r\n"
        "**Groupe :** (joueurs)\r\n\r\n## Les personnages joueurs\r\n\r\n- [[Lea]]\r\n\r\n## Fin\r\n\r\nrien\r\n"
    ),
    "Modeles/Personnage.md": "---\ntype: modele\n---\n\n# Personnage\n\n**Joueur :** \n",
    "Notes/Vide.md": "# Vide\n",
    "Canon/Regle.md": "# Regle\n\nIntouchable.\n",
}


class ModeleBavard(ModeleMuet):
    """Un modele sans outils qui propose une page en bloc dans sa reponse."""

    def __init__(self, reponse: str):
        super().__init__(outils=False)
        self.reponse = reponse

    def repondre(self, systeme, messages, outils=None, executer=None):
        self.systeme = systeme
        yield {"type": "texte", "texte": self.reponse}
        yield {"type": "fin", "usage": {}}


def essais_ecriture(r: Rapport) -> None:
    """L'ecriture dans le coffre : seulement des propositions, validees, et bornees."""
    print("\n== ecriture dans le coffre ==")
    from .ecriture import Ecriture, EcritureRefusee, blocs_de

    dossier = Path(tempfile.mkdtemp(prefix="essai-ecriture-"))
    try:
        for nom, contenu in ECRITURE_ESSAI.items():
            cible = dossier / nom
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_bytes(contenu.encode("utf-8"))
        idx = Index(dossier)
        ec = Ecriture(idx, ["Campagnes", "Notes"])

        def refuse(fonction, *args) -> bool:
            try:
                fonction(*args)
            except EcritureRefusee:
                return True
            return False

        # --- les chemins
        r.verifie("hors des dossiers autorises : refuse", refuse(ec.preparer_creation, "Canon/Nouvelle", "x"))
        r.verifie("remonter avec .. : refuse", refuse(ec.preparer_creation, "Campagnes/../Canon/X", "x"))
        r.verifie("chemin absolu : refuse", refuse(ec.preparer_creation, "C:/Windows/X", "x"))
        r.verifie("dossier de modele (_) : refuse", refuse(ec.preparer_creation, "Campagnes/_Modele/Autre", "x"))
        r.verifie("caractere interdit : refuse", refuse(ec.preparer_creation, "Campagnes/A?B", "x"))
        r.verifie("le dossier autorise lui-meme n'est pas une page", refuse(ec.preparer_creation, "Campagnes", "x"))
        r.verifie("une page existante ne s'ecrase pas",
                  refuse(ec.preparer_creation, "Campagnes/Existante/Campagne", "x"))
        r.verifie("un modele ne se modifie pas", refuse(ec.preparer_modification, "Personnage", "", "x"))
        r.verifie("une page hors zone ne se modifie pas", refuse(ec.preparer_modification, "Regle", "", "x"))

        # --- une creation : rien n'est ecrit avant la validation
        prop = ec.preparer_creation("Campagnes/Les voleurs/Lea", "# Lea\n\nEveillee.", "Fiche de Lea")
        nouveau = dossier / "Campagnes" / "Les voleurs" / "Lea.md"
        r.verifie("une proposition n'ecrit rien", not nouveau.exists())
        chemin = ec.appliquer(prop)
        r.verifie("la validation cree la page et ses dossiers",
                  nouveau.is_file() and chemin == "Campagnes/Les voleurs/Lea")
        r.verifie("la page creee est relue a chaud", idx.page("Campagnes/Les voleurs/Lea") is not None)
        r.verifie("valider deux fois n'ecrase pas", refuse(ec.appliquer, prop))
        retouche = ec.preparer_creation("Notes/Retouche", "avant")
        ec.appliquer(retouche, "apres")
        r.verifie("le texte retouche par le MJ remplace la proposition",
                  (dossier / "Notes" / "Retouche.md").read_text(encoding="utf-8").strip() == "apres")

        # --- une page creee d'apres un modele n'est pas un modele
        copie = ec.preparer_creation(
            "Notes/Fiche",
            "---\ntype: modele\nmodele_de: pj\nstatut: modele\nvisibilite: mj\n---\n\n# Lea\n",
        )["contenu"]
        r.verifie("un `type: modele` recopie prend le type du modele (modele_de)",
                  "type: pj" in copie and "modele_de" not in copie and "type: modele" not in copie, copie)
        r.verifie("un `statut: modele` recopie devient brouillon", "statut: brouillon" in copie)
        r.verifie("les autres metadonnees et le corps restent",
                  "visibilite: mj" in copie and copie.endswith("# Lea\n"))
        intacte = ec.preparer_creation("Notes/Autre", "---\ntype: pnj\nstatut: canon\n---\n\n# X")["contenu"]
        r.verifie("une page qui n'est pas un modele est laissee telle quelle", "type: pnj\nstatut: canon" in intacte)

        # --- une modification
        existante = dossier / "Campagnes" / "Existante" / "Campagne.md"
        r.verifie("le passage a remplacer doit exister",
                  refuse(ec.preparer_modification, "Campagne existante", "absent", "x"))
        r.verifie("le passage a remplacer doit etre unique",
                  refuse(ec.preparer_modification, "Campagne existante", "\n", "x"))
        modif = ec.preparer_modification("Campagne existante", "**Groupe :** (joueurs)", "**Groupe :** Ana, Ben")
        r.verifie("une proposition de modification n'ecrit rien",
                  "(joueurs)" in existante.read_text(encoding="utf-8"))
        ec.appliquer(modif)
        brut = existante.read_bytes().decode("utf-8")
        r.verifie("la modification remplace le passage", "**Groupe :** Ana, Ben" in brut)
        r.verifie("les fins de ligne de la page sont gardees (CRLF)", "\r\n" in brut and "\n\n" not in brut.replace("\r\n", ""))
        ajout = ec.preparer_modification("Campagne existante", "", "- [[Ben]]", section="Les personnages joueurs")
        ec.appliquer(ajout)
        texte = existante.read_text(encoding="utf-8").replace("\r\n", "\n")
        r.verifie("un ajout se place a la fin de sa section",
                  "- [[Lea]]\n- [[Ben]]\n\n## Fin" in texte, repr(texte[-80:]))
        perime = ec.preparer_modification("Campagne existante", "rien", "tout")
        existante.write_text(texte.replace("rien", "modifie dans Obsidian"), encoding="utf-8")
        r.verifie("une page changee depuis la proposition n'est pas ecrasee", refuse(ec.appliquer, perime))

        # --- les blocs d'un modele sans outils
        reponse = (
            "Voici la fiche.\n\n```page chemin=\"Campagnes/Les voleurs/Ben\"\n# Ben\n\nMachine.\n```\n\n"
            "```ajout page=\"Vide\" section=\"\"\n- une ligne\n```\n\n"
            "```page chemin=\"Canon/Interdit\"\n# Non\n```\n"
        )
        r.verifie("les blocs de proposition sont reconnus", len(blocs_de(reponse)) == 3)
        gardees: list[dict] = []

        def proposer(p):
            gardees.append(p)
            return {**p, "id": str(len(gardees))}

        bavard = ModeleBavard(reponse)
        assistant = AssistantMJ(idx, bavard, False, ecriture=ec, proposer=proposer)
        evenements = list(assistant.repondre("cree Ben", [], []))
        types = [e["type"] for e in evenements]
        r.verifie("un modele sans outils recoit le format des blocs", "```page chemin=" in bavard.systeme)
        r.verifie("ses blocs deviennent des propositions", types.count("proposition") == 2, str(types))
        r.verifie("un bloc hors zone est refuse, avec la raison", types.count("proposition_refusee") == 1)
        r.verifie("et rien n'est ecrit", not (dossier / "Campagnes" / "Les voleurs" / "Ben.md").exists())

        # --- les outils (Claude), et le mode joueurs
        muet = ModeleMuet(outils=True)
        avec = AssistantMJ(idx, muet, False, ecriture=ec, proposer=proposer)
        list(avec.repondre("x", [], []))
        r.verifie("un modele a outils recoit la consigne des outils d'ecriture",
                  "proposer_page" in muet.systeme and "```page" not in muet.systeme)
        retour = avec.executer("proposer_page", {"chemin": "Notes/Par outil", "contenu": "# Ok", "resume": "r"})
        r.verifie("l'outil propose sans ecrire",
                  retour.startswith("Proposition prete") and not (dossier / "Notes" / "Par outil.md").exists())
        refus = avec.executer("proposer_page", {"chemin": "Canon/Non", "contenu": "# Non", "resume": ""})
        r.verifie("l'outil explique un refus au modele", refus.startswith("Proposition refusee"))

        muet_j = ModeleMuet(outils=True)
        joueurs = AssistantMJ(idx, muet_j, True, ecriture=ec, proposer=proposer)
        list(joueurs.repondre("x", [], []))
        r.verifie("mode joueurs : pas de consigne d'ecriture", "proposer_page" not in muet_j.systeme)
        r.verifie("mode joueurs : l'outil d'ecriture ne repond pas",
                  joueurs.executer("proposer_page", {"chemin": "Notes/J", "contenu": "x", "resume": ""})
                  .startswith("L'ecriture dans le coffre n'est pas disponible"))
    finally:
        shutil.rmtree(dossier, ignore_errors=True)


def essais_ollama(r: Rapport) -> None:
    """Les outils d'un modele Ollama, contre un faux serveur Ollama local."""
    print("\n== ollama : outils ==")
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from .modele import ModeleOllama, _arguments

    faux = {"capacites": ["completion", "tools"], "requetes": []}

    class FauxOllama(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _envoyer(self, corps: bytes, type_mime: str = "application/json") -> None:
            self.send_response(200)
            self.send_header("Content-Type", type_mime)
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def do_GET(self):
            self._envoyer(_json.dumps({"models": [{"name": "faux:1"}]}).encode())

        def do_POST(self):
            charge = _json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if self.path == "/api/show":
                return self._envoyer(_json.dumps({"capabilities": faux["capacites"]}).encode())
            faux["requetes"].append(charge)
            if any(m.get("role") == "tool" for m in charge["messages"]):
                lignes = [{"message": {"content": "Selon la page, "}},
                          {"message": {"content": "MOT-TEMOIN."}, "done": True}]
            elif charge.get("tools"):
                lignes = [{"message": {"content": "Je lis la page.", "tool_calls": [
                    {"function": {"name": "lire_page", "arguments": {"page": "Publique"}}}]}, "done": True}]
            else:
                lignes = [{"message": {"content": "sans outils"}, "done": True}]
            self._envoyer("\n".join(_json.dumps(l) for l in lignes).encode(), "application/x-ndjson")

    serveur = ThreadingHTTPServer(("127.0.0.1", 0), FauxOllama)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % serveur.server_address[1]
    dossier = Path(tempfile.mkdtemp(prefix="essai-ollama-"))
    try:
        r.verifie("la capacite `tools` est detectee", ModeleOllama("faux:1", url).outils_natifs)
        r.verifie("« outils = non » les retire", not ModeleOllama("faux:1", url, outils="non").outils_natifs)
        faux["capacites"] = ["completion"]
        r.verifie("sans la capacite, pas d'outils", not ModeleOllama("faux:1", url).outils_natifs)
        r.verifie("« outils = oui » les force", ModeleOllama("faux:1", url, outils="oui").outils_natifs)
        r.verifie("un modele injoignable n'a pas d'outils",
                  not ModeleOllama("faux:1", "http://127.0.0.1:9", delai=0.3).outils_natifs)
        r.verifie("des arguments en chaine JSON sont lus", _arguments('{"page": "X"}') == {"page": "X"})
        faux["capacites"] = ["completion", "tools"]

        fabriquer_coffre(dossier)
        idx = Index(dossier)
        assistant = AssistantMJ(idx, ModeleOllama("faux:1", url), False)
        evenements = list(assistant.repondre("Que dit la page publique ?", [], []))
        texte = "".join(e.get("texte", "") for e in evenements if e["type"] == "texte")
        premiere, seconde = faux["requetes"][0], faux["requetes"][1]
        noms = [o["function"]["name"] for o in premiere.get("tools", [])]
        r.verifie("les outils partent au format d'Ollama", "lire_page" in noms and "chercher" in noms, str(noms))
        r.verifie("le coffre n'est plus fourni d'avance",
                  "integralite du coffre" not in _json.dumps(premiere, ensure_ascii=False))
        r.verifie("l'appel d'outil est annonce a l'interface",
                  any(e["type"] == "outil" and e["nom"] == "lire_page" for e in evenements))
        retour = next((m for m in seconde["messages"] if m.get("role") == "tool"), {})
        r.verifie("le resultat de l'outil est renvoye au modele", "Page publique" in retour.get("content", ""))
        r.verifie("le modele repond apres l'outil, en un nouveau paragraphe",
                  texte == "Je lis la page.\n\nSelon la page, MOT-TEMOIN.", repr(texte))
        r.verifie("la page lue apparait dans les sources",
                  any(e["type"] == "sources" and e["pages"][0]["chemin"] == "Publique" for e in evenements))
    finally:
        serveur.shutdown()
        shutil.rmtree(dossier, ignore_errors=True)


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
    essais_ecriture(r)
    essais_ollama(r)

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
