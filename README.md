# Passerelle de télémétrie Forza Horizon

Transforme la télémétrie de *Forza Horizon 6* en sources d'interaction pour
n'importe quel logiciel parlant **OSC** ou **WebSocket** : création visuelle
(TouchDesigner, cables.gl, vvvv), lumière (QLC+, Chataigne), son
(SuperCollider, Pure Data, Sonic Pi, VCV Rack), overlay de diffusion.

La passerelle écoute le flux « Data Out » du jeu, décode les 88 champs du
paquet, en calcule 19 de plus déjà mis à l'échelle, et rediffuse le tout.

## Démarrage rapide

```bash
pip install -r requirements.txt
python gui.py
```

Dans le jeu : **Réglages → HUD et repères de conduite → Data Out**, activer,
saisir l'adresse réseau de la machine et le port **5300**.

En ligne de commande, sans interface :

```bash
python main.py
```

## Réglage du jeu

Le jeu émet **un paquet par image rendue** : la cadence suit donc le nombre
d'images par seconde, et non le protocole. Mesuré sur la même machine : 30 Hz
et 60 Hz en roulant selon la charge, 60 Hz à l'arrêt. Les paquets font
**324 octets** (format « Horizon Dash »).

Le jeu émet depuis l'adresse réseau de la machine, pas depuis `127.0.0.1` :
la passerelle écoute donc sur `0.0.0.0`.

## Sorties

### OSC

Une adresse par canal, préfixée `/forza/` — `/forza/speed_kmh`,
`/forza/rpm_ratio`… Plusieurs destinations sont possibles, ce qui permet
d'alimenter simultanément plusieurs logiciels :

```bash
python main.py --osc 127.0.0.1:7000 --osc 192.168.0.50:9000
```

Le nom du véhicule part sur `/forza/car_name` sous forme de chaîne, et
uniquement au changement de voiture. Une chaîne n'est pas acceptée par tous
les récepteurs sur leur entrée principale : dans TouchDesigner, il faut un
**OSC In DAT**, pas un OSC In CHOP.

### WebSocket

```bash
python main.py --ws-port 8765
```

L'**overlay de démonstration est servi sur le même port** :
<http://localhost:8765/> — utilisable directement comme source navigateur
dans OBS (fond transparent).

Le serveur écoute sur `127.0.0.1` par défaut. Le flux contient la position du
véhicule ; `--ws-lan` l'ouvre au réseau local, à faire sciemment.

**Réglages par client**, dans l'URL de connexion :

| Paramètre | Effet |
|---|---|
| `?full=1` | état complet à chaque trame, sans fusion à faire |
| `?channels=speed_kmh,gear` | ne recevoir que ces canaux |

Ou par commande JSON après connexion : `{"subscribe": [...]}`,
`{"subscribe": "*"}`, `{"full": true}`.

Trois types de messages :

- `hello` — schéma des canaux, unités, catégories, cadence, véhicule courant.
  Un client n'a donc rien à coder en dur.
- `telemetry` — les mesures. Par défaut **différentiel** : seuls les champs
  qui varient sont émis, avec un état complet toutes les 2 s. Un client sans
  état accumulé doit demander `?full=1`.
