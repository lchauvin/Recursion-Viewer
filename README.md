# Assistant de MJ

Un petit serveur web local qui affiche un coffre de notes Markdown, le cherche,
et y branche un assistant qui en connait le contenu. Ecrit pour mener des
parties de *Recursion : l'ere de l'Erosion*, mais l'outil ne contient aucune
donnee de jeu : il ouvre n'importe quel dossier de fichiers `.md`.

Conception detaillee : [DESIGN.md](DESIGN.md).

## Demarrer

```
py -m assistant
```

ou, sous Windows, un double-clic sur `lancer.cmd`.

Le navigateur s'ouvre sur `http://localhost:3011/`. Au premier demarrage, si
aucun coffre n'est connu, la page demande le chemin du dossier et l'enregistre.

Rien a installer : le serveur, le rendu Markdown et la recherche n'utilisent
que la bibliotheque standard de Python (3.11 ou plus recent, pour `tomllib`).

### Choisir le coffre

Dans cet ordre de priorite :

```
py -m assistant --coffre "~/Documents/Recursion"     # ligne de commande
set ASSISTANT_COFFRE=C:\Users\...\Documents\Recursion # environnement
```

...ou la section `[coffres.<cle>]` du fichier de configuration. Voir
[config.exemple.toml](config.exemple.toml).

### Options

| Option | Effet |
| --- | --- |
| `--coffre`, `-c` | une cle de coffre declaree, ou le chemin d'un dossier |
| `--port` | port d'ecoute (3011 par defaut) |
| `--hote` | interface d'ecoute (127.0.0.1 par defaut) |
| `--modele` | `claude-opus-5-5`, ou `ollama:<modele>` |
| `--sans-navigateur` | ne pas ouvrir le navigateur au demarrage |
| `--aide`, `-h` | l'aide |

## Les parametres

Le bouton en forme d'engrenage, en haut a droite, ouvre la page de parametres
du modele. Elle contient :

| Reglage | Pour quoi |
| --- | --- |
| Fournisseur | Claude (API) ou Ollama (local) |
| Modele Claude | l'identifiant exact, par exemple `claude-opus-5-5` |
| Effort de reflexion | `low` a `max` : plus haut, plus fin et plus lent |
| Cle d'API | affiche seulement si elle est detectee, et d'ou elle vient |
| URL du serveur Ollama | `http://localhost:11434`, `https://ollama.com`, ou une machine du reseau |
| Modele Ollama | le nom exact rendu par `ollama list`, tag compris |
| Cle d'API Ollama | affichee seulement si elle est detectee, et d'ou elle vient |

Le bouton **Tester** interroge l'URL saisie *avant* d'enregistrer, et affiche
les modeles trouves ; ils alimentent ensuite la saisie semi-automatique du
champ modele. Les reglages de Claude et ceux d'Ollama sont conserves
separement : passer de l'un a l'autre ne perd rien. `Echap` ferme la page.

**Les cles d'API ne se saisissent pas ici**, volontairement : voir la section
suivante.

Si le modele choisi n'existe pas a l'URL indiquee, l'enregistrement est refuse
et la liste des modeles disponibles s'affiche. C'est le piege classique quand
on passe du local au cloud en gardant un modele local : la question echouerait
en 404 au pire moment.

L'adresse d'ecoute et le port se changent en ligne de commande ou dans le
fichier de configuration, pas depuis la page : ils demandent un redemarrage.

## Les cles d'API

Elles se mettent dans vos variables d'environnement, ou dans un fichier `.env`
a la racine du projet. Modele a copier : [.env.example](.env.example).

```
ANTHROPIC_API_KEY=sk-ant-...        # pour Claude
OLLAMA_API_KEY=...                  # pour Ollama Cloud, ou un Ollama protege
```

| Service | Variables reconnues |
| --- | --- |
| Claude | `ANTHROPIC_API_KEY`, `CLAUDE_API_KEY` |
| Ollama | `OLLAMA_API_KEY`, `OLLAMA_KEY`, `OLLAMA_TOKEN` |

Ordre de priorite : variables d'environnement du systeme, puis le fichier
designe par `ASSISTANT_ENV`, puis le `.env` du projet, du dossier courant et
du dossier de configuration. Le serveur lit les cles au demarrage : relancez-le
apres en avoir change une.

**Ce que l'outil ne fait jamais** avec une cle : la recopier dans
`config.toml`, la renvoyer par l'API, l'afficher dans l'interface ou la
journaliser. La page de parametres dit seulement si une cle a ete trouvee et
dans quelle variable. La cle Ollama n'est envoyee qu'a l'URL configuree dans
`[ollama]`, en en-tete `Authorization: Bearer`.

## L'assistant

L'assistant marche avec Claude par l'API, ou avec un modele local via Ollama.
**Les deux sont optionnels** : sans l'un ni l'autre, la lecture et la recherche
fonctionnent quand meme, et l'interface explique ce qui manque.

### Claude

```
pip install anthropic
```

