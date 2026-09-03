// Banc d'essai du script de web/overlay.html, hors navigateur.
//
// Pourquoi ce banc : dans cet environnement, un onglet non affiche ne compose
// aucune image, donc `requestAnimationFrame` ne se declenche jamais et le DOM
// de l'overlay reste fige sur son etat initial — impossible d'y valider quoi
// que ce soit. Ici le script reel est charge dans un contexte `vm` avec un DOM
// et un WebSocket simules, et une horloge que l'on avance a la main : la
// logique testee est celle du fichier livre, pas une reecriture.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ICI = path.dirname(fileURLToPath(import.meta.url));
const HTML = path.join(ICI, "..", "web", "overlay.html");

const source = fs.readFileSync(HTML, "utf8");
const script = source.match(/<script>([\s\S]*?)<\/script>/)[1];
assert.ok(script.length > 500, "script de l'overlay introuvable");

// Les identifiants attendus sont releves dans le corps HTML, pas codes ici :
// renommer un id dans le fichier doit casser le banc, pas passer inapercu.
const corps = source.match(/<body[\s\S]*?<\/body>/)[0];
const IDS = [...corps.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);

// Texte initial porte par le BALISAGE. Un DOM simule qui part vide ferait
// croire que l'overlay n'affiche rien avant sa premiere image, alors que
// `paint()` ne peint que si quelque chose a change : le texte de depart
// ("Connecting…", "0", "N") vient du HTML lui-meme.
const TEXTE_INITIAL = Object.fromEntries(IDS.map((id) => {
  const trouve = corps.match(new RegExp(`id="${id}"[^>]*>([^<]*)<`));
  return [id, trouve ? trouve[1] : ""];
}));

function creeElement(id) {
  const classes = new Set();
  return {
    id,
    textContent: TEXTE_INITIAL[id] ?? "",
    style: {},
    classList: {
      add: (...cs) => cs.forEach((c) => classes.add(c)),
      remove: (...cs) => cs.forEach((c) => classes.delete(c)),
      contains: (c) => classes.has(c),
      get taille() { return classes.size; },
    },
  };
}

function bancEssai() {
  const elements = Object.fromEntries(IDS.map((id) => [id, creeElement(id)]));
  const images = [];          // callbacks de requestAnimationFrame
  const minuteries = [];      // setTimeout captures, jamais executes seuls
  const envois = [];          // ce que l'overlay envoie au serveur
  let horloge = 1000;
  let prise = null;           // instance de WebSocket creee par l'overlay

  class FauxWebSocket {
    constructor(url) {
      this.url = url;
      this.ferme = false;
      prise = this;
    }
    send(charge) { envois.push(JSON.parse(charge)); }
    close() { this.ferme = true; if (this.onclose) this.onclose(); }
  }

  const contexte = {
    console,
    JSON, Math, Object, Array, String, Number, Boolean, Error, URLSearchParams,
    WebSocket: FauxWebSocket,
    performance: { now: () => horloge },
    setTimeout: (fn, delai) => { minuteries.push({ fn, delai }); return minuteries.length; },
    clearTimeout: () => {},
    requestAnimationFrame: (fn) => { images.push(fn); return images.length; },
    location: { search: "", hostname: "localhost", port: "8765" },
    document: {
      getElementById: (id) => elements[id],
      addEventListener: (nom, fn) => { contexte.document._ecouteurs[nom] = fn; },
      visibilityState: "visible",
      _ecouteurs: {},
    },
  };
  vm.createContext(contexte);
  vm.runInContext(script, contexte, { filename: "overlay.html" });

  return {
    elements, envois, minuteries, contexte,
    get prise() { return prise; },
    avance(ms) { horloge += ms; },
    // Une seule image : on execute les callbacks en attente, qui se
    // reinscrivent d'eux-memes comme dans un navigateur.
    image() {
      const enAttente = images.splice(0, images.length);
      enAttente.forEach((fn) => fn());
    },
    recoit(objet) {
      prise.onmessage({ data: JSON.stringify(objet) });
    },
    recoitBrut(texte) {
      prise.onmessage({ data: texte });
    },
    ouvre() { prise.onopen(); },
  };
}

const essais = [];
function essai(nom, fn) { essais.push([nom, fn]); }

// --------------------------------------------------------------------------

essai("l'overlay se connecte au meme hote et au meme port que la page", (b) => {
  assert.equal(b.prise.url, "ws://localhost:8765");
});