- `status` — toutes les secondes, sert aussi de battement de cœur.
  `receiving: false` signifie qu'aucun paquet n'arrive du jeu ; des paquets
  qui arrivent sans rien faire varier (menu, voiture à l'arrêt) restent
  `true`.

## Canaux

**88 canaux bruts** décodés du paquet, plus **19 canaux dérivés** calculés par
la passerelle. Les bruts ne sont jamais remplacés : tout est ajouté.

| Dérivé | Depuis | Unité |
|---|---|---|
| `speed_kmh`, `speed_mph` | `speed` (m/s) | km/h, mph |
| `rpm_ratio` | régime ÷ régime max | 0-1 |
| `throttle`, `brake_pedal`, `clutch_pedal`, `handbrake_pedal` | octets 0-255 | 0-1 |
| `steer_norm` | `steer` (-127..127) | -1..1 |
| `g_lateral`, `g_vertical`, `g_longitudinal` | accélérations (m/s²) | g |
| `yaw_deg`, `pitch_deg`, `roll_deg` | radians | degrés |
| `tire_temp_*_c` | °F | °C |
| `slip_max` | le plus fort des 4 glissements | normalisé |

Les grandeurs bornées se branchent directement sur une opacité, une échelle ou
un volume. `--no-derived` les désactive.

### Lissage

La télémétrie est bruitée. Le lissage est réglable canal par canal, par une
constante de temps en secondes :

```bash
python main.py --smooth "slip_max=0.15, g_lateral=0.15"
```

Il est **additif** : `slip_max_smooth` apparaît à côté de `slip_max`, qui
reste intact. Un filtre retarde et rabote les extrêmes — écraser la valeur
brute falsifierait la télémétrie pour qui l'analyse. Mesuré sur données
réelles : 60 à 75 % d'agitation en moins sur les canaux bruités, extrêmes
conservés dans le brut.

Les entiers significatifs (rapport de boîte, numéro de tour, identifiant de
véhicule) ne sont jamais lissés : une moyenne entre deux rapports donnerait
2,7.

## Interface graphique

`python gui.py`

- réception, destinations OSC, serveur WebSocket
- les 107 canaux par catégorie, avec valeurs en direct, filtre et sélection
- champ de lissage, colonne indiquant le réglage effectif
- véhicule détecté : nom, classe, PI, transmission, cylindres
- indicateur d'état à code couleur, repris dans la barre d'état système

Fermer la fenêtre replie l'application dans la barre système sans arrêter la
passerelle. Les réglages sont enregistrés dans `config.json`.

## TouchDesigner

`touchdesigner/` contient deux scripts constructeurs, à coller dans un
**Text DAT** (langage Python) et à exécuter une fois :

- `build_forza_bridge_component.py` — crée un composant `forza_bridge` avec
  un OSC In CHOP réglé (`Strip Prefix Segments = 1`, donc `/forza/speed`
  devient le canal `speed`), une sortie Null CHOP et la table des canaux.
  Sauvegardé en `.tox` réutilisable.
- `build_forza_dashboard.py` — tableau de bord de base : vitesse, régime,
  rapport, g-mètre. À exécuter **à l'intérieur** du composant.

## cables.gl

`cables/build_cables_patch.py` génère un patch `.cables` complet, branché sur
la passerelle, affichant véhicule, vitesse et régime dans une barre latérale.

```bash
python cables/build_cables_patch.py --gabarit chemin/vers/un_patch.cables
```

Le `--gabarit` reprend l'identité locale et la version du logiciel d'un patch
existant, ce qui évite les écarts de format. Ouvrir ensuite par
**File → Open patch** : le glisser-déposer part dans le téléverseur d'assets
et échoue.

L'URL du patch porte `?full=1`, car cables traite chaque message isolément :
en différentiel, un champ figé y arriverait vide.

## Table des véhicules

`car_ordinals.json` traduit l'identifiant numérique envoyé par le jeu en nom
lisible (660 véhicules). Elle vient d'une liste communautaire, donc figée :
les voitures ajoutées par les mises à jour du jeu s'affichent
« Véhicule inconnu (ordinal N) », et ces ordinaux sont notés dans
`car_ordinals_unknown.json`.

```bash
python tools/update_car_table.py            # aperçu des différences
python tools/update_car_table.py --ecrire   # applique
```

## Tests

```bash
python -m unittest discover -v
```

Aucune dépendance à installer : bibliothèque standard uniquement. Les tests
couvrent le décodage du paquet, le catalogue, les canaux dérivés, le lissage,
la boucle de la passerelle, le serveur WebSocket et le service HTTP.

Chaque test qui protège une correction porte en commentaire le défaut qu'il
empêche de revenir. Plusieurs sont des **contre-épreuves** : elles vérifient
qu'en désactivant l'option testée le comportement redevient bien l'ancien,
sans quoi le test principal passerait même si la fonctionnalité ne servait à
rien.

## Structure

| Fichier | Rôle |
|---|---|
| `forza_telemetry.py` | décodage du paquet UDP |
| `channel_catalog.py` | catégories, unités, sélection par défaut |
| `derived_channels.py` | canaux calculés |
| `smoothing.py` | lissage temporel additif |
| `car_lookup.py` | ordinal → véhicule, classes, transmissions |
| `bridge.py` | boucle réception → OSC + WebSocket |
| `ws_server.py` | serveur WebSocket (différentiel, abonnements, état) |
| `http_assets.py` | overlay servi sur le port du WebSocket |
| `main.py` / `gui.py` | ligne de commande / interface |
| `tray.py` | icône de barre d'état système |
| `web/overlay.html` | overlay de démonstration |

## Dépendances

`python-osc` et `websockets` sont nécessaires. `pystray` et `Pillow` ne
servent qu'à l'icône de barre d'état : sans eux, l'interface reste une fenêtre
ordinaire.
