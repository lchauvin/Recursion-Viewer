# DESIGN — Assistant de MJ pour Recursion

Document de conception d'un petit serveur web local qui affiche le coffre Obsidian, permet de le chercher, et y branche un assistant IA pour aider à mener une partie.

**Statut :** proposition, rien n'est construit. À relire et à décider après la première partie de test de *La Ruche silencieuse*.

## 1. Pourquoi

Le coffre Obsidian contient déjà tout le jeu. Deux manques apparaissent à l'usage :

- l'application de bureau de Claude n'ouvre ni les liens locaux ni les liens `obsidian://`, donc les citations de l'assistant ne sont pas cliquables ;
- pendant une partie, il faut jongler entre Obsidian, l'assistant et la table.

L'outil réunit les trois : lire le coffre, le chercher, et discuter avec un assistant qui en connaît le contenu, dans une seule page.

## 2. Ce que l'outil doit faire

1. Afficher n'importe quelle page du coffre, avec ses liens `[[...]]` rendus cliquables.
2. Chercher dans tout le coffre, par mot-clé, et afficher les résultats avec leur contexte.
3. Discuter avec un assistant qui lit les pages pertinentes et cite ses sources par des liens cliquables.
4. Permettre de choisir le modèle : Claude par l'API, ou un modèle local via Ollama.
5. Respecter les consignes de `CLAUDE.md` : citer ses sources, ne pas inventer de règle sans le dire, protéger les secrets, respecter les principes du jeu.

## 3. Ce que l'outil ne doit pas faire

- **Pas d'édition.** Obsidian reste le seul endroit où l'on écrit. L'outil lit, il n'écrit pas. Une exception possible plus tard : écrire des notes de séance dans `10 Notes de l assistant`.
- **Pas de seconde source de vérité.** Aucune base de données, aucune copie des pages. Les fichiers Markdown du coffre sont la référence.
- **Pas de comptes, pas d'hébergement public.** L'outil tourne en local, sur le poste du MJ.
- **Pas de recherche vectorielle.** Le coffre tient dans une fenêtre de contexte moderne ; une recherche plein texte suffit.
- **Pas de gestion de personnages ni de jets de dés** dans une première version.

## 4. Principes de conception

- **Le plus simple qui fonctionne.** Si une fonction peut attendre la version suivante, elle attend.
- **Le coffre d'abord.** L'outil doit continuer à marcher si on y ajoute, renomme ou supprime des pages dans Obsidian, sans rien reconfigurer.
- **L'outil ne contient aucune donnée de jeu.** Le coffre est un paramètre, pas une partie du programme. L'outil doit pouvoir ouvrir n'importe quel coffre, y compris celui d'un autre jeu, sans qu'une ligne de code change.
- **Lecture à chaud.** Les fichiers sont relus à chaque requête : pas de cache à invalider, pas de redémarrage après une modification.
- **Un seul fichier de configuration**, et des valeurs par défaut qui marchent sans y toucher.
- **Dégradation douce.** Sans clé d'API et sans Ollama, la lecture et la recherche fonctionnent quand même.

## 5. Architecture

```
Navigateur (une page)
   │  HTTP, localhost
   ▼
Serveur local
   ├── lecture du coffre (fichiers .md)
   ├── recherche plein texte
   └── appel au modèle ─── Claude (API) ou Ollama (local)
```

**Choix techniques proposés**

| Élément | Proposition | Raison |
| --- | --- | --- |
| Langage | Python | Lisible, bibliothèques standard suffisantes |
| Serveur | FastAPI, ou le serveur HTTP de la bibliothèque standard | Léger, bien documenté |
| Interface | Une page HTML, sans framework | Pas de compilation, pas de dépendances |
| Rendu Markdown | Une petite bibliothèque, ou un rendu côté navigateur | Les tableaux et les encadrés doivent s'afficher |
| Modèles | API Claude et API Ollama, derrière une même interface | Un seul réglage à changer |

**Arborescence envisagée**

```
assistant/              # le programme, versionnable, sans donnée de jeu
  config.exemple.toml   # modèle de configuration, livré avec le code
  serveur.py            # routes
  coffre.py             # lecture, index, recherche, liens
  modele.py             # Claude ou Ollama derrière la même interface
  static/
    index.html
    style.css
    app.js

~/Documents/Recursion/  # le coffre, ailleurs, versionné séparément
~/.config/assistant-jdr/config.toml   # la configuration de l'utilisateur
```

