"""Point d'entree : python -m assistant [options]"""

from __future__ import annotations

import sys

from .config import Config
from .serveur import servir


def principal(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    sans_navigateur = "--sans-navigateur" in argv
    argv = [a for a in argv if a != "--sans-navigateur"]
    try:
        cfg = Config.charger(argv)
    except SystemExit as fin:
        return int(fin.code or 0)
    servir(cfg, ouvrir=not sans_navigateur)
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