essai("avant tout evenement, le balisage affiche deja quelque chose", (b) => {
  // `paint()` ne peint que sur changement : ce que voit l'utilisateur au
  // chargement vient du HTML. Une page muette serait un defaut.
  assert.equal(b.elements.status.textContent, "Connecting…");
  assert.equal(b.elements.speed.textContent, "0");
  assert.equal(b.elements.gear.textContent, "N");
  b.image();
  assert.equal(b.elements.status.textContent, "Connecting…",
               "une image sans donnee a efface l'affichage");
});

essai("liaison jamais etablie : le statut passe en erreur", (b) => {
  // Serveur absent : onerror ferme la prise, ce qui doit produire un
  // diagnostic visible plutot que laisser "Connecting…" indefiniment.
  b.prise.onerror();
  b.image();
  assert.match(b.elements.status.textContent, /Disconnected/);
  assert.ok(b.elements.status.classList.contains("err"));
});

essai("a l'ouverture, le statut annonce l'attente de l'accueil", (b) => {
  b.ouvre();
  b.image();
  assert.match(b.elements.status.textContent, /awaiting hello/);
});

essai("l'accueil declenche un abonnement aux six canaux affiches", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true,
             channels: new Array(112).fill("x"), subscribe_supported: true,
             status_interval: 1 });
  assert.equal(b.envois.length, 1, "aucun abonnement envoye");
  assert.deepEqual(b.envois[0].subscribe,
                   ["speed", "gear", "current_engine_rpm", "engine_max_rpm",
                    "accel", "brake"]);
});

essai("sans abonnement possible, rien n'est envoye", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"],
             subscribe_supported: false });
  assert.equal(b.envois.length, 0);
});

essai("le statut cite la cadence et le mode annonces", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true,
             channels: new Array(112).fill("x"), subscribe_supported: true });
  b.recoit({ type: "subscribed", channels: new Array(6).fill("y") });
  b.image();
  assert.equal(b.elements.status.textContent,
               "Connected — 6/112 channels at 60 Hz (differential)");
});

essai("le mode trames completes est distingue", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 30, differential: false, channels: ["a"] });
  b.image();
  assert.match(b.elements.status.textContent, /at 30 Hz \(full frames\)/);
});

essai("une trame de telemetrie s'affiche", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "telemetry", full: true, speed: 30, gear: 3,
             current_engine_rpm: 4000, engine_max_rpm: 8000,
             accel: 255, brake: 0, car_name: "1988 BMW M3" });
  b.image();
  assert.equal(b.elements.speed.textContent, 108);      // 30 m/s -> 108 km/h
  assert.equal(b.elements.gear.textContent, 3);
  assert.equal(b.elements.car.textContent, "1988 BMW M3");
  assert.equal(b.elements.rpm.style.width, "50%");      // 4000 / 8000
  assert.equal(b.elements.accel.style.width, "100%");   // 255 / 255
  assert.equal(b.elements.brake.style.width, "0%");
});

essai("LA fusion differentielle : un champ absent garde sa valeur", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "telemetry", full: true, speed: 30, gear: 3,
             current_engine_rpm: 4000, engine_max_rpm: 8000 });
  b.image();
  // Trame partielle : seule la vitesse change.
  b.recoit({ type: "telemetry", speed: 40 });
  b.image();
  assert.equal(b.elements.speed.textContent, 144);
  assert.equal(b.elements.gear.textContent, 3, "le rapport a ete perdu");
  assert.equal(b.elements.rpm.style.width, "50%", "le regime a ete perdu");
});

essai("une trame complete remplace l'etat au lieu de le fusionner", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "telemetry", speed: 30, gear: 3 });
  b.image();
  b.recoit({ type: "telemetry", full: true, speed: 10 });
  b.image();
  assert.equal(b.elements.speed.textContent, 36);
  // `gear` a disparu de l'etat : paint() n'ecrit rien, l'ancien texte reste.
  assert.equal(b.elements.gear.textContent, 3);
});

essai("la marche arriere s'affiche R et non 0", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "telemetry", full: true, gear: 0 });
  b.image();
  assert.equal(b.elements.gear.textContent, "R");
});

essai("le nom du vehicule vient de l'accueil", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"],
             car_name: "1994 Subaru Vivio RX-R" });
  b.image();
  assert.equal(b.elements.car.textContent, "1994 Subaru Vivio RX-R");
});

essai("la trame d'etat met le vehicule a jour, sauf le tiret", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"],
             car_name: "Une voiture" });
  b.recoit({ type: "status", receiving: true, car_name: "-" });
  b.image();
  assert.equal(b.elements.car.textContent, "Une voiture",
               "le tiret a ecrase un nom connu");
  b.recoit({ type: "status", receiving: true, car_name: "Une autre" });
  b.image();
  assert.equal(b.elements.car.textContent, "Une autre");
});

