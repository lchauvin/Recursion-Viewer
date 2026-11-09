"""Le serveur local : routes HTTP, rendu des pages, flux de conversation.

Tout tient dans une page. Les routes `/api/...` renvoient du JSON, sauf
`/api/conversation` qui renvoie un flux d'evenements (SSE).
"""

from __future__ import annotations

import json
import mimetypes
import threading
import traceback
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import carte as cartes
from . import modele as modeles
from .assistant_mj import AssistantMJ, url_de_page
from .coffre import CoffreIntrouvable, HorsCoffre, Index
from .ecriture import Ecriture, EcritureRefusee
from .config import NOMS_CLE_OLLAMA, Config
from .etat import Etats
from . import rendu

STATIQUE = Path(__file__).parent / "static"


class Application:
    """L'etat du serveur : configuration, index par coffre, modele courant."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.etats = Etats()
        self._index: dict[str, Index] = {}
        self._modele: modeles.Modele | None = None
        self._verrou = threading.Lock()

    # ----------------------------------------------------------------- coffre

    @property
    def coffre_courant(self):
        cle = self.cfg.coffre_par_defaut
        return self.cfg.coffres.get(cle) if cle else None

    def index(self) -> Index:
        coffre = self.coffre_courant
        if coffre is None:
            raise CoffreIntrouvable("aucun coffre configure")
        with self._verrou:
            if coffre.cle not in self._index:
                self._index[coffre.cle] = Index(coffre.chemin)
            index = self._index[coffre.cle]
        index.rafraichir()
        return index

    def etat(self):
        coffre = self.coffre_courant
        return self.etats.pour(coffre.cle if coffre else "aucun")

    def ecriture(self) -> Ecriture | None:
        """Ce que l'assistant peut ecrire dans le coffre courant, apres validation."""
        coffre = self.coffre_courant
        if coffre is None:
            return None
        return Ecriture(self.index(), coffre.zones_ecriture)

    def ecrire(self, corps: dict) -> dict:
        """Ecrit une proposition validee par le MJ, ou une note qu'il a composee."""
        coffre = self.coffre_courant
        if coffre is None:
            raise EcritureRefusee("Aucun coffre ouvert.")
        if self.etat().mode_joueurs:
            raise EcritureRefusee("Pas d'ecriture en mode joueurs.")
        ecriture = self.ecriture()
        contenu = corps.get("contenu")
        contenu = None if contenu is None else str(contenu)
        ident = str(corps.get("id") or "")
        if ident:
            proposition = self.etats.proposition(coffre.cle, ident)
            if proposition is None:
                raise EcritureRefusee("Cette proposition n'existe plus.")
            chemin = ecriture.appliquer(proposition, contenu)
            self.etats.retirer_proposition(coffre.cle, ident)
        else:
            # Une note composee par le MJ (« Enregistrer comme note »).
            proposition = ecriture.preparer_creation(str(corps.get("chemin") or ""), contenu or "")
            chemin = ecriture.appliquer(proposition)
        page = self.index().page(chemin)
        return {
            "ok": True,
            "chemin": chemin,
            "titre": page.titre if page else chemin,
            "url": url_de_page(chemin),
        }

    # ----------------------------------------------------------------- modele

    def modele(self) -> modeles.Modele:
        with self._verrou:
            attendu = (
                self.cfg.fournisseur,
                self.cfg.modele_claude if self.cfg.fournisseur == "claude" else self.cfg.modele_ollama,
            )
            courant = (
                (self._modele.fournisseur, self._modele.identifiant) if self._modele else None
            )
            if self._modele is None or courant != attendu:
                self._modele = modeles.construire(self.cfg)
            return self._modele

    def oublier_modele(self) -> None:
        with self._verrou:
            self._modele = None

    # ------------------------------------------------------------------ rendu

    def rendre_page(self, chemin: str) -> dict:
        index = self.index()
        etat = self.etat()
        page = index.page(chemin)
        if page is None:
            return {"erreur": "introuvable", "chemin": chemin}
        if etat.mode_joueurs and page.reserve_mj:
            return {
                "erreur": "reservee",
                "chemin": page.chemin,
                "titre": page.titre,
                "message": "Page reservee au MJ : masquee en mode joueurs.",
            }

        def resoudre(nom: str):
            cible = index.resoudre(nom)
            if cible is None:
                return None
            if etat.mode_joueurs and cible.reserve_mj:
                return None
            return (url_de_page(cible.chemin), True)

        resultat = rendu.rendre(page.corps, resoudre, etat.mode_joueurs)
        return {
            "chemin": page.chemin,
            "titre": page.titre,
            "meta": page.meta,
            "type": page.type,
            "statut": page.statut,
            "visibilite": page.visibilite,
            "alias": page.alias,
            "reserve_mj": page.reserve_mj,
            "html": resultat.html,
            "titres": [
                {"niveau": n, "texte": t, "ancre": a} for n, t, a in resultat.titres
            ],
            "liens_casses": resultat.liens_casses,
            "secrets": resultat.secrets,
            "epinglee": page.chemin in etat.epingles,
            "est_carte": cartes.est_carte(page),
            # La carte ou figure ce lieu, pour le bouton « Sur la carte ».
            "sur_carte": None
            if cartes.est_carte(page)
            else cartes.situer(index, page.chemin, etat.mode_joueurs),
        }

    def rendre_carte(self, chemin: str) -> dict:
        index = self.index()
        etat = self.etat()
        page = index.page(chemin)
        if page is None or not cartes.est_carte(page):
            return {"erreur": "introuvable", "chemin": chemin}
        if etat.mode_joueurs and page.reserve_mj:
            return {"erreur": "reservee", "message": "Carte reservee au MJ."}
        donnees = cartes.construire(index, page, etat.mode_joueurs)
        for noeud in donnees["noeuds"]:
            noeud["url"] = url_de_page(noeud["page"]) if noeud["page"] else None
        donnees["mode_joueurs"] = etat.mode_joueurs
        return donnees

    def etat_complet(self) -> dict:
        coffre = self.coffre_courant
        base = {
            "coffres": [
                {
                    "cle": c.cle,
                    "nom": c.nom,
                    "chemin": str(c.chemin),
                    "existe": c.existe,
                    "courant": coffre is not None and c.cle == coffre.cle,
                }
                for c in self.cfg.coffres.values()
            ],
            "modele": self.modele().decrire(),
            "modeles_claude": [
                "claude-opus-5-5",
                "claude-opus-5",
                "claude-sonnet-5-5",
                "claude-haiku-5-5",
            ],
            "efforts": ["low", "medium", "high", "xhigh", "max"],
            "effort": self.cfg.effort,
            "contexte_max": self.cfg.contexte_max,
            "modele_claude": self.cfg.modele_claude,
            "modele_ollama": self.cfg.modele_ollama,
            "ollama_url": self.cfg.ollama_url,
            # Jamais les cles elles-memes : seulement si elles existent, et
            # d'ou elles viennent.
            "cle_api": {
                "presente": bool(self.cfg.cle_api),
                "source": self.cfg.source_cle_api,
            },
            "cle_ollama": {
                "presente": bool(self.cfg.cle_ollama),
                "source": self.cfg.source_cle_ollama,
                "noms_reconnus": list(NOMS_CLE_OLLAMA),
            },
            "hote": self.cfg.hote,
            "port": self.cfg.port,
            "config": str(self.cfg.source) if self.cfg.source else None,
        }
        if coffre is None:
            base.update({"coffre": None, "pret": False})
            return base

        etat = self.etat()
        try:
            index = self.index()
        except CoffreIntrouvable:
            base.update(
                {
                    "coffre": {"cle": coffre.cle, "nom": coffre.nom, "chemin": str(coffre.chemin)},
                    "pret": False,
                    "erreur": "Le dossier %s n'existe pas." % coffre.chemin,
                }
            )
            return base

        epingles = []
        for chemin in etat.epingles:
            page = index.page(chemin)
            if page is None:
                continue
            if etat.mode_joueurs and page.reserve_mj:
                continue
            epingles.append({"chemin": page.chemin, "titre": page.titre, "url": url_de_page(page.chemin)})

        accueil = index.accueil()
        base.update(
            {
                "coffre": {
                    "cle": coffre.cle,
                    "nom": coffre.nom,
                    "chemin": str(coffre.chemin),
                    "pages": len(index.pages),
                    "instructions": index.instructions() is not None,
                },
                "pret": True,
                "mode_joueurs": etat.mode_joueurs,
                "epingles": epingles,
                "types": index.types(),
                "accueil": accueil.chemin if accueil else None,
                "cartes": [
                    {"chemin": c.chemin, "titre": c.titre}
                    for c in cartes.cartes(index, etat.mode_joueurs)
                ],
                "conversation": etat.conversation,
                # Les propositions peuvent contenir des secrets : jamais en mode joueurs.
                "ecriture": {
                    "active": not etat.mode_joueurs,
                    "dossiers": coffre.zones_ecriture,
                    "notes": coffre.dossier_notes,
                },
                "propositions": [] if etat.mode_joueurs else etat.propositions,
            }
        )
        return base

    # ----------------------------------------------------------- conversation

    def flux_conversation(self, question: str):
        """Generateur d'evenements pour une question du MJ."""
        coffre = self.coffre_courant
        if coffre is None:
            yield {"type": "erreur", "texte": "Aucun coffre ouvert."}
            return
        etat = self.etat()
        try:
            index = self.index()
        except CoffreIntrouvable as err:
            yield {"type": "erreur", "texte": "Coffre introuvable : %s" % err}
            return

        assistant = AssistantMJ(
            index,
            self.modele(),
            etat.mode_joueurs,
            self.cfg.contexte_max,
            ecriture=Ecriture(index, coffre.zones_ecriture),
            proposer=lambda proposition: self.etats.ajouter_proposition(coffre.cle, proposition),
        )
        historique = list(etat.conversation)
        self.etats.ajouter_message(coffre.cle, "user", question)

        reponse: list[str] = []
        echec = False
        differe: list[dict] = []
        for evenement in assistant.repondre(question, historique, etat.epingles):
            if evenement.get("type") == "texte":
                reponse.append(evenement["texte"])
            if evenement.get("type") == "erreur":
                echec = True
            if evenement.get("type") == "fin":
                differe.append(evenement)
                continue
            yield evenement
        for evenement in differe:
            yield evenement

        texte = "".join(reponse).strip()
        if texte and not echec:
            self.etats.ajouter_message(coffre.cle, "assistant", texte)


