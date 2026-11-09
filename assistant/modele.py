"""Les modeles : Claude (API) et Ollama (local), derriere une meme interface.

Chaque modele expose `repondre()`, un generateur d'evenements :

    {"type": "texte",  "texte": "..."}        un fragment de reponse
    {"type": "outil",  "nom": "...", ...}     le modele a consulte une page
    {"type": "info",   "texte": "..."}        trace pour l'interface
    {"type": "erreur", "texte": "..."}        echec, la conversation s'arrete
    {"type": "fin",    "usage": {...}}        termine

Degradation douce (DESIGN 4) : sans cle d'API et sans Ollama, ces classes se
declarent indisponibles et expliquent pourquoi, sans empecher la lecture ni la
recherche de fonctionner.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Iterator

# Streaming : on laisse de la place au modele, les delais HTTP ne comptent pas.
MAX_TOKENS = 64000

# Fallback serveur en cas de refus d'un classifieur de surete.
BETA_FALLBACK = "server-side-fallback-2026-07-01"


class Modele:
    """Interface commune. `disponible` dit si le modele peut etre appele."""

    fournisseur = "?"

    def __init__(self, identifiant: str):
        self.identifiant = identifiant
        self.raison_indisponible: str | None = None

    @property
    def disponible(self) -> bool:
        return self.raison_indisponible is None

    @property
    def outils_natifs(self) -> bool:
        """Vrai si le modele sait demander lui-meme les pages dont il a besoin."""
        return False

    def repondre(
        self,
        systeme: str,
        messages: list[dict],
        outils: list[dict] | None = None,
        executer: Callable[[str, dict], str] | None = None,
    ) -> Iterator[dict]:
        raise NotImplementedError

    def decrire(self) -> dict:
        return {
            "fournisseur": self.fournisseur,
            "identifiant": self.identifiant,
            "disponible": self.disponible,
            "raison": self.raison_indisponible,
            "outils_natifs": self.outils_natifs,
        }


# --------------------------------------------------------------------- Claude


class ModeleClaude(Modele):
    fournisseur = "claude"

    def __init__(self, identifiant: str, cle_api: str | None, effort: str = "medium"):
        super().__init__(identifiant)
        self.effort = effort
        self._client = None
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.raison_indisponible = (
                "La bibliotheque anthropic n'est pas installee. "
                "Installer avec : pip install anthropic"
            )
            return
        if not cle_api:
            self.raison_indisponible = (
                "Aucune cle d'API. Definir ANTHROPIC_API_KEY, ou cle_api dans la "
                "section [claude] du fichier de configuration."
            )
            return
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=cle_api)
        # Si le SDK ou l'API refuse le fallback serveur, on repasse sans, une
        # fois pour toutes (voir _entrer).
        self._beta_actif = True

    @property
    def outils_natifs(self) -> bool:
        return True

    def repondre(
        self,
        systeme: str,
        messages: list[dict],
        outils: list[dict] | None = None,
        executer: Callable[[str, dict], str] | None = None,
    ) -> Iterator[dict]:
        if not self.disponible:
            yield {"type": "erreur", "texte": self.raison_indisponible or "modele indisponible"}
            return

        anthropic = self._anthropic
        # Le prompt systeme est stable d'un message a l'autre : on le met en cache.
        blocs_systeme = [
            {"type": "text", "text": systeme, "cache_control": {"type": "ephemeral"}}
        ]
        conversation = list(messages)
        usage_total = {"entree": 0, "sortie": 0, "cache_lu": 0}
        tours = 0

        while True:
            tours += 1
            if tours > 12:
                yield {
                    "type": "erreur",
                    "texte": "Trop d'aller-retours avec le coffre ; reponse interrompue.",
                }
                return
            try:
                message = yield from self._un_tour(
                    blocs_systeme, conversation, outils, usage_total, "\n\n" if tours > 1 else ""
                )
            except anthropic.APIStatusError as err:
                yield {"type": "erreur", "texte": _message_erreur(err)}
                return
            except anthropic.APIConnectionError as err:
                yield {"type": "erreur", "texte": "Connexion a l'API impossible : %s" % err}
                return
            except Exception as err:  # une erreur de modele ne doit pas tuer le serveur
                yield {"type": "erreur", "texte": "Erreur inattendue : %s" % err}
                return

            if message.stop_reason == "refusal":
                details = getattr(message, "stop_details", None)
                categorie = getattr(details, "category", None) or "non precisee"
                yield {
                    "type": "erreur",
                    "texte": "Le modele a decline la demande (categorie : %s)." % categorie,
                }
                return

            if message.stop_reason == "pause_turn":
                conversation.append({"role": "assistant", "content": message.content})
                continue

            if message.stop_reason != "tool_use":
                yield {"type": "fin", "usage": usage_total}
                return

            appels = [b for b in message.content if getattr(b, "type", "") == "tool_use"]
            conversation.append({"role": "assistant", "content": message.content})

            resultats = []
            for appel in appels:
                entree = appel.input if isinstance(appel.input, dict) else {}
                yield {"type": "outil", "nom": appel.name, "entree": entree}
                if executer is None:
                    texte = "Outil indisponible."
                    erreur = True
                else:
                    try:
                        texte = executer(appel.name, entree)
                        erreur = False
                    except Exception as err:
                        texte = "Echec de l'outil : %s" % err
                        erreur = True
                bloc = {
                    "type": "tool_result",
                    "tool_use_id": appel.id,
                    "content": texte,
                }
                if erreur:
                    bloc["is_error"] = True
                resultats.append(bloc)
            # Tous les resultats dans un seul message utilisateur.
            conversation.append({"role": "user", "content": resultats})

    def _un_tour(self, blocs_systeme, conversation, outils, usage_total, prefixe=""):
        """Un appel en streaming. Emet les fragments de texte, renvoie le message.
        `prefixe` precede le premier fragment : il separe le texte de deux tours."""
        parametres = {
            "model": self.identifiant,
            "max_tokens": MAX_TOKENS,
            "system": blocs_systeme,
            "messages": conversation,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
        }
        if outils:
            # Pas de streaming fin des entrees d'outil : meme une page proposee
            # tient sans peine, et l'API garde ainsi sa validation de schema.
            parametres["tools"] = outils

        flux = None
        try:
            flux = self._entrer(parametres)
            for fragment in flux.text_stream:
                if fragment:
                    if prefixe:
                        fragment, prefixe = prefixe + fragment.lstrip(), ""
                    yield {"type": "texte", "texte": fragment}
            message = flux.get_final_message()
        finally:
            if flux is not None:
                flux.close()

        usage = getattr(message, "usage", None)
        if usage is not None:
            usage_total["entree"] += getattr(usage, "input_tokens", 0) or 0
            usage_total["sortie"] += getattr(usage, "output_tokens", 0) or 0
            usage_total["cache_lu"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        return message

    def _entrer(self, parametres: dict):
        """Ouvre le flux, avec le fallback serveur en cas de refus de surete.

        La requete HTTP part a l'entree du gestionnaire de contexte, pas a
        l'appel : c'est donc ici, et pas plus tot, qu'un SDK trop ancien ou une
        API qui ignore le fallback se manifeste. On retombe alors sur l'appel
        ordinaire, definitivement pour cette instance.
        """
        if self._beta_actif:
            try:
                return self._client.beta.messages.stream(
                    betas=[BETA_FALLBACK], fallbacks="default", **parametres
                ).__enter__()
            except TypeError:
                self._beta_actif = False
            except self._anthropic.BadRequestError as err:
                if not _refus_de_parametre(err):
                    raise
                self._beta_actif = False
        return self._client.messages.stream(**parametres).__enter__()


def _refus_de_parametre(err) -> bool:
    """Vrai si un 400 porte sur le fallback serveur ou sur l'en-tete beta."""
    texte = str(getattr(err, "message", "") or err).lower()
    return "fallback" in texte or "beta" in texte