essai("jeu a l'arret : statut peremptoire mais non alarmant", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "status", receiving: false });
  b.image();
  assert.equal(b.elements.status.textContent, "Game idle — no packets received");
  assert.ok(b.elements.status.classList.contains("stale"));
  assert.ok(!b.elements.status.classList.contains("err"));
});

essai("pont muet : detecte a l'absence de trame d'etat", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"],
             status_interval: 1 });
  b.recoit({ type: "status", receiving: true });
  b.image();
  assert.match(b.elements.status.textContent, /Connected —/);

  b.avance(4000);          // plus de 3 x l'intervalle annonce
  b.image();
  assert.equal(b.elements.status.textContent,
               "Bridge unreachable — no status frame");
  assert.ok(b.elements.status.classList.contains("err"));
});

essai("le delai de silence suit l'intervalle annonce par le serveur", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"],
             status_interval: 5 });
  b.recoit({ type: "status", receiving: true });
  b.image();
  b.avance(4000);          // moins de 3 x 5 s : pas encore d'alerte
  b.image();
  assert.match(b.elements.status.textContent, /Connected —/,
               "alerte trop precoce : le seuil ignore status_interval");
  b.avance(12000);
  b.image();
  assert.match(b.elements.status.textContent, /Bridge unreachable/);
});

essai("liaison coupee : message et nouvelle tentative programmee", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.prise.onclose();
  b.image();
  assert.equal(b.elements.status.textContent, "Disconnected — retrying in 2 s");
  assert.ok(b.elements.status.classList.contains("err"));
  assert.equal(b.minuteries.length, 1);
  assert.equal(b.minuteries[0].delai, 2000);
});

essai("la coupure prime sur le reste des diagnostics", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "status", receiving: false });
  b.prise.onclose();
  b.image();
  assert.match(b.elements.status.textContent, /Disconnected/,
               "un flux arrete masquait la liaison coupee");
});

essai("une trame illisible est ignoree sans casser la reception", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "telemetry", full: true, speed: 30 });
  b.image();
  b.recoitBrut("{ceci n'est pas du JSON");        // ne doit pas lever
  b.recoit({ type: "telemetry", speed: 40 });
  b.image();
  assert.equal(b.elements.speed.textContent, 144,
               "la reception s'est arretee sur la trame illisible");
});

essai("NaN dans une trame ne casse pas l'affichage", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoitBrut('{"type":"telemetry","full":true,"speed":null}');
  b.image();
  assert.equal(b.elements.speed.textContent, 0);
});

essai("le rendu n'a lieu que dans l'image, pas a la reception", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "telemetry", full: true, speed: 30 });
  assert.equal(b.elements.speed.textContent, TEXTE_INITIAL.speed,
               "ecriture dans le DOM depuis onmessage : a 60 Hz cela entre en "
               + "concurrence avec le rendu du navigateur");
  b.image();
  assert.equal(b.elements.speed.textContent, 108);
});

essai("le retour d'un onglet masque force un rendu", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "telemetry", full: true, speed: 30 });
  b.image();
  // Trame recue alors que l'onglet est masque : aucune image ne passe.
  b.recoit({ type: "telemetry", speed: 40 });
  b.contexte.document.visibilityState = "visible";
  b.contexte.document._ecouteurs.visibilitychange();
  b.image();
  assert.equal(b.elements.speed.textContent, 144);
});

essai("un regime sans maximum annonce retombe sur 8000", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "telemetry", full: true, current_engine_rpm: 4000 });
  b.image();
  assert.equal(b.elements.rpm.style.width, "50%");
});

essai("les jauges restent bornees a 0-100 %", (b) => {
  b.ouvre();
  b.recoit({ type: "hello", rate_hz: 60, differential: true, channels: ["a"] });
  b.recoit({ type: "telemetry", full: true, current_engine_rpm: 99000,
             engine_max_rpm: 8000, accel: 300, brake: -50 });
  b.image();
  assert.equal(b.elements.rpm.style.width, "100%");
  assert.equal(b.elements.accel.style.width, "100%");
  assert.equal(b.elements.brake.style.width, "0%");
});

// --------------------------------------------------------------------------

let echecs = 0;
for (const [nom, fn] of essais) {
  try {
    fn(bancEssai());
    console.log(`  [ok] ${nom}`);
  } catch (err) {
    echecs += 1;
    console.log(`  [KO] ${nom}\n       ${err.message.split("\n")[0]}`);
  }
}
console.log(`\n${essais.length - echecs}/${essais.length} essais reussis`);
process.exit(echecs ? 1 : 0);