...puis `ANTHROPIC_API_KEY` dans vos variables d'environnement ou votre `.env`
(voir [Les cles d'API](#les-cles-dapi)).

Modele par defaut : `claude-opus-5-5`, avec la reflexion adaptative et un
effort `medium` (reglable par `effort` dans la configuration : `low` a `max`).
Claude demande lui-meme les pages dont il a besoin, par leur nom, et l'outil
les lui fournit ; les pages consultees s'affichent sous chaque reponse.

### Ollama

```
ollama serve
ollama pull llama3.1:8b
```

**Choisir le modele.** Le menu « modele » de l'interface liste automatiquement
tout ce qu'Ollama a d'installe, sous un groupe « Ollama (local) » : il suffit
d'en choisir un, et le choix est enregistre. La liste est relue au demarrage
et a chaque changement de modele, donc un `ollama pull` en cours de route
apparait apres un rechargement de la page.

Les deux autres moyens, quand l'interface n'est pas pratique :

```
py -m assistant --modele ollama:llama3.1:8b     # pour ce lancement
```

...ou la section `[ollama]` de la configuration :

```toml
fournisseur = "ollama"

[ollama]
url = "http://localhost:11434"
modele = "llama3.1:8b"
```

Donnez le nom exact rendu par `ollama list`, **tag compris** (`llama3.1:8b`,
pas `llama3.1`, sauf si c'est le nom reel). L'URL se change pour joindre un
Ollama qui tourne sur une autre machine du reseau.

**Ollama Cloud.** Mettez `url = "https://ollama.com"` et une cle dans
`OLLAMA_API_KEY` (voir [Les cles d'API](#les-cles-dapi)). La liste des modeles
du cloud est publique, mais poser une question sans cle renvoie un 401 ; les
modeles y sont differents de ceux installes en local, et l'outil refuse
d'enregistrer un modele qui n'existe pas a l'URL choisie.

Si Ollama n'est pas lance, le menu affiche « aucun modele detecte » et la
pastille passe a « indisponible » avec la raison ; la lecture et la recherche
continuent de fonctionner.

**Ce qu'un modele local recoit.** Il n'a pas d'outils et ne peut donc rien
demander : les pages lui sont fournies d'avance, **autant que le budget de
contexte le permet**, les plus pertinentes d'abord (pages epinglees, puis
celles nommees dans la question, puis les meilleurs resultats de la recherche,
puis le reste). Le coffre de Recursion fait environ 134 000 caracteres : il
passe donc en entier, ce que DESIGN 3 anticipait, et aucune page ne peut
manquer.

```toml
contexte_max = 200000   # en caracteres, environ 4 par token
```

A baisser pour un petit modele local : un modele a 8 000 tokens de contexte
veut plutot `contexte_max = 20000`. Au-dela du budget, les pages les moins
pertinentes sont ecartees, jamais tronquees en plein milieu.

Les consignes envoyees s'adaptent : on ne parle d'outils qu'a un modele qui en
a. Sinon il annonce « je vais consulter telle page » et s'arrete la, puisque
rien ne viendra. C'est moins fin que Claude pour improviser une scene, et tres
correct pour une question de regle ou un resume.

### Les citations

Dans ses reponses, l'assistant cite ses sources par des liens cliquables vers
les pages de l'outil (`[Le Reve](/page/03%20Regles/Le%20Reve)`). Un clic ouvre
la page dans la colonne centrale : c'est le probleme que cet outil resout.

## Le coffre

Rien n'est obligatoire : un dossier de fichiers `.md` suffit. L'outil exploite
ce qu'il trouve et se passe du reste.

| Element | S'il est present | S'il est absent |
| --- | --- | --- |
| Metadonnees (`type`, `statut`, `visibilite`, `aliases`) | filtres de recherche, mode joueurs, alias | toutes les pages sont traitees comme reservees au MJ |
| `CLAUDE.md` a la racine | sert d'instructions systeme a l'assistant | instructions generiques par defaut |
| Sous-dossiers | repris tels quels dans l'arborescence | liste a plat |

Les noms de dossiers ne sont jamais codes en dur : l'outil lit l'arborescence
reelle. Les fichiers sont relus a chaque requete, donc une page ajoutee,
renommee ou supprimee dans Obsidian apparait sans redemarrer.

**L'outil ne modifie jamais le coffre.** Obsidian ecrit, l'outil lit. Les
pages epinglees, le mode joueurs et l'historique de conversation sont ranges
hors du coffre, dans le dossier de donnees de l'utilisateur.

## La carte

Une page de metadonnee `type: carte` s'affiche comme une carte interactive
plutot que comme du texte. Ses lieux sont les lignes de ses tableaux Markdown :
la carte se modifie dans Obsidian, comme le reste du coffre, et se relit a
chaque ouverture. Le coffre de Recursion en a deux : le systeme solaire
(`02 Univers/Carte.md`) et le Reve (`02 Univers/Carte du Reve.md`).

```
| Lieu                 | Dans      | Forme   | Orbite | Angle | Taille | Note        |
| -------------------- | --------- | ------- | ------ | ----- | ------ | ----------- |
| Le Soleil            |           | etoile  | 0      |       | 8      | Au centre.  |
| La Terre             | Le Soleil | planete | 62     | 215   | 3      |             |
| [[Le Sanctuaire]]    | La Terre  | lieu    | 0.35   | 200   |        |             |
```

| Colonne | Sens |
| --- | --- |
| `Lieu` | seule colonne obligatoire : un nom, ou un lien `[[Page\|Nom]]` vers la page du lieu |
| `Dans` | le lieu parent, par son nom ; vide a la racine |
| `Orbite`, `Angle` | distance au parent, et angle en degres (0 a droite, 90 en haut ; vide = reparti entre freres) |
| `Taille` | rayon du lieu, dans les memes unites |
| `Forme` | dans l'espace : `etoile`, `planete`, `lune`, `ceinture`, `anneau`, `region` ; sur une terre : `continent`, `ville`, `quartier`, `zone` ; des reperes : `ruche`, `station`, `balise`, `flotte`, `signal`, `reve`, `lieu` |
| `Couleur` | `#rrggbb` ou un nom de couleur CSS |
| `Calque` | un nom de calque, affichable ou masquable (vide = calque de base) |
| `Relie` | des lieux vers lesquels tracer un fil, separes par des virgules |
| `Note` | le texte du survol ; vide, c'est le debut de la page liee |

La metadonnee `fond:` de la page choisit le decor : `ciel` (etoiles, par
defaut) ou `brume` (un monde de songe dore, sans etoiles, ou les fils
deviennent des routes). Quand le coffre a plusieurs cartes, chacune donne
un lien vers les autres.

On zoome a la molette, on se deplace en glissant, un double-clic emmene sur un
lieu. Les enfants d'un lieu n'apparaissent qu'en s'en approchant : on descend
du systeme a la planete, puis au quartier. Un clic ouvre une fiche : la note,
ce que le lieu contient, et trois actions (ouvrir la page, s'y rendre,
preparer une question a l'assistant). Le bouton **Carte** de la barre du haut
ouvre la premiere carte du coffre ; **Sur la carte**, au-dessus d'une page,
montre le lieu qui la porte ; **Tableau** revient au texte de la page.

**Les secrets.** Les tableaux places dans un encadre `> [!mj]` sont reserves
au MJ, comme le reste de l'encadre ; un lieu dont la page est reservee au MJ
aussi. En mode joueurs, le serveur n'envoie ni ces lieux, ni ce qu'ils
contiennent, ni leurs fils. Rangez donc un lieu secret dans l'encadre plutot
que dans un tableau public : le tableau public reste lisible en mode texte.

## Le mode joueurs

Le bouton « Mode joueurs » prepare l'ecran a etre tourne vers la table. Le
filtrage est fait par le serveur, pas par le navigateur : les pages dont la
visibilite est `mj` et les encadres `> [!mj]` ne sont pas envoyes du tout, et
l'assistant lui-meme perd l'acces a ces pages. Un liseré orange rappelle que
le mode est actif.

## Raccourcis

| Raccourci | Effet |
| --- | --- |
| `Ctrl` + `K` | aller au champ de recherche |
| `Entree` | envoyer la question |
| `Maj` + `Entree` | nouvelle ligne dans la question |
| `Echap` | fermer la page de parametres |

## Verifier avant la table

```
py -m assistant.essais                                   # coffre temporaire
py -m assistant.essais --coffre "~/Documents/Recursion"   # et le vrai coffre
```

Les essais ne touchent ni au reseau, ni a la cle d'API, ni au coffre. Ils
verifient surtout les deux risques que le DESIGN demande de lever avant de
s'en servir devant les joueurs : qu'aucun secret ne fuit en mode joueurs
(page, encadre, index, arborescence, recherche, contexte du modele), et que
l'outil fonctionne sur un dossier de notes quelconque.

## Organisation du code

```
assistant/
  __main__.py       point d'entree : python -m assistant
  config.py         configuration, coffres, ligne de commande
  coffre.py         index, arborescence, recherche, resolution des liens
  rendu.py          Markdown -> HTML (metadonnees, tableaux, encadres, [[liens]])
  carte.py          pages `type: carte` : lieux, placement, secrets
  modele.py         Claude et Ollama derriere une meme interface
  assistant_mj.py   contexte envoye au modele, outils, conduite de la conversation
  serveur.py        routes HTTP et flux de conversation
  static/           index.html, style.css, app.js, carte.js (la carte)
config.exemple.toml  modele de configuration
```

Le dossier du programme et le dossier du coffre sont independants : l'assistant
peut etre versionne sans y embarquer le jeu, et inversement.

## Etat des etapes du DESIGN

| Version | Contenu | Etat |
| --- | --- | --- |
| 0 | lire : pages, liens cliquables, arborescence | fait |
| 1 | chercher : plein texte, filtres | fait |
| 2 | l'assistant : conversation, contexte, citations, Claude et Ollama | fait |
| 3 | la table : mode joueurs, pages epinglees | fait, sauf l'ecriture des notes de seance |

L'ecriture des notes de seance dans le coffre reste volontairement non
implementee : c'est la question ouverte 4 du DESIGN, a trancher apres une
partie de test. Le reglage `dossier_notes` est deja lu, pour le jour ou.