# ----------------------------------------------------------------- gestionnaire


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "AssistantMJ/1.0"
    protocol_version = "HTTP/1.1"
    app: Application  # pose par servir()

    # -------------------------------------------------------------- reponses

    def log_message(self, format, *args):  # noqa: A002
        if self.path.startswith(("/static/", "/favicon")):
            return
        print("  %s %s" % (self.command, self.path))

    def _envoyer(self, code: int, corps: bytes, type_mime: str, cache: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(corps)))
        if not cache:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(corps)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, donnees, code: int = 200) -> None:
        self._envoyer(
            code,
            json.dumps(donnees, ensure_ascii=False, default=str).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _texte(self, texte: str, code: int = 200) -> None:
        self._envoyer(code, texte.encode("utf-8"), "text/plain; charset=utf-8")

    def _corps_json(self) -> dict:
        try:
            taille = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if taille <= 0 or taille > 2_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(taille).decode("utf-8")) or {}
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return {}

    # ------------------------------------------------------------------- GET

    def do_GET(self) -> None:  # noqa: N802
        separe = urllib.parse.urlsplit(self.path)
        chemin = urllib.parse.unquote(separe.path)
        params = urllib.parse.parse_qs(separe.query)

        try:
            if chemin == "/" or chemin.startswith("/page/") or chemin == "/recherche":
                return self._servir_index()
            if chemin.startswith("/static/"):
                return self._servir_statique(chemin[len("/static/") :])
            if chemin == "/favicon.ico":
                return self._servir_statique("favicon.svg")
            if chemin == "/api/etat":
                return self._json(self.app.etat_complet())
            if chemin == "/api/arbre":
                etat = self.app.etat()
                return self._json(self.app.index().arbre(etat.mode_joueurs))
            if chemin == "/api/page":
                demande = (params.get("chemin") or [""])[0]
                if not demande:
                    return self._json({"erreur": "chemin manquant"}, 400)
                resultat = self.app.rendre_page(demande)
                code = 404 if resultat.get("erreur") == "introuvable" else 200
                return self._json(resultat, code)
            if chemin == "/api/carte":
                demande = (params.get("chemin") or [""])[0]
                resultat = self.app.rendre_carte(demande)
                code = 404 if resultat.get("erreur") == "introuvable" else 200
                return self._json(resultat, code)
            if chemin == "/api/recherche":
                etat = self.app.etat()
                resultats = self.app.index().chercher(
                    (params.get("q") or [""])[0],
                    type_=(params.get("type") or [""])[0],
                    visibilite=(params.get("visibilite") or [""])[0],
                    mode_joueurs=etat.mode_joueurs,
                )
                return self._json({"resultats": resultats})
            if chemin == "/api/ollama":
                # `url` permet d'essayer une adresse avant de l'enregistrer.
                url = (params.get("url") or [""])[0].strip() or self.app.cfg.ollama_url
                if not url.startswith(("http://", "https://")):
                    return self._json(
                        {
                            "disponible": False,
                            "modeles": [],
                            "url": url,
                            "raison": "L'URL doit commencer par http:// ou https://",
                        }
                    )
                local = modeles.ModeleOllama(
                    self.app.cfg.modele_ollama, url, self.app.cfg.cle_ollama
                )
                return self._json(
                    {
                        "disponible": local.disponible,
                        "modeles": local.modeles_disponibles(),
                        "url": url,
                        "raison": local.raison_indisponible,
                        "cle_utilisee": bool(self.app.cfg.cle_ollama),
                    }
                )
            if chemin == "/api/brut":
                return self._servir_brut((params.get("chemin") or [""])[0])
        except CoffreIntrouvable as err:
            return self._json({"erreur": "coffre introuvable", "detail": str(err)}, 503)
        except HorsCoffre:
            return self._json({"erreur": "chemin refuse"}, 403)
        except Exception:
            traceback.print_exc()
            return self._json({"erreur": "erreur interne"}, 500)

        self._texte("Introuvable", 404)

    # ------------------------------------------------------------------ POST

    def do_POST(self) -> None:  # noqa: N802
        chemin = urllib.parse.urlsplit(self.path).path
        try:
            if chemin == "/api/conversation":
                return self._conversation()
            corps = self._corps_json()

            if chemin == "/api/coffre":
                cle = str(corps.get("cle") or "")
                if cle not in self.app.cfg.coffres:
                    return self._json({"erreur": "coffre inconnu"}, 400)
                self.app.cfg.coffre_par_defaut = cle
                self.app.cfg.ecrire()
                return self._json(self.app.etat_complet())

            if chemin == "/api/coffre-nouveau":
                brut = str(corps.get("chemin") or "").strip()
                if not brut:
                    return self._json({"erreur": "chemin manquant"}, 400)
                cible = Path(brut).expanduser()
                if not cible.is_dir():
                    return self._json(
                        {"erreur": "Ce dossier n'existe pas : %s" % cible}, 400
                    )
                self.app.cfg.enregistrer_coffre(cible, corps.get("nom") or None)
                return self._json(self.app.etat_complet())

            if chemin == "/api/epingle":
                coffre = self.app.coffre_courant
                if coffre is None:
                    return self._json({"erreur": "aucun coffre"}, 400)
                page = self.app.index().page(str(corps.get("chemin") or ""))
                if page is None:
                    return self._json({"erreur": "page introuvable"}, 404)
                self.app.etats.basculer_epingle(coffre.cle, page.chemin)
                return self._json(self.app.etat_complet())

            if chemin == "/api/mode-joueurs":
                coffre = self.app.coffre_courant
                if coffre is None:
                    return self._json({"erreur": "aucun coffre"}, 400)
                self.app.etats.definir_mode_joueurs(coffre.cle, bool(corps.get("actif")))
                return self._json(self.app.etat_complet())

            if chemin == "/api/modele":
                cfg = self.app.cfg
                fournisseur = str(corps.get("fournisseur") or "").strip()
                identifiant = str(corps.get("identifiant") or "").strip()
                if fournisseur not in ("claude", "ollama"):
                    return self._json({"erreur": "fournisseur inconnu"}, 400)

                # Le menu n'envoie qu'un identifiant ; la page de parametres
                # envoie les deux modeles, l'URL et l'effort.
                if identifiant:
                    if fournisseur == "claude":
                        cfg.modele_claude = identifiant
                    else:
                        cfg.modele_ollama = identifiant
                if corps.get("modele_claude"):
                    cfg.modele_claude = str(corps["modele_claude"]).strip()
                if corps.get("modele_ollama"):
                    cfg.modele_ollama = str(corps["modele_ollama"]).strip()
                if corps.get("ollama_url"):
                    url = str(corps["ollama_url"]).strip().rstrip("/")
                    if not url.startswith(("http://", "https://")):
                        return self._json(
                            {"erreur": "L'URL doit commencer par http:// ou https://"}, 400
                        )
                    cfg.ollama_url = url
                if corps.get("effort"):
                    effort = str(corps["effort"]).strip()
                    if effort not in ("low", "medium", "high", "xhigh", "max"):
                        return self._json({"erreur": "effort inconnu : %s" % effort}, 400)
                    cfg.effort = effort

                cfg.fournisseur = fournisseur
                self.app.oublier_modele()
                cfg.ecrire()
                return self._json(self.app.etat_complet())

            if chemin == "/api/ecrire":
                try:
                    resultat = self.app.ecrire(corps)
                except EcritureRefusee as err:
                    return self._json({"erreur": str(err)}, 400)
                return self._json(resultat)

            if chemin == "/api/proposition/ignorer":
                coffre = self.app.coffre_courant
                if coffre is not None:
                    self.app.etats.retirer_proposition(coffre.cle, str(corps.get("id") or ""))
                return self._json({"ok": True})

            if chemin == "/api/conversation/vider":
                coffre = self.app.coffre_courant
                if coffre is not None:
                    self.app.etats.vider_conversation(coffre.cle)
                return self._json({"ok": True})
        except CoffreIntrouvable as err:
            return self._json({"erreur": "coffre introuvable", "detail": str(err)}, 503)
        except Exception:
            traceback.print_exc()
            return self._json({"erreur": "erreur interne"}, 500)

        self._texte("Introuvable", 404)

    # --------------------------------------------------------------- services

    def _servir_index(self) -> None:
        fichier = STATIQUE / "index.html"
        try:
            self._envoyer(200, fichier.read_bytes(), "text/html; charset=utf-8")
        except OSError:
            self._texte("index.html manquant", 500)

    def _servir_statique(self, nom: str) -> None:
        cible = (STATIQUE / nom).resolve()
        if STATIQUE.resolve() not in cible.parents or not cible.is_file():
            return self._texte("Introuvable", 404)
        type_mime = mimetypes.guess_type(cible.name)[0] or "application/octet-stream"
        if type_mime.startswith("text/") or type_mime in ("application/javascript", "image/svg+xml"):
            type_mime += "; charset=utf-8"
        self._envoyer(200, cible.read_bytes(), type_mime)

    def _servir_brut(self, chemin: str) -> None:
        """Le Markdown tel quel, pour verifier ce que l'outil a lu."""
        index = self.app.index()
        page = index.page(chemin)
        if page is None:
            return self._texte("Introuvable", 404)
        if self.app.etat().mode_joueurs and page.reserve_mj:
            return self._texte("Page reservee au MJ.", 403)
        corps = page.corps
        if self.app.etat().mode_joueurs:
            corps = rendu.retirer_secrets(corps)
        self._texte(corps)

    def _conversation(self) -> None:
        corps = self._corps_json()
        question = str(corps.get("question") or "").strip()
        if not question:
            return self._json({"erreur": "question vide"}, 400)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def ecrire(evenement: dict) -> bool:
            charge = json.dumps(evenement, ensure_ascii=False, default=str)
            try:
                self.wfile.write(("data: " + charge + "\n\n").encode("utf-8"))
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        try:
            for evenement in self.app.flux_conversation(question):
                if not ecrire(evenement):
                    return
        except Exception as err:
            traceback.print_exc()
            ecrire({"type": "erreur", "texte": "Erreur interne : %s" % err})
        ecrire({"type": "clos"})


