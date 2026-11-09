"""Configuration : fichier TOML unique, variable d'environnement, ligne de commande.

Priorite (DESIGN 6) : ligne de commande > environnement > fichier de configuration.
Aucun chemin de coffre n'est code en dur ici.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

NOM_APP = "assistant-jdr"

# Valeurs par defaut : tout marche sans toucher au fichier de configuration.
DEFAUTS = {
    "hote": "127.0.0.1",
    "port": 3011,
    "fournisseur": "claude",  # "claude" ou "ollama"
    "modele_claude": "claude-opus-5-5",
    "effort": "medium",  # low | medium | high | xhigh | max
    "modele_ollama": "llama3.1",
    "ollama_url": "http://localhost:11434",
    "dossier_notes": "10 Notes de l assistant",
    # Budget de contexte pour un modele sans outils, en caracteres (~4/token).
    "contexte_max": 200000,
}


def dossier_config() -> Path:
    """~/.config/assistant-jdr sous POSIX, %APPDATA%/assistant-jdr sous Windows."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / NOM_APP
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / NOM_APP


def dossier_donnees() -> Path:
    """Les epingles et l'historique vivent ici, jamais dans le coffre (DESIGN 6)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / NOM_APP
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / NOM_APP


def fichier_config() -> Path:
    return dossier_config() / "config.toml"


# ------------------------------------------------------------ secrets (.env)

# Noms reconnus, dans l'ordre. Le premier est celui qu'utilise Ollama lui-meme.
NOMS_CLE_OLLAMA = ("OLLAMA_API_KEY", "OLLAMA_KEY", "OLLAMA_TOKEN")
NOMS_CLE_CLAUDE = ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")


def fichiers_env() -> list[Path]:
    """Les .env consultes, dans l'ordre de priorite."""
    chemins = []
    explicite = os.environ.get("ASSISTANT_ENV")
    if explicite:
        chemins.append(Path(explicite).expanduser())
    # A la racine du programme (le dossier qui contient le paquet assistant).
    chemins.append(Path(__file__).resolve().parent.parent / ".env")
    chemins.append(Path.cwd() / ".env")
    chemins.append(dossier_config() / ".env")
    vus, uniques = set(), []
    for chemin in chemins:
        cle = str(chemin).lower()
        if cle not in vus:
            vus.add(cle)
            uniques.append(chemin)
    return uniques


def lire_env(chemin: Path) -> dict[str, str]:
    """Analyse un .env : `NOM=valeur`, guillemets et `export` optionnels.

    Les valeurs sont des secrets : elles ne sont ni journalisees, ni renvoyees
    par l'API, ni recopiees dans le fichier de configuration.
    """
    valeurs: dict[str, str] = {}
    try:
        texte = chemin.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return valeurs
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        if ligne.startswith("export "):
            ligne = ligne[len("export ") :].strip()
        if "=" not in ligne:
            continue
        nom, _, valeur = ligne.partition("=")
        nom = nom.strip()
        valeur = valeur.strip()
        if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in "\"'":
            valeur = valeur[1:-1]
        elif " #" in valeur:
            # Commentaire en fin de ligne, seulement hors guillemets.
            valeur = valeur.split(" #", 1)[0].strip()
        if nom:
            valeurs[nom] = valeur
    return valeurs


def trouver_secret(noms: tuple[str, ...]) -> tuple[str | None, str]:
    """Cherche un secret : variables d'environnement d'abord, puis les .env.

    Renvoie (valeur, provenance). La provenance nomme la variable et le
    fichier, jamais la valeur.
    """
    for nom in noms:
        if os.environ.get(nom):
            return os.environ[nom], "variable d'environnement %s" % nom
    for chemin in fichiers_env():
        if not chemin.is_file():
            continue
        valeurs = lire_env(chemin)
        for nom in noms:
            if valeurs.get(nom):
                return valeurs[nom], "%s dans %s" % (nom, chemin)
    return None, "absente"


@dataclass
class Coffre:
    """Un coffre declare : une cle, un chemin, un nom affichable."""

    cle: str
    chemin: Path
    nom: str
    dossier_notes: str = DEFAUTS["dossier_notes"]

    @property
    def existe(self) -> bool:
        return self.chemin.is_dir()