Le dossier du programme et le dossier du coffre sont indépendants. On peut mettre l'assistant sous Git sans y embarquer le jeu, et inversement.

## 6. Le coffre en paramètre

Le chemin du coffre n'est jamais écrit dans le code. Il se donne de trois façons, dans cet ordre de priorité :

1. **En ligne de commande :** `assistant --coffre ~/Documents/Recursion`
2. **Par une variable d'environnement :** `ASSISTANT_COFFRE=~/Documents/Recursion`
3. **Dans le fichier de configuration :** `coffre = "~/Documents/Recursion"`

Si aucune des trois n'est fournie, l'outil affiche au démarrage une page qui demande le chemin du coffre, l'enregistre dans la configuration, et continue.

**Plusieurs coffres.** La configuration peut en déclarer plusieurs, avec un nom pour chacun, et l'un d'eux par défaut :

```toml
coffre_par_defaut = "recursion"

[coffres.recursion]
chemin = "~/Documents/Recursion"
nom = "Recursion : l'ère de l'Érosion"

[coffres.campagne-test]
chemin = "~/Documents/Recursion-bac-a-sable"
nom = "Bac à sable"
```

On passe de l'un à l'autre par un menu de l'interface, ou par `--coffre recursion`. Chaque coffre garde ses propres pages épinglées et son propre historique de conversation, rangés hors du coffre, dans le dossier de données de l'utilisateur.

**Ce que l'outil attend d'un coffre.** Rien d'obligatoire : un dossier de fichiers `.md` suffit. L'outil exploite ce qu'il trouve, et se passe du reste.

| Élément | Si présent | Si absent |
| --- | --- | --- |
| Métadonnées en tête de page (`type`, `statut`, `visibilite`, `aliases`) | Filtres de recherche, mode joueurs, alias | Toutes les pages sont traitées comme visibles par le MJ |
| `CLAUDE.md` à la racine | Sert d'instructions système à l'assistant | Instructions génériques par défaut |
| Page d'accueil (`00 Accueil.md` ou équivalent) | Page ouverte au démarrage | Première page de l'arborescence |
| Sous-dossiers | Repris tels quels dans l'arborescence | Liste à plat |

Les noms de dossiers (`03 Regles`, `Modeles`...) ne sont jamais codés en dur : l'outil lit l'arborescence réelle. Les éventuels réglages propres à un coffre (dossier des notes de séance, par exemple) se déclarent dans sa section de configuration, jamais dans le code.

## 7. Le coffre vu par l'outil

**Lecture.** Au démarrage et à chaque requête, l'outil parcourt les fichiers `.md` du coffre. Pour chacun, il lit les métadonnées en tête de fichier (`type`, `statut`, `visibilite`, `aliases`), le titre et le corps.

**Index.** Une table en mémoire : nom de fichier, titre, alias, chemin, métadonnées, texte. Reconstruite quand un fichier a changé de date de modification.

**Liens.** Les `[[Nom]]` et `[[Nom|Titre affiché]]` deviennent des liens vers la page correspondante dans l'outil. Un lien qui ne correspond à aucune page s'affiche en rouge : c'est aussi un moyen de repérer les liens cassés.

**Secrets.** Les encadrés `> [!mj]- Réservé au MJ` sont repliés par défaut. Un bouton « mode joueurs » masque ces encadrés et toutes les pages dont la visibilité est `mj` : de quoi montrer un écran à la table sans rien dévoiler.

## 8. La recherche

Recherche plein texte, sans accents ni casse, sur les titres, les alias et le corps. Les résultats affichent le titre, le chemin et la ligne qui contient le terme. Les titres remontent avant le corps. Filtres simples par `type` et par `visibilite`.

C'est volontairement basique : sur quelques dizaines de pages, c'est instantané et prévisible.

## 9. L'assistant

**Le contexte envoyé au modèle**, à chaque message :

1. `CLAUDE.md` comme instructions système, avec une consigne de citation propre à l'outil (voir plus bas).
2. L'index : la liste des pages avec leur titre, leur chemin et leur type. Court, et suffisant pour que le modèle sache ce qui existe.
3. Les pages pertinentes, en entier.
4. L'historique de la conversation en cours.