def servir(cfg: Config, ouvrir: bool = True) -> None:
    app = Application(cfg)
    Gestionnaire.app = app
    serveur = ThreadingHTTPServer((cfg.hote, cfg.port), Gestionnaire)
    serveur.daemon_threads = True

    adresse = "http://%s:%d/" % ("localhost" if cfg.hote in ("127.0.0.1", "0.0.0.0") else cfg.hote, cfg.port)
    coffre = app.coffre_courant
    print("Assistant de MJ")
    print("  adresse  : " + adresse)
    if coffre is None:
        print("  coffre   : aucun — le chemin sera demande dans la page")
    else:
        print("  coffre   : %s (%s)" % (coffre.nom, coffre.chemin))
        if not coffre.existe:
            print("             ATTENTION : ce dossier n'existe pas")
    etat_modele = app.modele()
    print(
        "  modele   : %s / %s — %s"
        % (
            etat_modele.fournisseur,
            etat_modele.identifiant,
            "pret" if etat_modele.disponible else etat_modele.raison_indisponible,
        )
    )
    print("  config   : %s" % (cfg.source or "valeurs par defaut"))
    print("\nCtrl+C pour arreter.\n")

    if ouvrir:
        threading.Timer(0.6, lambda: webbrowser.open(adresse)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArret.")
    finally:
        serveur.server_close()