def _message_erreur(err) -> str:
    code = getattr(err, "status_code", "?")
    if code == 401:
        return "Cle d'API refusee (401). Verifier ANTHROPIC_API_KEY."
    if code == 429:
        return "Limite de debit atteinte (429). Reessayer dans un instant."
    if code == 404:
        return "Modele inconnu (404) : %s" % getattr(err, "message", err)
    return "Erreur de l'API (%s) : %s" % (code, getattr(err, "message", err))


# --------------------------------------------------------------------- Ollama


class ModeleOllama(Modele):
    """Modele servi par Ollama, local ou dans le cloud.

    Un modele qui declare la capacite `tools` (Ollama la donne dans
    /api/show) recoit les outils, comme Claude : il demande les pages dont il a
    besoin et propose ses ecritures par outil. Sinon, le contexte est choisi
    avant l'appel et le coffre lui est fourni d'avance. Le reglage
    `[ollama] outils` force l'un ou l'autre (« oui », « non ») ; par defaut,
    « auto » suit ce que declare le modele.
    """

    fournisseur = "ollama"

    # Un nom comme « localhost » resout en IPv6 puis en IPv4, et chaque essai
    # attend ce delai : le garder court, sinon tester une adresse morte fige
    # l'interface plusieurs secondes.
    DELAI_SONDE = 1.2
    DELAI_CAPACITES = 6
    TOURS_MAX = 12

    def __init__(
        self,
        identifiant: str,
        url: str,
        cle_api: str | None = None,
        delai: float | None = None,
        outils: str = "auto",
    ):
        super().__init__(identifiant)
        self.url = url.rstrip("/")
        # Ollama local n'en demande pas ; Ollama Cloud et les instances
        # derriere une authentification, si.
        self.cle_api = cle_api or None
        self.refuse = False
        self.capacites: list[str] = []
        self.reglage_outils = outils if outils in ("auto", "oui", "non") else "auto"
        # Une seule sonde : elle dit a la fois si Ollama repond et ce qu'il a.
        self._modeles = self._sonder(delai if delai is not None else self.DELAI_SONDE)
        if self._modeles is None and not self.raison_indisponible:
            self.raison_indisponible = (
                "Ollama ne repond pas sur %s. Le lancer avec : ollama serve" % self.url
            )
        if self.disponible and self.reglage_outils == "auto":
            self.capacites = self._capacites()

    @property
    def outils_natifs(self) -> bool:
        if self.reglage_outils == "oui":
            return True
        if self.reglage_outils == "non":
            return False
        return "tools" in self.capacites

    def decrire(self) -> dict:
        description = super().decrire()
        description["capacites"] = list(self.capacites)
        return description

    def _entetes(self) -> dict[str, str]:
        entetes = {"Content-Type": "application/json"}
        if self.cle_api:
            entetes["Authorization"] = "Bearer " + self.cle_api
        return entetes

    def _sonder(self, delai: float) -> list[str] | None:
        """La liste des modeles installes, ou None si Ollama ne repond pas."""
        requete = urllib.request.Request(
            self.url + "/api/tags", headers=self._entetes(), method="GET"
        )
        try:
            with urllib.request.urlopen(requete, timeout=delai) as reponse:
                if reponse.status != 200:
                    return None
                brut = json.loads(reponse.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                self.raison_indisponible = (
                    "Ollama a refuse la cle d'API (%s) sur %s. Verifier "
                    "OLLAMA_API_KEY dans le fichier .env." % (err.code, self.url)
                    if self.cle_api
                    else "Ollama demande une cle d'API (%s) sur %s. Definir "
                    "OLLAMA_API_KEY dans le fichier .env." % (err.code, self.url)
                )
                self.refuse = True
            return None
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            return None
        return sorted(str(m.get("name", "")) for m in brut.get("models", []) if m.get("name"))

    def _capacites(self) -> list[str]:
        """Ce que le modele declare savoir faire (« tools », « thinking »...).

        En cas d'echec, une liste vide : le modele est alors traite sans
        outils, ce qui marche toujours.
        """
        requete = urllib.request.Request(
            self.url + "/api/show",
            data=json.dumps({"model": self.identifiant}).encode("utf-8"),
            headers=self._entetes(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(requete, timeout=self.DELAI_CAPACITES) as reponse:
                brut = json.loads(reponse.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            return []
        return [str(c) for c in (brut.get("capabilities") or []) if c]

    def modeles_disponibles(self) -> list[str]:
        return list(self._modeles or [])

    def repondre(
        self,
        systeme: str,
        messages: list[dict],
        outils: list[dict] | None = None,
        executer: Callable[[str, dict], str] | None = None,
    ) -> Iterator[dict]:
        if not self.disponible:
            yield {"type": "erreur", "texte": self.raison_indisponible or "modele indisponible"}
            return

        conversation = [{"role": "system", "content": systeme}] + [
            {"role": m["role"], "content": _texte_simple(m.get("content"))}
            for m in messages
        ]
        definitions = _outils_ollama(outils) if outils and self.outils_natifs else None

        deja_ecrit = False
        for _ in range(self.TOURS_MAX):
            charge = {"model": self.identifiant, "stream": True, "messages": conversation}
            if definitions:
                charge["tools"] = definitions
            # Le texte de chaque tour suit celui du precedent : sans separation,
            # « je lis la page.Voici » se colle.
            resultat = yield from self._un_tour(charge, "\n\n" if deja_ecrit else "")
            if resultat is None:
                return  # l'erreur a deja ete emise
            texte, appels = resultat
            deja_ecrit = deja_ecrit or bool(texte.strip())
            if not appels:
                yield {"type": "fin", "usage": {}}
                return

            conversation.append({"role": "assistant", "content": texte, "tool_calls": appels})
            for appel in appels:
                fonction = appel.get("function") or {}
                nom = str(fonction.get("name") or "")
                entree = _arguments(fonction.get("arguments"))
                yield {"type": "outil", "nom": nom, "entree": entree}
                if executer is None:
                    sortie = "Outil indisponible."
                else:
                    try:
                        sortie = executer(nom, entree)
                    except Exception as err:  # un outil ne doit pas tuer la conversation
                        sortie = "Echec de l'outil : %s" % err
                conversation.append({"role": "tool", "tool_name": nom, "content": sortie})

        yield {
            "type": "erreur",
            "texte": "Trop d'aller-retours avec le coffre ; reponse interrompue.",
        }

    def _un_tour(self, charge: dict, prefixe: str = ""):
        """Un appel en streaming. Emet le texte ; renvoie (texte, appels d'outil),
        ou None apres avoir emis une erreur. `prefixe` precede le premier
        fragment de texte, s'il y en a un."""
        requete = urllib.request.Request(
            self.url + "/api/chat",
            data=json.dumps(charge).encode("utf-8"),
            headers=self._entetes(),
            method="POST",
        )
        morceaux: list[str] = []
        appels: list[dict] = []
        try:
            with urllib.request.urlopen(requete, timeout=600) as reponse:
                for ligne in reponse:
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    try:
                        bloc = json.loads(ligne.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if bloc.get("error"):
                        yield {"type": "erreur", "texte": str(bloc["error"])}
                        return None
                    message = bloc.get("message") or {}
                    # Le raisonnement (« thinking ») n'est pas montre : seule la
                    # reponse l'est.
                    fragment = message.get("content") or ""
                    if fragment:
                        if not morceaux and prefixe:
                            fragment = prefixe + fragment.lstrip()
                        morceaux.append(fragment)
                        yield {"type": "texte", "texte": fragment}
                    for appel in message.get("tool_calls") or []:
                        if isinstance(appel, dict):
                            appels.append(appel)
                    if bloc.get("done"):
                        break
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                yield {
                    "type": "erreur",
                    "texte": (
                        "Ollama a refuse la cle d'API (%s). Verifier OLLAMA_API_KEY "
                        "dans le fichier .env, puis relancer le serveur." % err.code
                        if self.cle_api
                        else "Ollama demande une cle d'API (%s). Definir OLLAMA_API_KEY "
                        "dans le fichier .env, puis relancer le serveur." % err.code
                    ),
                }
                return None
            detail = ""
            try:
                detail = err.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            yield {
                "type": "erreur",
                "texte": "Ollama a repondu %s. %s" % (err.code, detail),
            }
            return None
        except (urllib.error.URLError, OSError) as err:
            yield {"type": "erreur", "texte": "Ollama injoignable : %s" % err}
            return None
        return "".join(morceaux), appels


def _outils_ollama(outils: list[dict]) -> list[dict]:
    """Les definitions d'outils au format d'Ollama (celui des « functions »)."""
    return [
        {
            "type": "function",
            "function": {
                "name": o["name"],
                "description": o.get("description", ""),
                "parameters": o.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for o in outils
    ]


def _arguments(brut) -> dict:
    """Les arguments d'un appel : un objet, ou parfois une chaine JSON."""
    if isinstance(brut, dict):
        return brut
    if isinstance(brut, str):
        try:
            valeur = json.loads(brut)
        except json.JSONDecodeError:
            return {}
        return valeur if isinstance(valeur, dict) else {}
    return {}


def _texte_simple(contenu) -> str:
    """Ollama n'accepte que du texte : on aplatit les blocs de contenu."""
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        morceaux = []
        for bloc in contenu:
            if isinstance(bloc, dict):
                if bloc.get("type") == "text":
                    morceaux.append(str(bloc.get("text", "")))
                elif bloc.get("type") == "tool_result":
                    morceaux.append(str(bloc.get("content", "")))
            elif isinstance(bloc, str):
                morceaux.append(bloc)
        return "\n\n".join(m for m in morceaux if m)
    return ""


def construire(cfg) -> Modele:
    """Construit le modele decrit par la configuration."""
    if cfg.fournisseur == "ollama":
        return ModeleOllama(
            cfg.modele_ollama, cfg.ollama_url, cfg.cle_ollama,
            outils=getattr(cfg, "ollama_outils", "auto"),
        )
    return ModeleClaude(cfg.modele_claude, cfg.cle_api, cfg.effort)