**Comment choisir les pages.** Première version : le modèle demande les pages dont il a besoin, par leur nom, et l'outil les lui fournit. Variante plus simple si cela pose problème : l'outil envoie les pages dont le titre ou les alias apparaissent dans la question, plus les pages épinglées par le MJ.

**Les pages épinglées.** Le MJ peut épingler des pages qui seront toujours envoyées, par exemple le scénario en cours et la campagne. Utile pendant une partie.

**La citation.** Dans cet outil, l'assistant cite ses sources avec des liens Markdown ordinaires vers les pages de l'outil, du type `[Le Rêve](/page/03%20Regles/Le%20Reve)`. Ils sont cliquables dans le navigateur, ce qui résout le problème de départ.

**Les modèles.** Une interface commune, deux implémentations :

- **Claude :** appel à l'API, clé lue dans la configuration ou dans l'environnement.
- **Ollama :** appel à `http://localhost:11434`, modèle au choix.

Le modèle se change dans la configuration, ou dans un menu de l'interface. À noter : un modèle local sera plus lent et moins fin pour improviser une scène ; il conviendra surtout aux questions de règles et aux résumés.

## 10. L'interface

Une seule page, deux zones :

- **à gauche**, l'arborescence du coffre et le champ de recherche ;
- **au centre**, la page affichée, ou la conversation avec l'assistant : le bouton « Assistant » de la barre du haut passe de l'une à l'autre, et ouvrir une page (lien, source citée, carte) ramène à la page.

Trois boutons : le mode joueurs, le choix du modèle, et l'épinglage de la page affichée.

Rien d'autre dans une première version. Pas de thème, pas de raccourcis, pas de préférences.

## 11. Étapes

**Version 0 : lire.** Ouvrir un coffre donné en paramètre, afficher les pages, les liens cliquables, l'arborescence. Pas d'IA. Déjà utile.

**Version 1 : chercher.** La recherche plein texte et les filtres.

**Version 2 : l'assistant.** La conversation, l'envoi du contexte, les citations cliquables, Claude et Ollama.

**Version 3 : la table.** Le mode joueurs, les pages épinglées, et éventuellement l'écriture des notes de séance dans le coffre.

Chaque version doit être utilisable seule. Si l'envie ou le temps manque après la version 1, l'outil reste utile.

## 12. Questions à trancher

- [ ] Attendre la première partie avant de commencer : quelles informations ai-je réellement cherchées, et à quelle vitesse en avais-je besoin ?
- [ ] Un assistant pendant la partie aide-t-il, ou casse-t-il le rythme ? À tester d'abord avec Claude dans une fenêtre à côté.
- [ ] Le mode joueurs sert-il vraiment, ou l'écran reste-t-il toujours face au MJ ?
- [x] Faut-il autoriser l'écriture des notes de séance, ou Obsidian suffit-il ? *Tranché : l'assistant propose, le MJ valide d'un clic, et seulement dans les dossiers déclarés (`dossiers_ecriture`). Voir le README, « Ecrire dans le coffre ».*
- [ ] Quel modèle local vaut la peine d'être essayé, et pour quelles tâches ?
- [ ] Ai-je vraiment besoin de plusieurs coffres, ou un seul suffit-il ?

## 13. Risques

- **Construire avant de savoir.** Le principal. Une partie de test coûte une soirée et répond à la plupart des questions ci-dessus.
- **Deux sources de vérité.** Si l'outil se met à écrire sans discipline, le coffre et l'outil divergeront. D'où la règle : Obsidian écrit, l'outil lit.
- **Les secrets à l'écran.** Un assistant qui affiche une page réservée au MJ au mauvais moment. Le mode joueurs doit être testé avant la première utilisation à la table.
- **Le temps de réponse.** Un modèle lent pendant une partie est pire que pas d'assistant du tout. À mesurer avant de s'en servir en jeu.
- **Un outil trop lié à ce coffre.** Si des noms de dossiers ou des particularités de Recursion se glissent dans le code, l'outil devient inutilisable ailleurs et difficile à faire évoluer. Un bon test : l'ouvrir sur un dossier de notes quelconque, et vérifier qu'il fonctionne.