@dataclass
class Config:
    coffres: dict[str, Coffre] = field(default_factory=dict)
    coffre_par_defaut: str | None = None
    hote: str = DEFAUTS["hote"]
    port: int = DEFAUTS["port"]
    fournisseur: str = DEFAUTS["fournisseur"]
    modele_claude: str = DEFAUTS["modele_claude"]
    effort: str = DEFAUTS["effort"]
    modele_ollama: str = DEFAUTS["modele_ollama"]
    ollama_url: str = DEFAUTS["ollama_url"]
    contexte_max: int = DEFAUTS["contexte_max"]
    cle_api: str | None = None
    source_cle_api: str = "absente"
    # Ollama Cloud, ou un Ollama derriere une authentification.
    cle_ollama: str | None = None
    source_cle_ollama: str = "absente"
    source: Path | None = None

    # ---------------------------------------------------------------- lecture

    @classmethod
    def charger(cls, argv: list[str] | None = None) -> "Config":
        cfg = cls()
        chemin = fichier_config()
        brut: dict = {}
        if chemin.is_file():
            try:
                brut = tomllib.loads(chemin.read_text(encoding="utf-8"))
                cfg.source = chemin
            except (tomllib.TOMLDecodeError, OSError) as err:
                print(f"[config] {chemin} illisible : {err}", file=sys.stderr)

        cfg.hote = str(brut.get("hote", cfg.hote))
        cfg.port = int(brut.get("port", cfg.port))
        cfg.fournisseur = str(brut.get("fournisseur", cfg.fournisseur))
        cfg.effort = str(brut.get("effort", cfg.effort))
        cfg.contexte_max = int(brut.get("contexte_max", cfg.contexte_max))
        cfg.cle_api = brut.get("cle_api") or None

        claude = brut.get("claude") or {}
        cfg.modele_claude = str(
            claude.get("modele", brut.get("modele_claude", cfg.modele_claude))
        )
        if claude.get("cle_api"):
            cfg.cle_api = str(claude["cle_api"])

        ollama = brut.get("ollama") or {}
        cfg.modele_ollama = str(ollama.get("modele", cfg.modele_ollama))
        cfg.ollama_url = str(ollama.get("url", cfg.ollama_url)).rstrip("/")

        for cle, bloc in (brut.get("coffres") or {}).items():
            if not isinstance(bloc, dict) or not bloc.get("chemin"):
                continue
            cfg.coffres[cle] = Coffre(
                cle=cle,
                chemin=_resoudre(bloc["chemin"]),
                nom=str(bloc.get("nom") or cle),
                dossier_notes=str(bloc.get("dossier_notes") or DEFAUTS["dossier_notes"]),
            )
        defaut = brut.get("coffre_par_defaut")
        if defaut in cfg.coffres:
            cfg.coffre_par_defaut = str(defaut)

        # Un coffre simple, sans section [coffres].
        if brut.get("coffre"):
            cfg._ajouter_ad_hoc(_resoudre(brut["coffre"]))

        # Environnement, puis ligne de commande : chacun gagne sur le precedent.
        if os.environ.get("ASSISTANT_COFFRE"):
            cfg._ajouter_ad_hoc(_resoudre(os.environ["ASSISTANT_COFFRE"]))

        # Les cles : variable d'environnement, sinon .env, sinon le fichier de
        # configuration. Une cle n'est jamais reecrite dans la configuration.
        if cfg.cle_api:
            cfg.source_cle_api = "fichier de configuration"
        trouvee, provenance = trouver_secret(NOMS_CLE_CLAUDE)
        if trouvee:
            cfg.cle_api, cfg.source_cle_api = trouvee, provenance
        cfg.cle_ollama, cfg.source_cle_ollama = trouver_secret(NOMS_CLE_OLLAMA)

        cfg._appliquer_argv(argv if argv is not None else sys.argv[1:])
        if cfg.coffre_par_defaut is None and cfg.coffres:
            cfg.coffre_par_defaut = next(iter(cfg.coffres))
        return cfg

    # ------------------------------------------------------------- arguments

    def _appliquer_argv(self, argv: list[str]) -> None:
        i = 0
        while i < len(argv):
            arg = argv[i]
            suivant = argv[i + 1] if i + 1 < len(argv) else None
            if arg in ("--coffre", "-c") and suivant:
                # Soit la cle d'un coffre declare, soit un chemin.
                if suivant in self.coffres:
                    self.coffre_par_defaut = suivant
                else:
                    self._ajouter_ad_hoc(_resoudre(suivant))
                i += 2
            elif arg == "--port" and suivant:
                self.port = int(suivant)
                i += 2
            elif arg == "--hote" and suivant:
                self.hote = suivant
                i += 2
            elif arg == "--modele" and suivant:
                # --modele ollama:llama3.1  ou  --modele claude-opus-5-5
                if suivant.startswith("ollama"):
                    self.fournisseur = "ollama"
                    if ":" in suivant:
                        self.modele_ollama = suivant.split(":", 1)[1]
                else:
                    self.fournisseur = "claude"
                    self.modele_claude = suivant
                i += 2
            elif arg in ("--aide", "-h", "--help"):
                print(AIDE)
                raise SystemExit(0)
            else:
                i += 1

    def _ajouter_ad_hoc(self, chemin: Path) -> None:
        cle = _cle_depuis_chemin(chemin)
        self.coffres[cle] = Coffre(cle=cle, chemin=chemin, nom=chemin.name or cle)
        self.coffre_par_defaut = cle

    # -------------------------------------------------------------- ecriture

    def enregistrer_coffre(self, chemin: Path | str, nom: str | None = None) -> Coffre:
        """Appele par la page de demarrage quand aucun coffre n'est connu."""
        chemin = _resoudre(str(chemin))
        cle = _cle_depuis_chemin(chemin)
        coffre = Coffre(cle=cle, chemin=chemin, nom=nom or chemin.name or cle)
        self.coffres[cle] = coffre
        self.coffre_par_defaut = cle
        self.ecrire()
        return coffre

    def ecrire(self) -> Path:
        """Reecrit le fichier de configuration. Jamais la cle d'API."""
        cible = fichier_config()
        cible.parent.mkdir(parents=True, exist_ok=True)
        lignes = [
            "# Configuration de l'assistant de MJ. Reecrit par l'outil.",
        ]
        if self.coffre_par_defaut:
            lignes.append(f'coffre_par_defaut = "{self.coffre_par_defaut}"')
        lignes += [
            f'hote = "{self.hote}"',
            f"port = {self.port}",
            f'fournisseur = "{self.fournisseur}"',
            f'effort = "{self.effort}"',
            f"contexte_max = {self.contexte_max}",
            "",
            "[claude]",
            f'modele = "{self.modele_claude}"',
            "",
            "[ollama]",
            f'url = "{self.ollama_url}"',
            f'modele = "{self.modele_ollama}"',
            "",
        ]
        for coffre in self.coffres.values():
            lignes += [
                f"[coffres.{coffre.cle}]",
                "chemin = " + _toml_str(coffre.chemin),
                "nom = " + _toml_str(coffre.nom),
                "dossier_notes = " + _toml_str(coffre.dossier_notes),
                "",
            ]
        cible.write_text("\n".join(lignes), encoding="utf-8")
        self.source = cible
        return cible


def _toml_str(valeur) -> str:
    texte = str(valeur).replace("\\", "/").replace('"', '\\"')
    return '"' + texte + '"'


def _resoudre(brut: str) -> Path:
    return Path(os.path.expandvars(str(brut))).expanduser().resolve()


def _cle_depuis_chemin(chemin: Path) -> str:
    base = chemin.name or "coffre"
    propre = "".join(c.lower() if c.isalnum() else "-" for c in base).strip("-")
    return propre or "coffre"


AIDE = """\
Assistant de MJ - serveur local de lecture du coffre.

  python -m assistant [options]

  --coffre, -c <cle|chemin>   coffre a ouvrir (cle declaree, ou chemin d'un dossier)
  --port <n>                  port d'ecoute (defaut 3011)
  --hote <adresse>            interface d'ecoute (defaut 127.0.0.1)
  --modele <id>               claude-opus-5-5, ou ollama:<modele>
  --aide, -h                  cette aide

Le coffre peut aussi venir de ASSISTANT_COFFRE, ou du fichier de configuration.
"""
