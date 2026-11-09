/* Carte interactive : dessine une page `type: carte` du coffre.

   Le serveur envoie des lieux deja places (x, y en unites de la carte) ; ce
   fichier ne connait aucun nom de lieu, seulement des formes.

   Trois couches :
   - le ciel, sur un canvas, avec une legere parallaxe ;
   - le monde, en SVG a l'echelle (orbites, ceintures, anneaux, zones) ;
   - les reperes et les etiquettes, en coordonnees d'ecran, recalcules a
     chaque image : ils gardent une taille lisible a tous les zooms.

   Zoom semantique : les enfants d'un lieu n'apparaissent que lorsque ce lieu
   occupe assez de place a l'ecran. On descend du systeme a la planete, de la
   planete au quartier, sans jamais tout afficher a la fois. */

(() => {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const BANDES = new Set(["ceinture", "anneau", "region"]);
  const CORPS = new Set(["etoile", "planete", "lune"]);
  // Les terres : des taches au contour irregulier, a l'echelle.
  const TERRES = new Set(["continent", "ville", "quartier"]);
  const COULEURS = {
    etoile: "#f6c66a", planete: "#8fa7c0", lune: "#b9bdc6", ceinture: "#8d8577",
    anneau: "#d9cba5", region: "#6b7480", zone: "#5fa98a", ruche: "#d7a94f",
    station: "#9fb6cc", balise: "#a9c6e8", flotte: "#7fb0dd", signal: "#e07b6a",
    reve: "#b48cff", lieu: "#c7ccd4",
    continent: "#c9a86a", ville: "#f0c987", quartier: "#d9c7a3",
  };
  const LIBELLES = {
    etoile: "étoile", planete: "planète", lune: "lune", ceinture: "ceinture",
    anneau: "anneaux", region: "région", zone: "zone", ruche: "ruche",
    station: "station", balise: "balise", flotte: "flotte", signal: "signal",
    reve: "songe", lieu: "lieu",
    continent: "continent", ville: "ville", quartier: "quartier",
  };

  /* Deux decors : le ciel etoile de l'espace, et la brume doree d'un monde
     de songe, sans etoiles. */
  const DECORS = {
    ciel: {
      fond: ["#0d121b", "#05070a"],
      nebuleuses: [
        [0.22, 0.3, 0.45, "rgba(94,155,209,0.07)"],
        [0.78, 0.72, 0.4, "rgba(150,110,220,0.06)"],
      ],
      grains: null,
    },
    brume: {
      fond: ["#2a2236", "#0b0910"],
      nebuleuses: [
        [0.2, 0.25, 0.5, "rgba(240,200,140,0.09)"],
        [0.8, 0.3, 0.45, "rgba(170,140,230,0.09)"],
        [0.55, 0.85, 0.55, "rgba(240,190,130,0.06)"],
        [0.1, 0.8, 0.4, "rgba(120,150,210,0.06)"],
      ],
      grains: ["#ffe2a8", "#e9d6ff"],
    },
  };

  /* Une tache au contour irregulier, reproductible : la somme de quelques
     sinusoides de frequences croissantes autour d'un cercle. */
  function tache(cx, cy, r, graine, rugosite, pas = 120) {
    const hasard = alea(graine);
    const ondes = [];
    for (let i = 2; i <= 9; i++) {
      ondes.push([i, (rugosite * (0.4 + hasard())) / Math.pow(i, 0.9), hasard() * Math.PI * 2]);
    }
    let d = "";
    for (let j = 0; j < pas; j++) {
      const t = (j / pas) * Math.PI * 2;
      let f = 1;
      for (const [i, a, phase] of ondes) f += a * Math.sin(i * t + phase);
      const x = cx + r * f * Math.cos(t);
      const y = cy + r * f * Math.sin(t);
      d += (j ? "L" : "M") + x.toFixed(4) + " " + y.toFixed(4);
    }
    return d + "Z";
  }
  const RAYON_MIN = { etoile: 7, planete: 3.4, lune: 2.4 };

  let compteur = 0;

  // ----------------------------------------------------------------- outils

  const echapper = (texte) =>
    String(texte ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  const creer = (nom, attrs = {}, parent = null) => {
    const e = document.createElementNS(NS, nom);
    for (const cle in attrs) e.setAttribute(cle, attrs[cle]);
    if (parent) parent.appendChild(e);
    return e;
  };

  const mouvementReduit = () =>
    window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function hachage(texte) {
    let h = 2166136261;
    for (let i = 0; i < texte.length; i++) {
      h ^= texte.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  // Un hasard reproductible : la Ceinture garde ses cailloux d'un rendu a l'autre.
  function alea(graine) {
    let s = graine >>> 0 || 1;
    return () => {
      s ^= s << 13; s >>>= 0;
      s ^= s >> 17;
      s ^= s << 5; s >>>= 0;
      return s / 4294967296;
    };
  }

  let pinceau = null;
  function rgb(couleur) {
    if (!pinceau) pinceau = document.createElement("canvas").getContext("2d");
    pinceau.fillStyle = "#c7ccd4";
    pinceau.fillStyle = couleur;
    const v = pinceau.fillStyle;
    if (v.startsWith("#")) {
      return [1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16));
    }
    const m = v.match(/[\d.]+/g);
    return m ? m.slice(0, 3).map(Number) : [199, 204, 212];
  }
  const melange = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
  const css = (c, a = 1) => (a >= 1 ? `rgb(${c.join(",")})` : `rgba(${c.join(",")},${a})`);
  const BLANC = [255, 255, 255];
  const NUIT = [6, 8, 12];

  const borne = (v, a, b) => Math.max(a, Math.min(b, v));
  const lisse = (t) => {
    const x = borne(t, 0, 1);
    return x * x * (3 - 2 * x);
  };
  const entreeSortie = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

  /* Le zoom « en survol » de van Wijk et Nuij, comme d3.interpolateZoom :
     on prend de la hauteur pour traverser, puis on redescend. p = [x, y, w],
     w etant la largeur visible en unites de la carte. */
  function interpolerZoom(p0, p1) {
    const rho = Math.SQRT2, rho2 = 2, rho4 = 4;
    const [ux0, uy0, w0] = p0;
    const [ux1, uy1, w1] = p1;
    const dx = ux1 - ux0, dy = uy1 - uy0, d2 = dx * dx + dy * dy;
    let f, S;
    if (d2 < 1e-12) {
      S = Math.log(w1 / w0) / rho;
      f = (t) => [ux0 + t * dx, uy0 + t * dy, w0 * Math.exp(rho * t * S)];
    } else {
      const d1 = Math.sqrt(d2);
      const b0 = (w1 * w1 - w0 * w0 + rho4 * d2) / (2 * w0 * rho2 * d1);
      const b1 = (w1 * w1 - w0 * w0 - rho4 * d2) / (2 * w1 * rho2 * d1);
      const r0 = Math.log(Math.sqrt(b0 * b0 + 1) - b0);
      const r1 = Math.log(Math.sqrt(b1 * b1 + 1) - b1);
      S = (r1 - r0) / rho;
      f = (t) => {
        const s = t * S;
        const ch = Math.cosh(r0);
        const u = (w0 / (rho2 * d1)) * (ch * Math.tanh(rho * s + r0) - Math.sinh(r0));
        return [ux0 + u * dx, uy0 + u * dy, (w0 * ch) / Math.cosh(rho * s + r0)];
      };
    }
    f.duree = borne(Math.abs(S) * 1000, 450, 1700);
    return f;
  }

  // ------------------------------------------------------------- la carte

  function monter(hote, donnees, options = {}) {
    const pre = "carte" + ++compteur;
    const noeuds = (donnees.noeuds || []).map((n) => ({ ...n }));
    const parId = new Map(noeuds.map((n) => [n.id, n]));
    const ordre = noeuds.slice().sort((a, b) => a.profondeur - b.profondeur);
    const calquesActifs = new Set(donnees.calques || []);
    noeuds.forEach((n) => {
      n.coul = rgb(n.couleur || COULEURS[n.forme] || COULEURS.lieu);
      n.alpha = 0;
    });

    const vue = { k: 1, tx: 0, ty: 0, w: 0, h: 0, dpr: 1 };
    const etat = {
      selection: null,
      survol: null,
      focus: null,
      anim: 0,
      image: 0,
      kMin: 1e-3,
      kMax: 6e4,
      detruit: false,
    };

    // ------------------------------------------------------------ squelette

    hote.innerHTML = "";
    const racine = document.createElement("div");
    racine.className = "carte";
    racine.tabIndex = 0;
    racine.setAttribute("role", "application");
    racine.setAttribute("aria-label", "Carte : " + (donnees.titre || ""));

    const ciel = document.createElement("canvas");
    ciel.className = "carte-ciel";
    const svg = creer("svg", { class: "carte-svg" });
    const defs = creer("defs", {}, svg);
    const gArriere = creer("g", { class: "c-monde" }, svg);
    const gCorps = creer("g", { class: "c-corps" }, svg);
    const gAvant = creer("g", { class: "c-monde" }, svg);
    const gFils = creer("g", { class: "c-fils" }, svg);
    const gNoeuds = creer("g", { class: "c-noeuds" }, svg);
    const gEtiquettes = creer("g", { class: "c-etiquettes" }, svg);
    const anneauChoix = creer("circle", { class: "c-choix", r: 10 }, gNoeuds);

    const gTerres = creer("g", {}, gArriere);
    const gRegions = creer("g", {}, gArriere);
    const gOrbites = creer("g", {}, gArriere);
    const gBandes = creer("g", {}, gArriere);
    const gZones = creer("g", {}, gAvant);
    const gVilles = creer("g", {}, gAvant);
    const gQuartiers = creer("g", {}, gAvant);

    racine.innerHTML =
      `<div class="carte-haut">
         <p class="etiquette carte-compte"></p>
         <nav class="carte-autres" aria-label="Autres cartes"></nav>
         <nav class="carte-ariane" aria-label="Position sur la carte"></nav>
       </div>
       <div class="carte-outils">
         <div class="carte-calques"></div>
         <div class="carte-groupe">
           <button type="button" data-action="moins" title="Dezoomer (-)">−</button>
           <button type="button" data-action="plus" title="Zoomer (+)">+</button>
           <button type="button" data-action="ensemble" title="Vue d'ensemble (0)">
             <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="2"/><circle cx="8" cy="8" r="6"/></svg>
           </button>
           <button type="button" data-action="agrandir" title="Agrandir la carte" aria-pressed="false">
             <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4"/></svg>
           </button>
         </div>
       </div>
       <aside class="carte-fiche" hidden></aside>
       <div class="carte-bulle" hidden></div>
       <div class="carte-bas">
         <span class="carte-aide">molette : zoom · glisser : deplacer · double-clic : s'y rendre</span>
         <details class="carte-erreurs" hidden><summary></summary><ul></ul></details>
       </div>`;
    racine.prepend(svg);
    racine.prepend(ciel);
    hote.appendChild(racine);

    const q = (sel) => racine.querySelector(sel);
    const ui = {
      compte: q(".carte-compte"),
      ariane: q(".carte-ariane"),
      calques: q(".carte-calques"),
      fiche: q(".carte-fiche"),
      bulle: q(".carte-bulle"),
      erreurs: q(".carte-erreurs"),
      agrandir: q('[data-action="agrandir"]'),
    };

    racine.dataset.fond = DECORS[donnees.fond] ? donnees.fond : "ciel";
    const decor = DECORS[racine.dataset.fond];
    const autres = options.cartes || [];
    q(".carte-autres").innerHTML = autres.length
      ? '<span class="etiquette">autres cartes</span>' +
        autres
          .map((c) => `<button type="button" data-carte="${echapper(c.chemin)}">${echapper(c.titre)}</button>`)
          .join("")
      : "";

    const nbSecrets = noeuds.filter((n) => n.secret).length;
    ui.compte.textContent =
      `${donnees.titre || "Carte"} · ${noeuds.length} lieu${noeuds.length > 1 ? "x" : ""}` +
      (nbSecrets ? ` · ${nbSecrets} secret${nbSecrets > 1 ? "s" : ""}` : "");

    ui.calques.innerHTML = (donnees.calques || [])
      .map(
        (c) =>
          `<button type="button" class="carte-calque" data-calque="${echapper(c)}" aria-pressed="true">` +
          `<span class="voyant"></span>${echapper(c)}</button>`
      )
      .join("");

    if ((donnees.erreurs || []).length) {
      ui.erreurs.hidden = false;
      ui.erreurs.querySelector("summary").textContent =
        `${donnees.erreurs.length} probleme${donnees.erreurs.length > 1 ? "s" : ""} dans la page`;
      ui.erreurs.querySelector("ul").innerHTML = donnees.erreurs
        .map((e) => `<li>${echapper(e)}</li>`)
        .join("");
    }

    if (!noeuds.length) {
      const vide = document.createElement("div");
      vide.className = "carte-vide";
      vide.innerHTML =
        "<p>Aucun lieu sur cette carte.</p>" +
        "<p>Ajoutez a la page un tableau avec au moins une colonne <code>Lieu</code>.</p>";
      racine.appendChild(vide);
    }

    // ----------------------------------------------------------- degrades

    function degrade(id, stops, attrs = {}) {
      const g = creer("radialGradient", { id, ...attrs }, defs);
      stops.forEach(([offset, couleur, opacite = 1]) =>
        creer("stop", { offset, "stop-color": couleur, "stop-opacity": opacite }, g)
      );
      return `url(#${id})`;
    }

    // ------------------------------------------------------------ elements

    noeuds.forEach((n, i) => {
      const c = css(n.coul);
      const clair = css(melange(n.coul, BLANC, 0.5));
      n.monde = [];

      // Le monde, a l'echelle
      if (CORPS.has(n.forme) && n.orbite > 0) {
        n.monde.push(
          creer("circle", { class: "c-orbite", cx: n.cx, cy: n.cy, r: n.orbite }, gOrbites)
        );
      }
      if (n.forme === "region") {
        const g = creer("g", {}, gRegions);
        creer("circle", {
          cx: n.cx, cy: n.cy, r: n.orbite, fill: "none", stroke: c,
          "stroke-width": n.taille, "stroke-opacity": 0.075,
        }, g);
        [-1, 1].forEach((s) =>
          creer("circle", {
            class: "c-bord", cx: n.cx, cy: n.cy, r: Math.max(0, n.orbite + (s * n.taille) / 2), stroke: c,
          }, g)
        );
        n.monde.push(g);
      }
      if (n.forme === "ceinture") {
        const g = creer("g", {}, gBandes);
        creer("circle", {
          cx: n.cx, cy: n.cy, r: n.orbite, fill: "none", stroke: c,
          "stroke-width": n.taille, "stroke-opacity": 0.06,
        }, g);
        const hasard = alea(hachage(n.id));
        const total = borne(Math.round(n.taille * 14 + n.orbite * 1.4), 140, 640);
        const lots = [[], [], []];
        for (let p = 0; p < total; p++) {
          // Une gaussienne grossiere : les cailloux se serrent au milieu de la bande.
          const g3 = (hasard() + hasard() + hasard()) / 3 - 0.5;
          const r = n.orbite + g3 * n.taille * 1.15;
          const a = hasard() * Math.PI * 2;
          const x = n.cx + r * Math.cos(a);
          const y = n.cy + r * Math.sin(a);
          lots[hasard() < 0.62 ? 0 : hasard() < 0.75 ? 1 : 2].push(
            `M${x.toFixed(3)} ${y.toFixed(3)}h0.0001`
          );
        }
        [[1.1, 0.35], [1.7, 0.55], [2.4, 0.85]].forEach(([largeur, opacite], j) =>
          creer("path", {
            class: "c-poussiere", d: lots[j].join(""),
            stroke: css(melange(n.coul, BLANC, j * 0.18)),
            "stroke-width": largeur, "stroke-opacity": opacite,
          }, g)
        );
        n.monde.push(g);
      }
      if (n.forme === "anneau") {
        const g = creer("g", {}, gBandes);
        const pas = [0.18, 0.34, 0.12, 0.42, 0.22];
        pas.forEach((opacite, j) => {
          const r = n.orbite - n.taille / 2 + (n.taille * (j + 0.5)) / pas.length;
          creer("circle", {
            cx: n.cx, cy: n.cy, r: Math.max(0, r), fill: "none", stroke: clair,
            "stroke-width": n.taille / (pas.length + 1.5), "stroke-opacity": opacite,
          }, g);
        });
        n.monde.push(g);
      }
      if (TERRES.has(n.forme) && n.taille > 0) {
        const graine = hachage(n.id + n.nom);
        const g = creer("g", {}, n.forme === "continent" ? gTerres : n.forme === "ville" ? gVilles : gQuartiers);
        if (n.forme === "continent") {
          const contour = tache(n.x, n.y, n.taille, graine, 0.15);
          // Le rivage : une lueur large, puis la terre, ses reliefs et sa cote.
          creer("path", {
            d: tache(n.x, n.y, n.taille * 1.035, graine, 0.15), fill: c, "fill-opacity": 0.07,
            stroke: c, "stroke-opacity": 0.12, "stroke-width": n.taille * 0.05,
          }, g);
          creer("path", {
            d: contour,
            fill: degrade(`${pre}-t${i}`, [
              ["0%", css(melange(n.coul, BLANC, 0.18)), 0.34],
              ["70%", c, 0.2],
              ["100%", css(melange(n.coul, NUIT, 0.4)), 0.28],
            ]),
          }, g);
          const hasard = alea(graine ^ 0x9e3779b9);
          for (let j = 0; j < 14; j++) {
            const a = hasard() * Math.PI * 2;
            const d = Math.sqrt(hasard()) * n.taille * 0.72;
            const rr = n.taille * (0.07 + hasard() * 0.16);
            creer("path", {
              d: tache(n.x + d * Math.cos(a), n.y + d * Math.sin(a), rr, graine + j, 0.22, 48),
              fill: hasard() < 0.5 ? clair : css(melange(n.coul, NUIT, 0.5)),
              "fill-opacity": 0.05 + hasard() * 0.06,
            }, g);
          }
          creer("path", { class: "c-cote", d: contour, fill: "none", stroke: clair }, g);
          creer("path", {
            class: "c-cote c-cote-fine", d: tache(n.x, n.y, n.taille * 0.965, graine, 0.15), fill: "none", stroke: clair,
          }, g);
        } else if (n.forme === "ville") {
          const contour = tache(n.x, n.y, n.taille, graine, 0.2, 72);
          creer("path", {
            d: contour, fill: c, "fill-opacity": 0.16,
            stroke: c, "stroke-opacity": 0.45, class: "c-cote",
          }, g);
          // Les lumieres de la ville, plus denses au centre.
          const hasard = alea(graine);
          const total = borne(Math.round(n.taille * n.taille * 1.3 + 24), 30, 280);
          const lots = [[], []];
          for (let j = 0; j < total; j++) {
            const a = hasard() * Math.PI * 2;
            const d = Math.pow(hasard(), 0.75) * n.taille * 0.86;
            lots[hasard() < 0.82 ? 0 : 1].push(
              `M${(n.x + d * Math.cos(a)).toFixed(4)} ${(n.y + d * Math.sin(a)).toFixed(4)}h0.0001`
            );
          }
          [[1.2, 0.5, melange(n.coul, BLANC, 0.35)], [2.1, 0.9, melange(n.coul, BLANC, 0.7)]].forEach(
            ([largeur, opacite, teinte], j) =>
              creer("path", {
                class: "c-poussiere", d: lots[j].join(""), stroke: css(teinte),
                "stroke-width": largeur, "stroke-opacity": opacite,
              }, g)
          );
        } else {
          creer("path", {
            class: "c-cote c-quartier", d: tache(n.x, n.y, n.taille, graine, 0.12, 64),
            fill: c, "fill-opacity": 0.14, stroke: c,
          }, g);
        }
        n.monde.push(g);
      }
      if (n.forme === "zone" && n.taille > 0) {
        const fond = degrade(`${pre}-z${i}`, [
          ["0%", c, 0.42], ["55%", c, 0.2], ["100%", c, 0],
        ]);
        n.monde.push(creer("circle", { cx: n.x, cy: n.y, r: n.taille, fill: fond }, gZones));
      }

      // Les corps, en coordonnees d'ecran (taille minimale lisible)
      const versSoleil = Math.hypot(n.x, n.y) || 1;
      const lx = 50 - (n.x / versSoleil) * 26;
      const ly = 50 - (n.y / versSoleil) * 26;
      if (n.forme === "etoile") {
        const g = creer("g", { class: "c-astre", "data-id": n.id }, gCorps);
        n.halo = creer("circle", {
          class: "c-halo",
          fill: degrade(`${pre}-h${i}`, [["0%", c, 0.5], ["35%", c, 0.14], ["100%", c, 0]]),
        }, g);
        n.disque = creer("circle", {
          fill: degrade(`${pre}-b${i}`, [
            ["0%", "#fff8e6"], ["45%", c], ["100%", css(melange(n.coul, [200, 90, 30], 0.45))],
          ]),
        }, g);
        n.gCorps = g;
      } else if (n.forme === "planete" || n.forme === "lune") {
        const g = creer("g", { class: "c-astre", "data-id": n.id }, gCorps);
        n.atmo = creer("circle", { class: "c-atmo", stroke: clair }, g);
        n.disque = creer("circle", {
          fill: degrade(`${pre}-b${i}`, [
            ["0%", css(melange(n.coul, BLANC, 0.42))],
            ["48%", c],
            ["100%", css(melange(n.coul, NUIT, 0.78))],
          ], { cx: lx + "%", cy: ly + "%", fx: lx + "%", fy: ly + "%", r: "78%" }),
        }, g);
        n.gCorps = g;
      }

      // Les reperes
      const g = creer("g", {
        class: `c-noeud f-${n.forme}${n.secret ? " secret" : ""}${n.calque ? " calque" : ""}`,
        "data-id": n.id,
      }, gNoeuds);
      n.emprise = creer("circle", { class: "c-emprise", stroke: c }, g);
      switch (n.forme) {
        case "etoile":
        case "planete":
        case "lune":
          break;
        case "zone":
        case "continent":
          creer("circle", { class: "c-point", r: 2.4, fill: c }, g);
          break;
        case "ville":
          creer("circle", { class: "c-anneau", r: 6.5, stroke: clair }, g);
          creer("circle", { r: 3.4, fill: clair, stroke: css(NUIT), "stroke-width": 1 }, g);
          break;
        case "quartier":
          creer("rect", {
            class: "c-forme", x: -3.4, y: -3.4, width: 6.8, height: 6.8, rx: 1.2,
            fill: css(melange(n.coul, NUIT, 0.4)), stroke: c,
          }, g);
          break;
        case "ceinture":
        case "anneau":
        case "region":
          creer("path", { class: "c-repere", d: "M0 -3.5L3.5 0L0 3.5L-3.5 0Z", fill: clair }, g);
          break;
        case "ruche":
          creer("path", {
            class: "c-forme", fill: css(melange(n.coul, NUIT, 0.45)), stroke: c,
            d: "M0 -5.6L4.85 -2.8L4.85 2.8L0 5.6L-4.85 2.8L-4.85 -2.8Z",
          }, g);
          creer("circle", { r: 1.4, fill: clair }, g);
          break;
        case "station":
          creer("path", {
            class: "c-forme", d: "M0 -5L5 0L0 5L-5 0Z",
            fill: css(melange(n.coul, NUIT, 0.5)), stroke: c,
          }, g);
          break;
        case "balise":
          creer("circle", { class: "c-pulse", r: 3, stroke: c }, g);
          creer("circle", { r: 2.4, fill: clair }, g);
          break;
        case "signal":
          [0, 1, 2].forEach((j) =>
            creer("circle", { class: "c-onde", r: 4, stroke: c, style: `animation-delay:${j * 1.1}s` }, g)
          );
          creer("circle", { r: 2.8, fill: c }, g);
          break;
        case "flotte": {
          const chevron = (x, y, s) =>
            `M${x - 2.6 * s} ${y + 1.8 * s}L${x} ${y - 2 * s}L${x + 2.6 * s} ${y + 1.8 * s}`;
          creer("path", {
            class: "c-flotte", stroke: c,
            d: [[0, -4, 1.15], [-5, 1, 0.9], [5, 1, 0.9], [-2.5, 5.5, 0.75], [2.5, 5.5, 0.75]]
              .map(([x, y, s]) => chevron(x, y, s)).join(""),
          }, g);
          break;
        }
        case "reve":
          n.songe = creer("circle", { class: "c-songe", stroke: c }, g);
          creer("circle", {
            class: "c-songe-halo", r: 13,
            fill: degrade(`${pre}-s${i}`, [["0%", c, 0.55], ["100%", c, 0]]),
          }, g);
          creer("path", {
            class: "c-forme", fill: clair,
            d: "M0 -7C0.8 -1.6 1.6 -0.8 7 0C1.6 0.8 0.8 1.6 0 7C-0.8 1.6 -1.6 0.8 -7 0C-1.6 -0.8 -0.8 -1.6 0 -7Z",
          }, g);
          break;
        default:
          creer("circle", { class: "c-anneau", r: 5.5, stroke: c }, g);
          creer("circle", { r: 2.6, fill: c }, g);
      }
      creer("circle", { class: "c-cible", r: 12 }, g);
      n.g = g;

      n.etiquette = creer("text", {
        class: `c-etiq p${Math.min(n.profondeur, 3)} f-${n.forme}` +
          (n.secret ? " secret" : "") + (n.calque ? " calque" : ""),
        "data-id": n.id,
      }, gEtiquettes);
      n.etiquette.textContent = n.nom;
    });

    const fils = (donnees.fils || []).map((f) => ({
      ...f,
      el: creer("path", { class: "c-fil" + (f.calque ? " c-fil-calque" : "") }, gFils),
    }));

    // --------------------------------------------------------------- ciel

    const etoiles = (() => {
      const hasard = alea(hachage(donnees.chemin || "ciel"));
      return Array.from({ length: 520 }, () => ({
        u: hasard(), v: hasard(),
        p: [0.012, 0.028, 0.055][Math.floor(hasard() * 3)],
        t: hasard() < 0.92 ? 0.6 + hasard() * 0.7 : 1.4 + hasard() * 0.9,
        a: 0.18 + hasard() * 0.6,
        c: hasard() < 0.15 ? "#ffe4c2" : hasard() < 0.3 ? "#c9dcff" : "#ffffff",
      }));
    })();

    function peindreCiel() {
      const ctx = ciel.getContext("2d");
      const { w, h, dpr } = vue;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const fond = ctx.createRadialGradient(w * 0.5, h * 0.42, 0, w * 0.5, h * 0.5, Math.max(w, h) * 0.8);
      fond.addColorStop(0, decor.fond[0]);
      fond.addColorStop(1, decor.fond[1]);
      ctx.fillStyle = fond;
      ctx.fillRect(0, 0, w, h);

      // Deux nebuleuses tres pales, qui glissent lentement avec la carte.
      const nebuleuse = (u, v, r, couleur) => {
        const x = ((u * w + vue.tx * 0.02) % (w * 1.6) + w * 1.6) % (w * 1.6) - w * 0.3;
        const y = ((v * h + vue.ty * 0.02) % (h * 1.6) + h * 1.6) % (h * 1.6) - h * 0.3;
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, couleur);
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      };
      decor.nebuleuses.forEach(([u, v, r, couleur]) => nebuleuse(u, v, Math.max(w, h) * r, couleur));

      const T = 1300;
      for (const e of etoiles) {
        const x0 = ((e.u * T + vue.tx * e.p) % T + T) % T;
        const y0 = ((e.v * T + vue.ty * e.p) % T + T) % T;
        // Dans la brume, pas d'etoiles : des grains de lumiere, plus pales.
        ctx.globalAlpha = decor.grains ? e.a * 0.45 : e.a;
        ctx.fillStyle = decor.grains ? decor.grains[e.u < 0.5 ? 0 : 1] : e.c;
        for (let x = x0; x < w; x += T) {
          for (let y = y0; y < h; y += T) {
            if (e.t > 1.3) {
              ctx.beginPath();
              ctx.arc(x, y, e.t * 0.6, 0, Math.PI * 2);
              ctx.fill();
            } else {
              ctx.fillRect(x, y, e.t, e.t);
            }
          }
        }
      }
      ctx.globalAlpha = 1;
    }

    // ------------------------------------------------------------- dessin

    const planifier = () => {
      if (!etat.image && !etat.detruit) etat.image = requestAnimationFrame(dessiner);
    };

    // A partir de quelle taille a l'ecran un lieu laisse voir ce qu'il contient.
    const ouverture = (n) => (n.portee > 0 ? lisse((n.portee * vue.k - 34) / 70) : 0);

    function rayonEcran(n) {
      if (CORPS.has(n.forme)) return Math.max(n.taille * vue.k, RAYON_MIN[n.forme]);
      if (n.forme === "zone" || TERRES.has(n.forme)) return Math.max(n.taille * vue.k, 3);
      return 6;
    }

    function ancetreVisible(n) {
      let courant = n;
      while (courant && courant.alpha < 0.2) {
        courant = courant.parent ? parId.get(courant.parent) : null;
      }
      return courant;
    }

    function dessiner() {
      etat.image = 0;
      const { k, tx, ty, w, h } = vue;
      if (!w || !h) return; // pas encore de taille : le ResizeObserver relancera
      const matrice = `matrix(${k} 0 0 ${k} ${tx} ${ty})`;
      gArriere.setAttribute("transform", matrice);
      gAvant.setAttribute("transform", matrice);
      peindreCiel();

      for (const n of ordre) {
        const parent = n.parent ? parId.get(n.parent) : null;
        const calqueVisible = !n.calque || calquesActifs.has(n.calque);
        n.alpha = !calqueVisible ? 0 : parent ? parent.alpha * ouverture(parent) : 1;
        n.sx = n.x * k + tx;
        n.sy = n.y * k + ty;
        n.r = rayonEcran(n);
      }

      const ecranMin = Math.min(w, h);
      for (const n of noeuds) {
        const visible = n.alpha > 0.015;
        // Une terre plus grande que l'ecran devient le sol : elle s'efface en
        // une teinte, pour que les villes et quartiers poses dessus ressortent.
        const sol = n.forme === "zone" || TERRES.has(n.forme)
          ? 1 - 0.72 * lisse((n.taille * k - ecranMin * 0.6) / (ecranMin * 1.6))
          : 1;
        for (const e of n.monde) {
          e.style.display = visible ? "" : "none";
          if (visible) e.style.opacity = n.alpha * sol;
        }

        const marge = n.r + 160;
        const aLEcran =
          n.sx > -marge && n.sx < w + marge && n.sy > -marge && n.sy < h + marge;
        const montre = visible && aLEcran;

        if (n.gCorps) {
          n.gCorps.style.display = montre ? "" : "none";
          if (montre) {
            // Plus grand que l'ecran, un astre devient le sol : il s'efface en
            // une teinte, pour laisser lire ce qui est pose dessus.
            const ecran = Math.min(w, h);
            const sol = 1 - 0.85 * lisse((n.r - ecran * 0.45) / (ecran * 1.4));
            n.gCorps.style.opacity = n.alpha * sol;
            n.disque.setAttribute("cx", n.sx);
            n.disque.setAttribute("cy", n.sy);
            n.disque.setAttribute("r", n.r);
            if (n.halo) {
              n.halo.setAttribute("cx", n.sx);
              n.halo.setAttribute("cy", n.sy);
              n.halo.setAttribute("r", n.r * 3.6);
            }
            if (n.atmo) {
              n.atmo.setAttribute("cx", n.sx);
              n.atmo.setAttribute("cy", n.sy);
              n.atmo.setAttribute("r", n.r + Math.max(1.4, n.r * 0.06));
            }
          }
        }

        n.g.style.display = montre ? "" : "none";
        if (montre) {
          n.g.setAttribute("transform", `translate(${n.sx.toFixed(2)} ${n.sy.toFixed(2)})`);
          n.g.style.opacity = n.alpha;
          // L'emprise d'un lieu qui a une taille : la clairiere, le cratere.
          const emprise = !CORPS.has(n.forme) && !BANDES.has(n.forme) && !TERRES.has(n.forme) && n.forme !== "zone"
            ? n.taille * k : 0;
          n.emprise.style.display = emprise > 9 ? "" : "none";
          if (emprise > 9) n.emprise.setAttribute("r", emprise);
          if (n.songe) {
            const r = n.taille * k;
            n.songe.style.display = r > 16 ? "" : "none";
            if (r > 16) n.songe.setAttribute("r", r);
          }
        }
      }

      // Les fils : chaque extremite se replie sur son plus proche ancetre visible.
      const traces = new Set();
      for (const f of fils) {
        const a = ancetreVisible(parId.get(f.de));
        const b = ancetreVisible(parId.get(f.vers));
        const calqueVisible = !f.calque || calquesActifs.has(f.calque);
        const cle = a && b ? [a.id, b.id].sort().join("|") : "";
        if (!calqueVisible || !a || !b || a === b || traces.has(cle)) {
          f.el.style.display = "none";
          continue;
        }
        traces.add(cle);
        const dx = b.sx - a.sx, dy = b.sy - a.sy;
        const longueur = Math.hypot(dx, dy);
        const mx = (a.sx + b.sx) / 2 - dy * 0.18;
        const my = (a.sy + b.sy) / 2 + dx * 0.18;
        f.el.style.display = longueur < 6 ? "none" : "";
        f.el.setAttribute("d", `M${a.sx} ${a.sy}Q${mx} ${my} ${b.sx} ${b.sy}`);
        f.el.style.opacity = Math.min(a.alpha, b.alpha) * 0.85;
      }

      placerEtiquettes();

      const choisi = etat.selection && parId.get(etat.selection);
      if (choisi && choisi.alpha > 0.05) {
        anneauChoix.style.display = "";
        anneauChoix.setAttribute("cx", choisi.sx);
        anneauChoix.setAttribute("cy", choisi.sy);
        anneauChoix.setAttribute("r", (CORPS.has(choisi.forme) ? choisi.r : 6) + 7);
      } else {
        anneauChoix.style.display = "none";
      }
    }

    function largeur(n) {
      if (n.lw === undefined || n.lw === 0) {
        try {
          n.lw = n.etiquette.getComputedTextLength();
        } catch {
          n.lw = 0;
        }
        if (!n.lw) return n.nom.length * 6.6;
      }
      return n.lw;
    }

    function placerEtiquettes() {
      const { w, h } = vue;
      const candidats = noeuds
        .filter((n) => n.alpha > 0.22 && n.sx > -60 && n.sx < w + 60 && n.sy > -30 && n.sy < h + 30)
        .sort((a, b) => priorite(b) - priorite(a));
      const places = [];
      const libre = (r) =>
        !places.some((p) => r[0] < p[2] && r[2] > p[0] && r[1] < p[3] && r[3] > p[1]);

      for (const n of noeuds) n.etiquetteMontree = false;
      for (const n of candidats) {
        const lw = largeur(n);
        const fh = n.profondeur === 0 ? 14 : 12.5;
        const essais = [];
        if ((CORPS.has(n.forme) || TERRES.has(n.forme)) && n.r > 34) {
          essais.push(["middle", n.sx, n.sy - n.r - 9]);
        } else if (n.forme === "zone" && n.r > 40) {
          essais.push(["middle", n.sx, n.sy + n.r * 0.55]);
        } else {
          const ecart = (CORPS.has(n.forme) ? n.r : 6) + 6;
          essais.push(["start", n.sx + ecart, n.sy + 4]);
          essais.push(["end", n.sx - ecart, n.sy + 4]);
          essais.push(["middle", n.sx, n.sy + ecart + 9]);
        }
        let retenu = null;
        for (const [ancre, x, y] of essais) {
          const x0 = ancre === "start" ? x : ancre === "end" ? x - lw : x - lw / 2;
          const rect = [x0 - 3, y - fh + 1, x0 + lw + 3, y + 4];
          if (n.id === etat.selection || n.id === etat.survol || libre(rect)) {
            retenu = [ancre, x, y, rect];
            break;
          }
        }
        if (!retenu) continue;
        places.push(retenu[3]);
        n.etiquetteMontree = true;
        n.etiquette.setAttribute("text-anchor", retenu[0]);
        n.etiquette.setAttribute("x", retenu[1].toFixed(1));
        n.etiquette.setAttribute("y", retenu[2].toFixed(1));
        n.etiquette.style.opacity = lisse((n.alpha - 0.22) / 0.35);
      }
      for (const n of noeuds) {
        n.etiquette.style.display = n.etiquetteMontree ? "" : "none";
        n.etiquette.classList.toggle("vive", n.id === etat.selection || n.id === etat.survol);
      }
    }

    function priorite(n) {
      if (n.id === etat.selection) return 1e6;
      if (n.id === etat.survol) return 1e5;
      return (
        (10 - Math.min(n.profondeur, 9)) * 1000 +
        (n.page ? 300 : 0) +
        (CORPS.has(n.forme) ? 200 : 0) +
        Math.min(n.portee * vue.k, 150)
      );
    }

    // --------------------------------------------------------- deplacement

    const centre = () => [(vue.w / 2 - vue.tx) / vue.k, (vue.h / 2 - vue.ty) / vue.k];

    function poser(cx, cy, k) {
      vue.k = borne(k, etat.kMin, etat.kMax);
      vue.tx = vue.w / 2 - cx * vue.k;
      vue.ty = vue.h / 2 - cy * vue.k;
      planifier();
    }

    function zoomerEn(facteur, sx, sy) {
      const k = borne(vue.k * facteur, etat.kMin, etat.kMax);
      const f = k / vue.k;
      vue.tx = sx - (sx - vue.tx) * f;
      vue.ty = sy - (sy - vue.ty) * f;
      vue.k = k;
      planifier();
    }

    function arreterAnimation() {
      if (etat.anim) cancelAnimationFrame(etat.anim);
      etat.anim = 0;
    }

    function voler(cx, cy, k, instantane = false) {
      arreterAnimation();
      k = borne(k, etat.kMin, etat.kMax);
      if (instantane || mouvementReduit()) return poser(cx, cy, k);
      const [x0, y0] = centre();
      const f = interpolerZoom([x0, y0, vue.w / vue.k], [cx, cy, vue.w / k]);
      const debut = performance.now();
      const pas = (t) => {
        const p = Math.min(1, (t - debut) / f.duree);
        const [x, y, largeurVue] = f(entreeSortie(p));
        poser(x, y, vue.w / largeurVue);
        etat.anim = p < 1 ? requestAnimationFrame(pas) : 0;
      };
      etat.anim = requestAnimationFrame(pas);
    }

    function cadrage() {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const n of noeuds) {
        if (n.parent || (n.calque && !calquesActifs.has(n.calque))) continue;
        let cx = n.x, cy = n.y, r = Math.max(n.taille, n.portee, 1);
        if (BANDES.has(n.forme)) {
          cx = n.cx; cy = n.cy; r = n.orbite + n.taille / 2;
        }
        x0 = Math.min(x0, cx - r); x1 = Math.max(x1, cx + r);
        y0 = Math.min(y0, cy - r); y1 = Math.max(y1, cy + r);
      }
      if (!isFinite(x0)) return { x: 0, y: 0, k: 1 };
      const k = Math.min(vue.w / (x1 - x0), vue.h / (y1 - y0)) * 0.9;
      return { x: (x0 + x1) / 2, y: (y0 + y1) / 2, k };
    }

    function ensemble(instantane = false) {
      etat.focus = null;
      const c = cadrage();
      voler(c.x, c.y, c.k, instantane);
      majAriane();
    }

    function cible(n) {
      let r;
      if (n.portee > 0) r = n.portee * 1.2;
      else if (CORPS.has(n.forme) || n.forme === "zone") r = Math.max(n.taille, 0.01) * 5;
      else {
        const parent = n.parent ? parId.get(n.parent) : null;
        r = parent && parent.portee > 0 ? parent.portee * 0.32 : Math.max(n.taille * 4, 4);
      }
      return { x: n.x, y: n.y, k: (Math.min(vue.w, vue.h) * 0.46) / Math.max(r, 1e-4) };
    }

    function aller(id, instantane = false) {
      const n = parId.get(id);
      if (!n) return;
      if (n.calque && !calquesActifs.has(n.calque)) basculerCalque(n.calque, true);
      etat.focus = id;
      const c = cible(n);
      voler(c.x, c.y, c.k, instantane);
      majAriane();
    }

    // ------------------------------------------------- fiche, bulle, ariane

    function chemin(n) {
      const liste = [];
      let courant = n;
      while (courant) {
        liste.unshift(courant);
        courant = courant.parent ? parId.get(courant.parent) : null;
      }
      return liste;
    }

    function majAriane() {
      const n = parId.get(etat.selection || etat.focus);
      const etapes = n ? chemin(n) : [];
      ui.ariane.innerHTML =
        `<button type="button" data-aller="">Vue d'ensemble</button>` +
        etapes
          .map(
            (e) =>
              `<span class="sep">›</span><button type="button" data-aller="${echapper(e.id)}"` +
              `${e === n ? ' class="actuel"' : ""}>${echapper(e.nom)}</button>`
          )
          .join("");
    }

    function nature(n) {
      const morceaux = [n.calque || LIBELLES[n.forme] || n.forme];
      if (n.calque && n.forme !== "reve") morceaux.push(LIBELLES[n.forme]);
      return morceaux.join(" · ");
    }

    function majFiche() {
      const n = parId.get(etat.selection);
      if (!n) {
        ui.fiche.hidden = true;
        return;
      }
      const enfants = n.enfants
        .map((id) => parId.get(id))
        .filter((e) => e && (!e.calque || calquesActifs.has(e.calque)));
      const lienPage = n.page
        ? `<a class="bouton bouton-petit bouton-primaire" href="${echapper(n.url || "")}" data-page="${echapper(n.page)}">` +
          `Ouvrir ${n.titre_page && n.titre_page !== n.nom ? "« " + echapper(n.titre_page) + " »" : "la page"}</a>`
        : "";
      ui.fiche.innerHTML =
        `<span class="mk mk-tl">+</span><span class="mk mk-br">+</span>
         <header class="fiche-tete">
           <span class="etiquette">${echapper(nature(n))}</span>
           ${n.secret ? '<span class="pastille" data-ton="mj">secret</span>' : ""}
           <button type="button" class="fiche-fermer" data-action="fermer" title="Fermer (Echap)">×</button>
         </header>
         <h3>${echapper(n.nom)}</h3>
         ${n.note ? `<p class="fiche-note">${echapper(n.note)}</p>` : '<p class="fiche-note vide">Pas de description.</p>'}
         ${enfants.length
           ? `<div class="fiche-enfants"><span class="etiquette">On y trouve</span><div>` +
             enfants
               .map((e) => `<button type="button" data-choisir="${echapper(e.id)}">${echapper(e.nom)}</button>`)
               .join("") +
             `</div></div>`
           : ""}
         <footer class="fiche-actions">
           ${lienPage}
           <button type="button" class="bouton bouton-petit" data-action="aller">S'y rendre</button>
           ${options.demander ? '<button type="button" class="bouton bouton-petit" data-action="demander" title="Preparer une question a l\'assistant">Demander</button>' : ""}
         </footer>`;
      ui.fiche.hidden = false;
    }

    function choisir(id, centrer = false) {
      etat.selection = id && parId.has(id) ? id : null;
      majFiche();
      majAriane();
      if (centrer && etat.selection) aller(etat.selection);
      planifier();
    }

    function montrerBulle(n, x, y) {
      if (!n) {
        ui.bulle.hidden = true;
        return;
      }
      const note = n.note.length > 150 ? n.note.slice(0, n.note.lastIndexOf(" ", 146)) + "…" : n.note;
      ui.bulle.innerHTML =
        `<span class="etiquette">${echapper(nature(n))}${n.secret ? " · secret" : ""}</span>` +
        `<strong>${echapper(n.nom)}</strong>` +
        (note ? `<span>${echapper(note)}</span>` : "");
      ui.bulle.hidden = false;
      const boite = racine.getBoundingClientRect();
      const bw = ui.bulle.offsetWidth, bh = ui.bulle.offsetHeight;
      let bx = x + 16, by = y + 14;
      if (bx + bw > boite.width - 8) bx = x - bw - 16;
      if (by + bh > boite.height - 8) by = y - bh - 14;
      ui.bulle.style.transform = `translate(${Math.max(8, bx)}px, ${Math.max(8, by)}px)`;
    }

    function basculerCalque(calque, actif) {
      const montre = actif ?? !calquesActifs.has(calque);
      if (montre) calquesActifs.add(calque);
      else calquesActifs.delete(calque);
      ui.calques.querySelectorAll("[data-calque]").forEach((b) => {
        if (b.dataset.calque === calque) b.setAttribute("aria-pressed", String(montre));
      });
      const choisi = parId.get(etat.selection);
      if (choisi && choisi.calque === calque && !montre) choisir(null);
      else majFiche();
      planifier();
    }

    // ---------------------------------------------------------- evenements

    const pointeurs = new Map();
    let geste = null;

    const local = (ev) => {
      const b = svg.getBoundingClientRect();
      return [ev.clientX - b.left, ev.clientY - b.top];
    };
    const noeudSous = (ev) => {
      const cibleEl = ev.target.closest && ev.target.closest("[data-id]");
      return cibleEl ? parId.get(cibleEl.dataset.id) : null;
    };

    svg.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0 && ev.pointerType === "mouse") return;
      arreterAnimation();
      const [x, y] = local(ev);
      pointeurs.set(ev.pointerId, { x, y });
      geste = { x0: x, y0: y, bouge: 0, noeud: noeudSous(ev) };
      if (pointeurs.size === 2) {
        const [a, b] = [...pointeurs.values()];
        geste.pince = { d: Math.hypot(a.x - b.x, a.y - b.y), mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
      }
      racine.focus({ preventScroll: true });
    });

    svg.addEventListener("pointermove", (ev) => {
      const [x, y] = local(ev);
      if (!pointeurs.has(ev.pointerId)) {
        const n = noeudSous(ev);
        const id = n ? n.id : null;
        if (id !== etat.survol) {
          etat.survol = id;
          svg.classList.toggle("survol", !!id);
          planifier();
        }
        montrerBulle(n, x, y);
        return;
      }
      const avant = pointeurs.get(ev.pointerId);
      pointeurs.set(ev.pointerId, { x, y });
      if (pointeurs.size === 2 && geste && geste.pince) {
        const [a, b] = [...pointeurs.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        vue.tx += mx - geste.pince.mx;
        vue.ty += my - geste.pince.my;
        zoomerEn(d / (geste.pince.d || d), mx, my);
        geste.pince = { d, mx, my };
        geste.bouge = 99;
        return;
      }
      vue.tx += x - avant.x;
      vue.ty += y - avant.y;
      if (geste) geste.bouge = Math.max(geste.bouge, Math.hypot(x - geste.x0, y - geste.y0));
      if (geste && geste.bouge > 4) {
        // La capture n'est prise qu'une fois le glissement commence : un simple
        // clic ou un double-clic garde ainsi pour cible le lieu sous le pointeur.
        if (!svg.hasPointerCapture(ev.pointerId)) svg.setPointerCapture(ev.pointerId);
        racine.classList.add("glisse");
        ui.bulle.hidden = true;
      }
      planifier();
    });

    const relacher = (ev) => {
      if (!pointeurs.has(ev.pointerId)) return;
      pointeurs.delete(ev.pointerId);
      racine.classList.remove("glisse");
      if (geste && pointeurs.size === 0) {
        if (geste.bouge <= 4 && ev.type === "pointerup") {
          const n = noeudSous(ev) || geste.noeud;
          choisir(n ? n.id : null);
        }
        geste = null;
      }
    };
    svg.addEventListener("pointerup", relacher);
    svg.addEventListener("pointercancel", relacher);
    svg.addEventListener("pointerleave", () => {
      if (!pointeurs.size) {
        etat.survol = null;
        ui.bulle.hidden = true;
        planifier();
      }
    });

    svg.addEventListener("dblclick", (ev) => {
      ev.preventDefault();
      const n = noeudSous(ev);
      if (n) {
        choisir(n.id);
        aller(n.id);
      } else {
        const [x, y] = local(ev);
        const [cx, cy] = [(x - vue.tx) / vue.k, (y - vue.ty) / vue.k];
        voler(cx, cy, vue.k * 2.2);
      }
    });

    svg.addEventListener(
      "wheel",
      (ev) => {
        ev.preventDefault();
        arreterAnimation();
        const [x, y] = local(ev);
        const delta = ev.deltaMode === 1 ? ev.deltaY * 18 : ev.deltaY;
        zoomerEn(Math.exp(-delta * 0.0016), x, y);
      },
      { passive: false }
    );

    racine.addEventListener("click", (ev) => {
      const bouton = ev.target.closest("button");
      if (!bouton) return;
      if (bouton.dataset.calque !== undefined) return basculerCalque(bouton.dataset.calque);
      if (bouton.dataset.carte && options.ouvrirCarte) return options.ouvrirCarte(bouton.dataset.carte);
      if (bouton.dataset.aller !== undefined) {
        if (!bouton.dataset.aller) {
          choisir(null);
          return ensemble();
        }
        choisir(bouton.dataset.aller);
        return aller(bouton.dataset.aller);
      }
      if (bouton.dataset.choisir) {
        choisir(bouton.dataset.choisir);
        return aller(bouton.dataset.choisir);
      }
      const action = bouton.dataset.action;
      if (action === "plus") voler(...centre(), vue.k * 2);
      else if (action === "moins") voler(...centre(), vue.k / 2);
      else if (action === "ensemble") {
        choisir(null);
        ensemble();
      } else if (action === "fermer") choisir(null);
      else if (action === "aller" && etat.selection) aller(etat.selection);
      else if (action === "demander" && etat.selection) {
        const n = parId.get(etat.selection);
        const page = n.titre_page && n.titre_page !== n.nom ? ` (page « ${n.titre_page} »)` : "";
        options.demander(`Que trouve-t-on à « ${n.nom} »${page} ? Que peut-on y faire ?`);
      } else if (action === "agrandir" && options.agrandir) {
        const actif = options.agrandir();
        ui.agrandir.setAttribute("aria-pressed", String(!!actif));
      }
    });

    racine.addEventListener("keydown", (ev) => {
      if (ev.target.closest("input, textarea, select")) return;
      const pasDeplacement = 70;
      const touches = {
        "+": () => voler(...centre(), vue.k * 1.8),
        "=": () => voler(...centre(), vue.k * 1.8),
        "-": () => voler(...centre(), vue.k / 1.8),
        "0": () => { choisir(null); ensemble(); },
        Escape: () => choisir(null),
        Enter: () => etat.selection && aller(etat.selection),
        ArrowLeft: () => { vue.tx += pasDeplacement; planifier(); },
        ArrowRight: () => { vue.tx -= pasDeplacement; planifier(); },
        ArrowUp: () => { vue.ty += pasDeplacement; planifier(); },
        ArrowDown: () => { vue.ty -= pasDeplacement; planifier(); },
      };
      const action = touches[ev.key];
      if (action && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
        ev.preventDefault();
        if (ev.key === "Escape") ev.stopPropagation();
        action();
      }
    });

    // ------------------------------------------------------------ taille

    let premier = true;
    function redimensionner() {
      const b = racine.getBoundingClientRect();
      if (!b.width || !b.height) return;
      const [cx, cy] = premier ? [0, 0] : centre();
      vue.w = b.width;
      vue.h = b.height;
      vue.dpr = Math.min(window.devicePixelRatio || 1, 2);
      ciel.width = Math.round(vue.w * vue.dpr);
      ciel.height = Math.round(vue.h * vue.dpr);
      svg.setAttribute("viewBox", `0 0 ${vue.w} ${vue.h}`);

      const c = cadrage();
      etat.kMin = c.k * 0.35;
      if (premier) {
        premier = false;
        demarrer(c);
      } else {
        poser(cx, cy, vue.k);
      }
    }

    function demarrer(c) {
      if (options.vue && isFinite(options.vue.k)) {
        poser(options.vue.x, options.vue.y, options.vue.k);
      } else {
        poser(c.x, c.y, c.k);
      }
      if (options.selection && parId.has(options.selection)) choisir(options.selection);
      if (options.focus && parId.has(options.focus)) {
        choisir(options.focus);
        setTimeout(() => aller(options.focus), mouvementReduit() ? 0 : 260);
      }
      majAriane();
    }

    const observateur = new ResizeObserver(redimensionner);
    observateur.observe(racine);

    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => {
        noeuds.forEach((n) => (n.lw = undefined));
        planifier();
      });
    }

    // ------------------------------------------------------------ interface

    return {
      aller: (id) => { choisir(id); aller(id); },
      choisir,
      etat: () => {
        const [x, y] = centre();
        return { x, y, k: vue.k, selection: etat.selection };
      },
      majAgrandi: (actif) => ui.agrandir.setAttribute("aria-pressed", String(!!actif)),
      detruire: () => {
        etat.detruit = true;
        arreterAnimation();
        if (etat.image) cancelAnimationFrame(etat.image);
        observateur.disconnect();
        hote.innerHTML = "";
      },
    };
  }

  window.CarteInteractive = { monter };
})();
