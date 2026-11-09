/* Assistant de MJ — une seule page, trois zones.
   Aucune dependance : fetch, pushState et un petit rendu Markdown pour les
   reponses de l'assistant. */

(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);

  const el = {
    app: $("#app"),
    amorce: $("#amorce"),
    amorceForm: $("#amorce-form"),
    amorceChemin: $("#amorce-chemin"),
    amorceErreur: $("#amorce-erreur"),
    coffreNom: $("#coffre-nom"),
    choixCoffre: $("#choix-coffre"),
    choixModele: $("#choix-modele"),
    boutonJoueurs: $("#bouton-joueurs"),
    boutonCarte: $("#bouton-carte"),
    boutonSurCarte: $("#bouton-sur-carte"),
    boutonVue: $("#bouton-vue"),
    recherche: $("#champ-recherche"),
    filtreType: $("#filtre-type"),
    filtreVisibilite: $("#filtre-visibilite"),
    epinglesBloc: $("#epingles-bloc"),
    epingles: $("#epingles"),
    navigation: $("#navigation"),
    comptePages: $("#compte-pages"),
    fil: $("#fil"),
    page: $("#page"),
    boutonEpingle: $("#bouton-epingle"),
    lienBrut: $("#lien-brut"),
    conversation: $("#conversation"),
    formQuestion: $("#form-question"),
    question: $("#question"),
    boutonEnvoyer: $("#bouton-envoyer"),
    boutonVider: $("#bouton-vider"),
    etatModele: $("#etat-modele"),
    // Parametres
    boutonParametres: $("#bouton-parametres"),
    parametres: $("#parametres"),
    panneau: $("#parametres .panneau"),
    formParametres: $("#form-parametres"),
    fermerParametres: $("#fermer-parametres"),
    pAnnuler: $("#p-annuler"),
    pModeleClaude: $("#p-modele-claude"),
    pListeClaude: $("#liste-claude"),
    pEffort: $("#p-effort"),
    pCle: $("#p-cle"),
    pCleOllama: $("#p-cle-ollama"),
    pUrl: $("#p-url"),
    pTester: $("#p-tester"),
    pModeleOllama: $("#p-modele-ollama"),
    pListeOllama: $("#liste-ollama"),
    pResultat: $("#p-resultat"),
    pErreur: $("#p-erreur"),
    pCoffre: $("#p-coffre"),
    pAdresse: $("#p-adresse"),
    pConfig: $("#p-config"),
  };

  const etat = {
    pret: false,
    modeJoueurs: false,
    cheminCourant: null,
    epingles: [],
    arbre: null,
    enCours: false,
    modelesClaude: [],
    modelesOllama: [],
    modeleCourant: {},
    // Cartes : la liste du coffre, l'instance affichee, et la derniere vue de
    // chacune, pour la retrouver telle quelle apres un detour par une page.
    cartes: [],
    carte: null,
    carteChemin: null,
    vuesCarte: {},
    vueTableau: false,
    surCarte: null,
    // L'ecriture dans le coffre : propositions de l'assistant, notes du MJ.
    ecriture: { active: false, dossiers: [], notes: "" },
  };

  // ------------------------------------------------------------------ outils

  const echapper = (texte) =>
    String(texte ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  const plier = (texte) =>
    String(texte ?? "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase();

  async function api(chemin, options) {
    const reponse = await fetch(chemin, options);
    const type = reponse.headers.get("content-type") || "";
    const corps = type.includes("json") ? await reponse.json() : await reponse.text();
    if (!reponse.ok && typeof corps === "object") corps.__code = reponse.status;
    return corps;
  }

  const poster = (chemin, donnees) =>
    api(chemin, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(donnees || {}),
    });

  // ------------------------------------------------------------------- etat

  async function chargerEtat() {
    const donnees = await api("/api/etat");
    appliquerEtat(donnees);
    return donnees;
  }

  function appliquerEtat(donnees) {
    etat.pret = !!donnees.pret;

    if (!donnees.coffre) {
      el.amorce.hidden = false;
      el.app.hidden = true;
      return;
    }
    el.amorce.hidden = true;
    el.app.hidden = false;

    etat.modeJoueurs = !!donnees.mode_joueurs;
    etat.epingles = donnees.epingles || [];
    etat.cartes = donnees.cartes || [];
    etat.ecriture = donnees.ecriture || { active: false, dossiers: [], notes: "" };
    el.boutonCarte.hidden = etat.cartes.length === 0;

    el.coffreNom.textContent = donnees.coffre.chemin;
    el.coffreNom.title = donnees.coffre.chemin;
    el.comptePages.textContent =
      (donnees.coffre.pages ?? 0) + " pages" +
      (donnees.coffre.instructions ? " · CLAUDE.md lu" : " · pas de CLAUDE.md");

    // Coffres
    el.choixCoffre.innerHTML = (donnees.coffres || [])
      .map(
        (c) =>
          `<option value="${echapper(c.cle)}"${c.courant ? " selected" : ""}>` +
          `${echapper(c.nom)}${c.existe ? "" : " (absent)"}</option>`
      )
      .join("");

    // Modeles
    const m = donnees.modele || {};
    etat.modeleCourant = m;
    etat.modelesClaude = donnees.modeles_claude || [];
    etat.dernierEtat = donnees;
    rendreChoixModele();

    el.etatModele.textContent = m.disponible ? "pret" : "indisponible";
    el.etatModele.dataset.ton = m.disponible ? "ok" : "alerte";
    el.etatModele.title = m.disponible
      ? `${m.fournisseur} / ${m.identifiant}`
      : m.raison || "";
    el.question.disabled = false;
    el.boutonEnvoyer.disabled = etat.enCours;

    // Mode joueurs
    el.boutonJoueurs.classList.toggle("actif", etat.modeJoueurs);
    el.boutonJoueurs.setAttribute("aria-pressed", String(etat.modeJoueurs));
    document.body.classList.toggle("joueurs", etat.modeJoueurs);

    // Types
    const typeChoisi = el.filtreType.value;
    el.filtreType.innerHTML =
      '<option value="">tous les types</option>' +
      (donnees.types || [])
        .map((t) => `<option value="${echapper(t)}">${echapper(t)}</option>`)
        .join("");
    el.filtreType.value = typeChoisi;
    el.filtreVisibilite.disabled = etat.modeJoueurs;

    rendreEpingles();
    if (donnees.conversation && !el.conversation.dataset.charge) {
      el.conversation.dataset.charge = "1";
      donnees.conversation.forEach((tour) => {
        const bloc = ajouterTour(tour.role, tour.contenu, { markdown: tour.role === "assistant" });
        if (tour.role === "assistant") ajouterActionsTour(bloc, tour.contenu);
      });
      // Les propositions laissees en attente (page rechargee, serveur relance).
      const attente = donnees.propositions || [];
      if (attente.length) {
        const bloc = ajouterTour("assistant", "Propositions en attente de validation :", {});
        attente.forEach((prop) => bloc.appendChild(carteProposition(prop)));
        majToutEnregistrer(bloc);
      }
      defiler();
    }
    return donnees;
  }

  /* Le menu des modeles : ceux de Claude, puis ceux qu'Ollama a installes.
     Un nom Ollama contient un `:` (llama3.1:8b), donc la valeur se decoupe au
     PREMIER deux-points seulement — voir lireValeurModele. */
  function rendreChoixModele() {
    const m = etat.modeleCourant || {};
    const choisi = (fournisseur, id) =>
      m.fournisseur === fournisseur && m.identifiant === id ? " selected" : "";
    const option = (fournisseur, id, libelle) =>
      `<option value="${echapper(fournisseur + ":" + id)}"${choisi(fournisseur, id)}>` +
      `${echapper(libelle || id)}</option>`;

    const claude =
      '<optgroup label="Claude (API)">' +
      etat.modelesClaude.map((id) => option("claude", id)).join("") +
      "</optgroup>";

    // Le modele configure doit rester selectionnable meme si Ollama est eteint.
    const locaux = etat.modelesOllama.slice();
    if (m.fournisseur === "ollama" && m.identifiant && !locaux.includes(m.identifiant)) {
      locaux.unshift(m.identifiant);
    }
    const ollama = locaux.length
      ? '<optgroup label="Ollama (local)">' +
        locaux.map((id) => option("ollama", id)).join("") +
        "</optgroup>"
      : '<optgroup label="Ollama (local)">' +
        '<option value="" disabled>aucun modele detecte</option></optgroup>';

    el.choixModele.innerHTML = claude + ollama;
  }

  function lireValeurModele(valeur) {
    const coupe = valeur.indexOf(":");
    if (coupe === -1) return { fournisseur: valeur, identifiant: "" };
    return { fournisseur: valeur.slice(0, coupe), identifiant: valeur.slice(coupe + 1) };
  }

  /* Interroge Ollama sans bloquer le demarrage : s'il n'est pas lance, le
     menu garde simplement sa liste vide. */
  async function chargerModelesOllama() {
    try {
      const donnees = await api("/api/ollama");
      etat.modelesOllama = donnees.modeles || [];
    } catch {
      etat.modelesOllama = [];
    }
    rendreChoixModele();
  }

  /* ------------------------------------------------------------ parametres */

  function ouvrirParametres() {
    const d = etat.dernierEtat || {};
    const m = etat.modeleCourant || {};
    const fournisseur = m.fournisseur === "ollama" ? "ollama" : "claude";

    el.formParametres.querySelectorAll('input[name="fournisseur"]').forEach((r) => {
      r.checked = r.value === fournisseur;
    });
    el.panneau.dataset.fournisseur = fournisseur;

    el.pModeleClaude.value = d.modele_claude || "";
    el.pListeClaude.innerHTML = (d.modeles_claude || [])
      .map((id) => `<option value="${echapper(id)}">`)
      .join("");

    el.pEffort.innerHTML = (d.efforts || ["low", "medium", "high", "xhigh", "max"])
      .map(
        (e) =>
          `<option value="${echapper(e)}"${e === d.effort ? " selected" : ""}>` +
          `${echapper(e)}</option>`
      )
      .join("");

    const cle = d.cle_api || {};
    el.pCle.textContent = cle.presente ? "detectee · " + cle.source : "absente";
    el.pCle.dataset.ton = cle.presente ? "ok" : "alerte";

    const cleO = d.cle_ollama || {};
    el.pCleOllama.textContent = cleO.presente
      ? "detectee · " + cleO.source
      : "absente (inutile en local)";
    el.pCleOllama.dataset.ton = cleO.presente ? "ok" : "";

    el.pUrl.value = d.ollama_url || "";
    el.pModeleOllama.value = d.modele_ollama || "";
    majListeOllama();

    el.pCoffre.textContent = d.coffre ? d.coffre.chemin : "aucun";
    el.pCoffre.title = el.pCoffre.textContent;
    el.pAdresse.textContent = (d.hote || "") + ":" + (d.port || "");
    el.pConfig.textContent = d.config || "valeurs par defaut";
    el.pConfig.title = el.pConfig.textContent;

    el.pResultat.hidden = true;
    el.pErreur.hidden = true;
    el.parametres.hidden = false;
    el.pModeleClaude.focus();
  }

  const fermerParametres = () => {
    el.parametres.hidden = true;
    el.boutonParametres.focus();
  };

  function majListeOllama() {
    el.pListeOllama.innerHTML = etat.modelesOllama
      .map((id) => `<option value="${echapper(id)}">`)
      .join("");
  }

  async function testerOllama() {
    const url = el.pUrl.value.trim();
    el.pResultat.hidden = false;
    el.pResultat.dataset.ton = "";
    el.pResultat.textContent = "Connexion a " + url + "…";
    el.pTester.disabled = true;
    try {
      const d = await api("/api/ollama?url=" + encodeURIComponent(url));
      if (d.disponible) {
        etat.modelesOllama = d.modeles || [];
        majListeOllama();
        rendreChoixModele();
        el.pResultat.dataset.ton = "ok";
        const choisi = el.pModeleOllama.value.trim();
        el.pResultat.textContent = d.modeles.length
          ? `${d.modeles.length} modele(s) : ${d.modeles.join(", ")}`
          : "Ollama repond, mais aucun modele n'est installe (ollama pull …).";
        // Si le champ est vide, on propose le premier trouve.
        if (!choisi && d.modeles.length) {
          el.pModeleOllama.value = d.modeles[0];
        } else if (choisi && d.modeles.length && !d.modeles.includes(choisi)) {
          // Piege classique : on passe du local au cloud en gardant un modele
          // local, et la question echoue en 404 au moment de la poser.
          el.pResultat.dataset.ton = "alerte";
          el.pResultat.textContent =
            `« ${choisi} » n'existe pas sur ${d.url}. ` +
            `Disponibles : ${d.modeles.slice(0, 8).join(", ")}` +
            (d.modeles.length > 8 ? `, …` : "");
        }
      } else {
        el.pResultat.dataset.ton = "alerte";
        el.pResultat.textContent = d.raison || "Ollama ne repond pas sur " + url;
      }
    } catch (err) {
      el.pResultat.dataset.ton = "alerte";
      el.pResultat.textContent = "Echec du test : " + err.message;
    } finally {
      el.pTester.disabled = false;
    }
  }

  async function enregistrerParametres(ev) {
    ev.preventDefault();
    el.pErreur.hidden = true;
    const fournisseur =
      el.formParametres.querySelector('input[name="fournisseur"]:checked')?.value || "claude";
    const charge = {
      fournisseur,
      modele_claude: el.pModeleClaude.value.trim(),
      modele_ollama: el.pModeleOllama.value.trim(),
      ollama_url: el.pUrl.value.trim(),
      effort: el.pEffort.value,
    };
    const manquant =
      fournisseur === "claude" ? !charge.modele_claude : !charge.modele_ollama || !charge.ollama_url;
    if (manquant) {
      el.pErreur.hidden = false;
      el.pErreur.textContent =
        fournisseur === "claude"
          ? "Indiquez un identifiant de modele Claude."
          : "Indiquez l'URL du serveur Ollama et le nom du modele.";
      return;
    }
    // Un modele absent de l'URL choisie echouerait en 404 a la premiere
    // question : on le dit maintenant, pas en pleine partie.
    if (fournisseur === "ollama") {
      const sonde = await api("/api/ollama?url=" + encodeURIComponent(charge.ollama_url));
      if (
        sonde.disponible &&
        (sonde.modeles || []).length &&
        !sonde.modeles.includes(charge.modele_ollama)
      ) {
        el.pErreur.hidden = false;
        el.pErreur.textContent =
          `« ${charge.modele_ollama} » n'existe pas sur ${sonde.url}. ` +
          `Disponibles : ${sonde.modeles.slice(0, 8).join(", ")}` +
          (sonde.modeles.length > 8 ? ", …" : "");
        return;
      }
    }

    const reponse = await poster("/api/modele", charge);
    if (reponse.erreur) {
      el.pErreur.hidden = false;
      el.pErreur.textContent = reponse.erreur;
      return;
    }
    appliquerEtat(reponse);
    chargerModelesOllama();
    fermerParametres();
  }

  function rendreEpingles() {
    el.epinglesBloc.hidden = etat.epingles.length === 0;
    el.epingles.innerHTML = etat.epingles
      .map(
        (p) =>
          `<li><button class="retirer" data-retirer="${echapper(p.chemin)}" ` +
          `title="Retirer">×</button><a href="${echapper(p.url)}" data-page="${echapper(
            p.chemin
          )}">${echapper(p.titre)}</a></li>`
      )
      .join("");
  }

  // -------------------------------------------------------------- navigation

  async function chargerArbre() {
    etat.arbre = await api("/api/arbre");
    rendreArbre();
  }

  function rendreArbre() {
    if (!etat.arbre) return;
    el.navigation.innerHTML = noeudHtml(etat.arbre, true);
    marquerCourante();
  }

  function noeudHtml(noeud, racine) {
    const pages = (noeud.pages || [])
      .map((p) => {
        const marqueur = p.visibilite ? p.visibilite.slice(0, 2) : "";
        return (
          `<a class="lien-page" href="/page/${encodeURI(p.chemin)}" ` +
          `data-page="${echapper(p.chemin)}" data-visibilite="${echapper(p.visibilite)}" ` +
          `title="${echapper(p.chemin)}">` +
          `<span class="marqueur">${echapper(marqueur)}</span>` +
          `<span>${echapper(p.titre)}</span></a>`
        );
      })
      .join("");

    const dossiers = (noeud.dossiers || [])
      .map(
        (d) =>
          `<details open><summary>${echapper(d.nom)}</summary>` +
          `<div class="enfants">${noeudHtml(d, false)}</div></details>`
      )
      .join("");

    return racine ? dossiers + pages : pages + dossiers;
  }

  function marquerCourante() {
    el.navigation.querySelectorAll(".lien-page").forEach((a) => {
      a.classList.toggle("courante", a.dataset.page === etat.cheminCourant);
    });
  }

  async function ouvrirPage(chemin, pousser = true, options = {}) {
    if (!chemin) return;
    const donnees = await api("/api/page?chemin=" + encodeURIComponent(chemin));
    fermerCarte();
    if (donnees.erreur === "introuvable") {
      el.page.innerHTML =
        `<div class="avis" data-ton="alerte">Aucune page a ce chemin : <code>${echapper(
          chemin
        )}</code></div>`;
      el.fil.innerHTML = "";
      return;
    }
    if (donnees.erreur === "reservee") {
      el.page.innerHTML =
        `<div class="avis" data-ton="alerte">${echapper(donnees.message)}</div>`;
      el.fil.innerHTML = "";
      return;
    }

    etat.cheminCourant = donnees.chemin;
    document.title = donnees.titre + " · Assistant de MJ";
    if (pousser) {
      const lieu = options.focus ? "?lieu=" + encodeURIComponent(options.focus) : "";
      history.pushState(
        { chemin: donnees.chemin, lieu: options.focus || null },
        "",
        "/page/" + encodeURI(donnees.chemin) + lieu
      );
    }

    rendrePage(donnees, options);
    marquerCourante();
    el.page.scrollTop = 0;
  }

  // ------------------------------------------------------------------ cartes

  function fermerCarte() {
    if (etat.carte) {
      etat.vuesCarte[etat.carteChemin] = etat.carte.etat();
      etat.carte.detruire();
      etat.carte = null;
    }
    el.page.classList.remove("page-carte");
  }

  async function afficherCarte(donnees, options = {}) {
    el.page.classList.add("page-carte");
    el.page.innerHTML =
      '<div class="carte-hote"><p class="carte-attente etiquette">Chargement de la carte…</p></div>';
    const carte = await api("/api/carte?chemin=" + encodeURIComponent(donnees.chemin));
    // On a pu changer de page, ou passer au tableau, pendant le chargement.
    if (etat.cheminCourant !== donnees.chemin || etat.vueTableau) return;
    if (carte.erreur || !window.CarteInteractive) {
      el.page.classList.remove("page-carte");
      el.page.innerHTML = `<div class="avis" data-ton="alerte">${echapper(
        carte.message || "Cette carte ne peut pas etre affichee."
      )}</div>`;
      return;
    }
    fermerCarte();
    el.page.classList.add("page-carte");
    const memoire = options.focus ? null : etat.vuesCarte[donnees.chemin];
    etat.carteChemin = donnees.chemin;
    etat.carte = window.CarteInteractive.monter(el.page.querySelector(".carte-hote") || el.page, carte, {
      focus: options.focus || null,
      vue: memoire,
      cartes: etat.cartes.filter((c) => c.chemin !== donnees.chemin),
      ouvrirCarte: (chemin) => {
        etat.vueTableau = false;
        ouvrirPage(chemin);
      },
      selection: memoire ? memoire.selection : null,
      demander: (texte) => {
        el.question.value = texte;
        el.question.dispatchEvent(new Event("input"));
        el.question.focus();
        el.question.setSelectionRange(texte.length, texte.length);
      },
      agrandir: () => document.body.classList.toggle("carte-large"),
    });
    etat.carte.majAgrandi(document.body.classList.contains("carte-large"));
  }

  function rendrePage(donnees, options = {}) {
    etat.surCarte = donnees.sur_carte || null;
    el.boutonSurCarte.hidden = !etat.surCarte;
    el.boutonSurCarte.title = etat.surCarte
      ? "Montrer ce lieu sur « " + etat.surCarte.titre + " »"
      : "";
    el.boutonVue.hidden = !donnees.est_carte;
    el.boutonVue.textContent = etat.vueTableau ? "Carte" : "Tableau";
    if (!donnees.est_carte) document.body.classList.remove("carte-large");
    if (donnees.est_carte && !etat.vueTableau) {
      rendreFil(donnees);
      majEpingle(donnees);
      afficherCarte(donnees, options);
      return;
    }

    const pastilles = [];
    if (donnees.type) pastilles.push(`<span class="pastille">${echapper(donnees.type)}</span>`);
    if (donnees.statut) pastilles.push(`<span class="pastille">${echapper(donnees.statut)}</span>`);
    if (donnees.visibilite)
      pastilles.push(
        `<span class="pastille" data-ton="${echapper(donnees.visibilite)}">` +
          `${echapper(donnees.visibilite)}</span>`
      );
    if (donnees.secrets)
      pastilles.push(
        `<span class="pastille" data-ton="mj">${donnees.secrets} encadre${
          donnees.secrets > 1 ? "s" : ""
        } mj</span>`
      );
    (donnees.alias || []).forEach((a) =>
      pastilles.push(`<span class="pastille">alias ${echapper(a)}</span>`)
    );

    let avis = "";
    if (donnees.liens_casses && donnees.liens_casses.length) {
      avis =
        `<div class="avis" data-ton="alerte"><span class="etiquette">liens casses</span>` +
        `<span>${donnees.liens_casses.map(echapper).join(" · ")}</span></div>`;
    }

    el.page.innerHTML =
      `<header class="entete-page"><h1>${echapper(donnees.titre)}</h1>` +
      `<div class="meta-ligne">${pastilles.join("")}</div></header>` +
      avis +
      donnees.html;

    rendreFil(donnees);
    majEpingle(donnees);
  }

  function rendreFil(donnees) {
    const parties = donnees.chemin.split("/");
    el.fil.innerHTML = parties
      .map((p, i) =>
        i === parties.length - 1
          ? `<span class="actuel">${echapper(p)}</span>`
          : `<span>${echapper(p)}</span><span class="sep">/</span>`
      )
      .join("");
  }

  function majEpingle(donnees) {
    const epinglee = etat.epingles.some((p) => p.chemin === donnees.chemin);
    el.boutonEpingle.textContent = epinglee ? "Desepingler" : "Epingler";
    el.boutonEpingle.classList.toggle("actif", epinglee);
    el.lienBrut.href = "/api/brut?chemin=" + encodeURIComponent(donnees.chemin);
  }

  // ---------------------------------------------------------------- recherche

  let minuteurRecherche = null;

  function lancerRecherche() {
    clearTimeout(minuteurRecherche);
    minuteurRecherche = setTimeout(async () => {
      const q = el.recherche.value.trim();
      if (!q) {
        rendreArbre();
        return;
      }
      const params = new URLSearchParams({ q });
      if (el.filtreType.value) params.set("type", el.filtreType.value);
      if (el.filtreVisibilite.value && !etat.modeJoueurs)
        params.set("visibilite", el.filtreVisibilite.value);
      const donnees = await api("/api/recherche?" + params.toString());
      rendreResultats(donnees.resultats || [], q);
    }, 140);
  }

  function rendreResultats(resultats, q) {
    if (!resultats.length) {
      el.navigation.innerHTML = `<p class="vide">Rien pour « ${echapper(q)} ».</p>`;
      return;
    }
    const termes = q.split(/\s+/).filter(Boolean);
    el.navigation.innerHTML =
      `<p class="etiquette" style="padding:7px 11px">${resultats.length} resultat(s)</p>` +
      '<ul class="resultats">' +
      resultats
        .map((r) => {
          const extraits = (r.extraits || [])
            .map(
              (e) =>
                `<div class="extrait">${surligner(e.texte, termes)}</div>`
            )
            .join("");
          return (
            `<li><a href="/page/${encodeURI(r.chemin)}" data-page="${echapper(r.chemin)}">` +
            `<div class="titre-res">${echapper(r.titre)}</div>` +
            `<div class="chemin-res">${echapper(r.chemin)}</div>` +
            extraits +
            `</a></li>`
          );
        })
        .join("") +
      "</ul>";
  }

  function surligner(texte, termes) {
    let sortie = echapper(texte);
    const plie = plier(sortie);
    const zones = [];
    termes.forEach((terme) => {
      const cible = plier(terme);
      if (!cible) return;
      let i = plie.indexOf(cible);
      while (i !== -1) {
        zones.push([i, i + cible.length]);
        i = plie.indexOf(cible, i + cible.length);
      }
    });
    if (!zones.length) return sortie;
    zones.sort((a, b) => a[0] - b[0]);
    const fusion = [];
    zones.forEach((z) => {
      const dernier = fusion[fusion.length - 1];
      if (dernier && z[0] <= dernier[1]) dernier[1] = Math.max(dernier[1], z[1]);
      else fusion.push([...z]);
    });
    let resultat = "";
    let curseur = 0;
    fusion.forEach(([debut, fin]) => {
      resultat += sortie.slice(curseur, debut) + "<mark>" + sortie.slice(debut, fin) + "</mark>";
      curseur = fin;
    });
    return resultat + sortie.slice(curseur);
  }

  // ------------------------------------------------- rendu Markdown (reponses)

  /* Un modele sans outils ecrit ses propositions en blocs ```page / ```ajout :
     dans la reponse, on les remplace par un renvoi vers la carte de
     proposition, affichee sous le texte. */
  const BLOC_PROPOSITION = /^(`{3,})(page|ajout)[ \t]+([^\n]*)\n[\s\S]*?\n\1[ \t]*$/gm;
  function sansBlocsProposition(texte) {
    return String(texte || "").replace(BLOC_PROPOSITION, (_, __, genre, attrs) => {
      const cible = (attrs.match(/(?:chemin|page)\s*=\s*"([^"]*)"/) || [])[1] || "";
      return `*↳ proposition : ${genre === "page" ? "nouvelle page" : "ajout a"} « ${cible} », ci-dessous.*`;
    });
  }

  function markdown(texte) {
    const lignes = String(texte || "").replace(/\r\n/g, "\n").split("\n");
    const sortie = [];
    let i = 0;
    let dansCode = false;
    let tampon = [];

    const viderTampon = () => {
      if (tampon.length) {
        sortie.push("<p>" + enLigne(tampon.join(" ")) + "</p>");
        tampon = [];
      }
    };

    while (i < lignes.length) {
      const ligne = lignes[i];

      if (/^\s*```/.test(ligne)) {
        viderTampon();
        if (!dansCode) {
          dansCode = true;
          sortie.push("<pre><code>");
        } else {
          dansCode = false;
          sortie.push("</code></pre>");
        }
        i++;
        continue;
      }
      if (dansCode) {
        sortie.push(echapper(ligne) + "\n");
        i++;
        continue;
      }

      if (!ligne.trim()) {
        viderTampon();
        i++;
        continue;
      }

      const titre = ligne.match(/^(#{1,6})\s+(.*)$/);
      if (titre) {
        viderTampon();
        const n = Math.min(titre[1].length + 1, 6);
        sortie.push(`<h${n}>${enLigne(titre[2])}</h${n}>`);
        i++;
        continue;
      }

      if (/^\s*([-*+]|\d+[.)])\s+/.test(ligne)) {
        viderTampon();
        const ordonnee = /^\s*\d+[.)]\s+/.test(ligne);
        const balise = ordonnee ? "ol" : "ul";
        sortie.push(`<${balise}>`);
        while (i < lignes.length && /^\s*([-*+]|\d+[.)])\s+/.test(lignes[i])) {
          sortie.push("<li>" + enLigne(lignes[i].replace(/^\s*([-*+]|\d+[.)])\s+/, "")) + "</li>");
          i++;
        }
        sortie.push(`</${balise}>`);
        continue;
      }

      if (/^\s*\|/.test(ligne) && i + 1 < lignes.length && /^[\s|:-]+$/.test(lignes[i + 1])) {
        viderTampon();
        // Un `|` a l'interieur d'un [[lien|titre]], de code en ligne ou
        // echappe `\|` ne separe pas deux cellules.
        const cellules = (l) => {
          let s = l.trim().replace(/^\|/, "");
          if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
          const sortie = [];
          let courant = "";
          let wiki = false;
          let code = false;
          for (let k = 0; k < s.length; k++) {
            if (s[k] === "\\" && s[k + 1] === "|") { courant += "|"; k++; continue; }
            if (s[k] === "`") { code = !code; courant += s[k]; continue; }
            if (!code && !wiki && s.startsWith("[[", k)) { wiki = true; courant += "[["; k++; continue; }
            if (!code && wiki && s.startsWith("]]", k)) { wiki = false; courant += "]]"; k++; continue; }
            if (s[k] === "|" && !wiki && !code) { sortie.push(courant.trim()); courant = ""; continue; }
            courant += s[k];
          }
          sortie.push(courant.trim());
          return sortie;
        };
        const entete = cellules(ligne);
        i += 2;
        const rangees = [];
        while (i < lignes.length && /^\s*\|/.test(lignes[i])) {
          rangees.push(cellules(lignes[i]));
          i++;
        }
        sortie.push(
          "<table><thead><tr>" +
            entete.map((c) => `<th>${enLigne(c)}</th>`).join("") +
            "</tr></thead><tbody>" +
            rangees
              .map((r) => "<tr>" + r.map((c) => `<td>${enLigne(c)}</td>`).join("") + "</tr>")
              .join("") +
            "</tbody></table>"
        );
        continue;
      }

      if (/^\s*>/.test(ligne)) {
        viderTampon();
        const bloc = [];
        while (i < lignes.length && /^\s*>/.test(lignes[i])) {
          bloc.push(lignes[i].replace(/^\s*>\s?/, ""));
          i++;
        }
        sortie.push("<blockquote>" + markdown(bloc.join("\n")) + "</blockquote>");
        continue;
      }

      if (/^\s*(-{3,}|\*{3,})\s*$/.test(ligne)) {
        viderTampon();
        sortie.push("<hr>");
        i++;
        continue;
      }

      tampon.push(ligne.trim());
      i++;
    }
    viderTampon();
    if (dansCode) sortie.push("</code></pre>");
    return sortie.join("");
  }

  function enLigne(texte) {
    const codes = [];
    let sortie = String(texte || "").replace(/`([^`]+)`/g, (_, c) => {
      codes.push(c);
      return "\u0000" + (codes.length - 1) + "\u0000";
    });
    sortie = echapper(sortie);
    // Filet : la consigne dit d'ecrire des liens Markdown, mais un petit modele
    // local retombe souvent dans la syntaxe Obsidian. On la rend cliquable
    // quand meme — ouvrirPage() sait resoudre un nom de page, pas qu'un chemin.
    sortie = sortie.replace(
      /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
      (_, cible, libelle) => {
        const nom = cible.trim();
        const texte = (libelle || nom).trim();
        return `<a class="lien-interne" href="/page/${encodeURI(nom)}" data-page="${nom.replace(
          /"/g, "&quot;"
        )}">${texte}</a>`;
      }
    );
    sortie = sortie.replace(
      /\[([^\]]+)\]\(([^)\s]+)\)/g,
      (_, libelle, url) => {
        const interne = url.startsWith("/page/");
        const attrs = interne
          ? ` data-page="${echapper(decodeURIComponent(url.slice(6)))}"`
          : ' target="_blank" rel="noreferrer noopener"';
        const classe = interne ? "lien-interne" : "lien-externe";
        return `<a class="${classe}" href="${echapper(url)}"${attrs}>${libelle}</a>`;
      }
    );
    sortie = sortie
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
    return sortie.replace(/\u0000(\d+)\u0000/g, (_, n) => "<code>" + echapper(codes[+n]) + "</code>");
  }

  // ------------------------------------------------------------ conversation

  function ajouterTour(role, contenu, options = {}) {
    const bloc = document.createElement("div");
    bloc.className = "tour";
    bloc.dataset.role = role;
    const nom =
      role === "user" ? "MJ" : role === "assistant" ? "Assistant" : "Probleme";
    bloc.innerHTML =
      `<span class="tour-role">${nom}</span><div class="tour-corps"></div>`;
    const corps = bloc.querySelector(".tour-corps");
    if (options.markdown) corps.innerHTML = markdown(role === "assistant" ? sansBlocsProposition(contenu) : contenu);
    else corps.textContent = contenu;
    el.conversation.appendChild(bloc);
    return bloc;
  }

  const defiler = () => {
    el.conversation.scrollTop = el.conversation.scrollHeight;
  };

  async function envoyer(question) {
    if (etat.enCours) return;
    etat.enCours = true;
    el.boutonEnvoyer.disabled = true;

    ajouterTour("user", question);
    const bloc = ajouterTour("assistant", "", { markdown: true });
    const corps = bloc.querySelector(".tour-corps");
    corps.classList.add("curseur");
    const trace = document.createElement("div");
    trace.className = "trace";
    bloc.appendChild(trace);
    defiler();

    let texte = "";
    let fini = false;

    try {
      const reponse = await fetch("/api/conversation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!reponse.ok || !reponse.body) throw new Error("HTTP " + reponse.status);

      const lecteur = reponse.body.getReader();
      const decodeur = new TextDecoder();
      let reste = "";

      while (!fini) {
        const { value, done } = await lecteur.read();
        if (done) break;
        reste += decodeur.decode(value, { stream: true });
        const morceaux = reste.split("\n\n");
        reste = morceaux.pop() || "";
        for (const morceau of morceaux) {
          const ligne = morceau.split("\n").find((l) => l.startsWith("data: "));
          if (!ligne) continue;
          let ev;
          try {
            ev = JSON.parse(ligne.slice(6));
          } catch {
            continue;
          }
          if (ev.type === "texte") {
            texte += ev.texte;
            corps.innerHTML = markdown(sansBlocsProposition(texte));
            defiler();
          } else if (ev.type === "outil") {
            const item = document.createElement("span");
            item.className = "trace-item";
            const propose = ev.nom.startsWith("proposer_");
            item.dataset.genre = ev.nom === "lire_page" ? "lecture" : propose ? "ecriture" : "recherche";
            const cible = ev.entree?.chemin || ev.entree?.page || ev.entree?.requete || "";
            item.textContent =
              (ev.nom === "lire_page" ? "lit " : propose ? "propose " : "cherche ") + cible;
            trace.appendChild(item);
            defiler();
          } else if (ev.type === "proposition") {
            bloc.appendChild(carteProposition(ev.proposition));
            majToutEnregistrer(bloc);
            defiler();
          } else if (ev.type === "proposition_refusee") {
            const refus = document.createElement("div");
            refus.className = "proposition refusee";
            refus.innerHTML =
              `<span class="etiquette">proposition refusee</span>` +
              `<code>${echapper(ev.chemin || "?")}</code><p>${echapper(ev.raison)}</p>`;
            bloc.appendChild(refus);
            defiler();
          } else if (ev.type === "sources") {
            const bande = document.createElement("div");
            bande.className = "sources";
            bande.innerHTML =
              '<span class="etiquette">sources</span>' +
              ev.pages
                .map(
                  (p) =>
                    `<a href="${echapper(p.url)}" data-page="${echapper(p.chemin)}">` +
                    `${echapper(p.titre)}</a>`
                )
                .join("");
            bloc.appendChild(bande);
            defiler();
          } else if (ev.type === "erreur") {
            ajouterTour("erreur", ev.texte);
            defiler();
          } else if (ev.type === "clos") {
            fini = true;
          }
        }
      }
    } catch (err) {
      ajouterTour("erreur", "Le flux a ete interrompu : " + err.message);
    } finally {
      corps.classList.remove("curseur");
      if (!texte.trim() && !corps.textContent.trim() && !bloc.querySelector(".proposition")) bloc.remove();
      else if (texte.trim()) ajouterActionsTour(bloc, texte);
      etat.enCours = false;
      el.boutonEnvoyer.disabled = false;
      el.question.focus();
      defiler();
    }
  }

  // -------------------------------------------------------------- ecriture

  const GENRES = { creation: "nouvelle page", modification: "modification" };

  function separerEntete(contenu) {
    const m = String(contenu || "").match(/^---\n([\s\S]*?)\n---\n?/);
    if (!m) return { meta: "", corps: contenu || "" };
    const meta = m[1]
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .join(" · ");
    return { meta, corps: contenu.slice(m[0].length) };
  }

  /* La carte d'une proposition : ce qui serait ecrit, et ou. Rien n'est ecrit
     avant le clic sur « Enregistrer dans le coffre ». */
  function carteProposition(prop) {
    const carte = document.createElement("div");
    carte.className = "proposition";
    carte.dataset.id = prop.id;
    let apercu = "";
    let brut = "";
    if (prop.genre === "creation") {
      const { meta, corps } = separerEntete(prop.contenu);
      apercu =
        (meta ? `<p class="prop-meta">${echapper(meta)}</p>` : "") +
        `<div class="prop-rendu">${markdown(corps)}</div>`;
      brut = prop.contenu;
    } else {
      const ou = prop.ancien
        ? ""
        : `<p class="prop-meta">ajout ${prop.section ? "a la fin de la section « " + echapper(prop.section) + " »" : "a la fin de la page"}</p>`;
      apercu =
        ou +
        (prop.ancien ? `<pre class="prop-ancien">${echapper(prop.ancien)}</pre>` : "") +
        `<pre class="prop-nouveau">${echapper(prop.nouveau)}</pre>`;
      brut = prop.nouveau;
    }
    carte.innerHTML =
      `<header class="prop-tete">
         <span class="etiquette">proposition · ${GENRES[prop.genre] || prop.genre}</span>
         <code class="prop-chemin" title="${echapper(prop.chemin)}">${echapper(prop.chemin)}</code>
       </header>
       ${prop.resume ? `<p class="prop-resume">${echapper(prop.resume)}</p>` : ""}
       <div class="prop-apercu">${apercu}</div>
       <textarea class="prop-texte" spellcheck="false" hidden></textarea>
       <footer class="prop-actions">
         <button type="button" class="bouton bouton-primaire bouton-petit" data-prop="enregistrer">Enregistrer dans le coffre</button>
         <button type="button" class="bouton bouton-petit" data-prop="retoucher">Retoucher</button>
         <button type="button" class="bouton bouton-petit" data-prop="ignorer">Ignorer</button>
       </footer>
       <p class="prop-etat" hidden></p>`;
    carte.querySelector(".prop-texte").value = brut;
    return carte;
  }

  function majToutEnregistrer(bloc) {
    const enAttente = bloc.querySelectorAll(".proposition[data-id]:not(.faite)").length;
    let bouton = bloc.querySelector(".prop-tout");
    if (enAttente >= 2 && !bouton) {
      bouton = document.createElement("button");
      bouton.type = "button";
      bouton.className = "bouton bouton-petit prop-tout";
      bouton.dataset.prop = "tout";
      bloc.appendChild(bouton);
    }
    if (bouton) {
      bouton.hidden = enAttente < 2;
      bouton.textContent = `Tout enregistrer (${enAttente})`;
      bloc.appendChild(bouton);
    }
  }

  function etatCarte(carte, texte, ton) {
    const p = carte.querySelector(".prop-etat");
    p.hidden = false;
    p.dataset.ton = ton || "";
    p.innerHTML = texte;
  }

  async function enregistrerCarte(carte) {
    if (carte.classList.contains("faite") || carte.classList.contains("en-cours")) return false;
    carte.classList.add("en-cours");
    const zone = carte.querySelector(".prop-texte");
    const charge = { id: carte.dataset.id };
    // Le texte retouche par le MJ remplace la proposition.
    if (!zone.hidden) charge.contenu = zone.value;
    const reponse = await poster("/api/ecrire", charge);
    carte.classList.remove("en-cours");
    if (reponse.erreur) {
      etatCarte(carte, echapper(reponse.erreur), "alerte");
      return false;
    }
    carte.classList.add("faite");
    carte.querySelector(".prop-actions").remove();
    zone.hidden = true;
    etatCarte(
      carte,
      `Enregistree dans le coffre : <a href="${echapper(reponse.url)}" data-page="${echapper(
        reponse.chemin
      )}">${echapper(reponse.titre)}</a>`,
      "ok"
    );
    await chargerArbre();
    if (etat.cheminCourant === reponse.chemin) ouvrirPage(reponse.chemin, false);
    return true;
  }

  async function actionProposition(bouton) {
    const action = bouton.dataset.prop;
    if (action === "tout") {
      const bloc = bouton.closest(".tour");
      bouton.disabled = true;
      for (const carte of bloc.querySelectorAll(".proposition[data-id]:not(.faite)")) {
        await enregistrerCarte(carte);
      }
      bouton.disabled = false;
      majToutEnregistrer(bloc);
      return;
    }
    const carte = bouton.closest(".proposition");
    if (!carte) return;
    if (action === "enregistrer") {
      await enregistrerCarte(carte);
      majToutEnregistrer(carte.closest(".tour"));
    } else if (action === "retoucher") {
      const zone = carte.querySelector(".prop-texte");
      zone.hidden = !zone.hidden;
      carte.querySelector(".prop-apercu").hidden = !zone.hidden;
      bouton.textContent = zone.hidden ? "Retoucher" : "Apercu";
      if (!zone.hidden) {
        zone.style.height = Math.min(zone.scrollHeight + 4, window.innerHeight * 0.5) + "px";
        zone.focus();
      }
    } else if (action === "ignorer") {
      await poster("/api/proposition/ignorer", { id: carte.dataset.id });
      carte.classList.add("faite", "ignoree");
      carte.querySelector(".prop-actions").remove();
      carte.querySelector(".prop-texte").hidden = true;
      etatCarte(carte, "Ignoree : rien n'a ete ecrit.");
      majToutEnregistrer(carte.closest(".tour"));
    }
  }

  // « Enregistrer comme note » : la reponse, telle quelle, dans le dossier de notes.
  function ajouterActionsTour(bloc, texte) {
    if (bloc.querySelector(".tour-actions")) return;
    const barre = document.createElement("div");
    barre.className = "tour-actions";
    barre.innerHTML =
      '<button type="button" class="lien-action" data-note>Enregistrer comme note</button>';
    bloc.texteBrut = texte;
    bloc.appendChild(barre);
  }

  function nomDeFichier(texte) {
    return String(texte || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/['’]/g, " ")
      .replace(/[^A-Za-z0-9 -]+/g, " ")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 7)
      .join(" ");
  }

  function versObsidian(texte) {
    // Les liens de l'outil deviennent des liens Obsidian, cliquables dans le coffre.
    return sansBlocsProposition(texte).replace(/\[([^\]]+)\]\(\/page\/([^)\s]+)\)/g, (_, libelle, chemin) => {
      let nom = chemin;
      try { nom = decodeURIComponent(chemin); } catch {}
      nom = nom.split("/").pop();
      return nom === libelle ? `[[${nom}]]` : `[[${nom}|${libelle}]]`;
    });
  }

  function ouvrirNote(bouton) {
    const bloc = bouton.closest(".tour");
    if (bloc.querySelector(".note-form")) return;
    let question = bloc.previousElementSibling;
    while (question && question.dataset.role !== "user") question = question.previousElementSibling;
    const sujet = nomDeFichier(question ? question.querySelector(".tour-corps").textContent : "") || "Note";
    const date = new Date().toISOString().slice(0, 10);
    const titre = question ? question.querySelector(".tour-corps").textContent.trim().slice(0, 90) : sujet;
    const contenu =
      `---\ntype: note\nstatut: brouillon\nvisibilite: mj\n---\n\n# ${titre}\n\n` +
      versObsidian(bloc.texteBrut || "").trim() + "\n";
    const form = document.createElement("form");
    form.className = "proposition note-form";
    form.innerHTML =
      `<header class="prop-tete"><span class="etiquette">enregistrer comme note</span></header>
       <label class="prop-champ"><span class="etiquette">chemin</span>
         <input type="text" class="note-chemin" spellcheck="false"></label>
       <textarea class="prop-texte" spellcheck="false"></textarea>
       <footer class="prop-actions">
         <button type="submit" class="bouton bouton-primaire bouton-petit">Enregistrer dans le coffre</button>
         <button type="button" class="bouton bouton-petit" data-annuler>Annuler</button>
       </footer>
       <p class="prop-etat" hidden></p>`;
    form.querySelector(".note-chemin").value = `${etat.ecriture.notes}/${date} ${sujet}`;
    const zone = form.querySelector(".prop-texte");
    zone.value = contenu;
    bloc.appendChild(form);
    zone.style.height = Math.min(zone.scrollHeight + 4, window.innerHeight * 0.4) + "px";
    form.querySelector("[data-annuler]").addEventListener("click", () => form.remove());
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const reponse = await poster("/api/ecrire", {
        chemin: form.querySelector(".note-chemin").value,
        contenu: zone.value,
      });
      if (reponse.erreur) return etatCarte(form, echapper(reponse.erreur), "alerte");
      form.classList.add("faite");
      form.querySelector(".prop-actions").remove();
      zone.hidden = true;
      etatCarte(
        form,
        `Note enregistree : <a href="${echapper(reponse.url)}" data-page="${echapper(reponse.chemin)}">${echapper(
          reponse.titre
        )}</a>`,
        "ok"
      );
      chargerArbre();
    });
    defiler();
  }

  // ------------------------------------------------------------- evenements

  document.addEventListener("click", async (ev) => {
    const prop = ev.target.closest("[data-prop]");
    if (prop) {
      ev.preventDefault();
      return actionProposition(prop);
    }
    const note = ev.target.closest("[data-note]");
    if (note) {
      ev.preventDefault();
      return ouvrirNote(note);
    }
    const retirer = ev.target.closest("[data-retirer]");
    if (retirer) {
      ev.preventDefault();
      appliquerEtat(await poster("/api/epingle", { chemin: retirer.dataset.retirer }));
      if (etat.cheminCourant) ouvrirPage(etat.cheminCourant, false);
      return;
    }

    const lien = ev.target.closest("a");
    if (!lien) return;

    // Tout lien interne vers une page s'ouvre dans la colonne centrale.
    const vers = lien.dataset.page
      ? lien.dataset.page
      : lien.getAttribute("href")?.startsWith("/page/")
      ? decodeURIComponent(lien.getAttribute("href").slice("/page/".length))
      : null;
    if (vers !== null && vers !== undefined && !lien.target) {
      ev.preventDefault();
      ouvrirPage(vers);
    }
  });

  el.recherche.addEventListener("input", lancerRecherche);
  el.filtreType.addEventListener("change", lancerRecherche);
  el.filtreVisibilite.addEventListener("change", lancerRecherche);

  el.boutonJoueurs.addEventListener("click", async () => {
    appliquerEtat(await poster("/api/mode-joueurs", { actif: !etat.modeJoueurs }));
    await chargerArbre();
    el.recherche.value = "";
    if (etat.cheminCourant) ouvrirPage(etat.cheminCourant, false);
  });

  el.boutonCarte.addEventListener("click", () => {
    if (!etat.cartes.length) return;
    etat.vueTableau = false;
    ouvrirPage(etat.cartes[0].chemin);
  });

  el.boutonSurCarte.addEventListener("click", () => {
    if (!etat.surCarte) return;
    etat.vueTableau = false;
    ouvrirPage(etat.surCarte.carte, true, { focus: etat.surCarte.noeud });
  });

  el.boutonVue.addEventListener("click", () => {
    etat.vueTableau = !etat.vueTableau;
    if (etat.cheminCourant) ouvrirPage(etat.cheminCourant, false);
  });

  el.boutonEpingle.addEventListener("click", async () => {
    if (!etat.cheminCourant) return;
    appliquerEtat(await poster("/api/epingle", { chemin: etat.cheminCourant }));
    ouvrirPage(etat.cheminCourant, false);
  });

  el.choixCoffre.addEventListener("change", async () => {
    appliquerEtat(await poster("/api/coffre", { cle: el.choixCoffre.value }));
    delete el.conversation.dataset.charge;
    el.conversation.innerHTML = "";
    await demarrer(true);
  });

  el.choixModele.addEventListener("change", async () => {
    if (!el.choixModele.value) return;
    const { fournisseur, identifiant } = lireValeurModele(el.choixModele.value);
    appliquerEtat(await poster("/api/modele", { fournisseur, identifiant }));
    // Ollama a pu etre lance entre-temps : on rafraichit la liste.
    if (fournisseur === "ollama") chargerModelesOllama();
  });

  el.boutonParametres.addEventListener("click", ouvrirParametres);
  el.fermerParametres.addEventListener("click", fermerParametres);
  el.pAnnuler.addEventListener("click", fermerParametres);
  el.pTester.addEventListener("click", testerOllama);
  el.formParametres.addEventListener("submit", enregistrerParametres);
  el.formParametres.querySelectorAll('input[name="fournisseur"]').forEach((r) =>
    r.addEventListener("change", () => {
      el.panneau.dataset.fournisseur = r.value;
    })
  );
  // Un clic sur le voile, en dehors du panneau, ferme aussi.
  el.parametres.addEventListener("click", (ev) => {
    if (ev.target === el.parametres) fermerParametres();
  });

  el.boutonVider.addEventListener("click", async () => {
    await poster("/api/conversation/vider", {});
    el.conversation.innerHTML = "";
  });

  el.formQuestion.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const question = el.question.value.trim();
    if (!question) return;
    el.question.value = "";
    el.question.style.height = "";
    envoyer(question);
  });

  el.question.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      el.formQuestion.requestSubmit();
    }
  });

  el.question.addEventListener("input", () => {
    el.question.style.height = "auto";
    el.question.style.height = Math.min(el.question.scrollHeight, window.innerHeight * 0.4) + "px";
  });

  el.amorceForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    el.amorceErreur.hidden = true;
    const reponse = await poster("/api/coffre-nouveau", { chemin: el.amorceChemin.value });
    if (reponse.erreur) {
      el.amorceErreur.textContent = reponse.erreur;
      el.amorceErreur.hidden = false;
      return;
    }
    appliquerEtat(reponse);
    await demarrer(true);
  });

  window.addEventListener("popstate", (ev) => {
    const chemin = ev.state?.chemin || cheminDeUrl();
    const lieu = ev.state ? ev.state.lieu : lieuDeUrl();
    if (chemin) ouvrirPage(chemin, false, { focus: lieu || null });
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !el.parametres.hidden) {
      ev.preventDefault();
      fermerParametres();
      return;
    }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
      ev.preventDefault();
      el.recherche.focus();
      el.recherche.select();
    }
  });

  // --------------------------------------------------------------- demarrage

  const cheminDeUrl = () =>
    location.pathname.startsWith("/page/")
      ? decodeURIComponent(location.pathname.slice("/page/".length))
      : null;

  const lieuDeUrl = () => new URLSearchParams(location.search).get("lieu");

  async function demarrer(remplacer) {
    const donnees = await chargerEtat();
    if (!donnees.coffre) {
      el.amorceChemin.focus();
      return;
    }
    if (!donnees.pret) {
      el.page.innerHTML = `<div class="avis" data-ton="alerte">${echapper(
        donnees.erreur || "Coffre illisible."
      )}</div>`;
      return;
    }
    chargerModelesOllama();
    await chargerArbre();
    const cible = (!remplacer && cheminDeUrl()) || donnees.accueil;
    const lieu = !remplacer && cheminDeUrl() ? lieuDeUrl() : null;
    if (cible) await ouvrirPage(cible, !cheminDeUrl() || !!remplacer, { focus: lieu });
  }

  demarrer(false);
})();
