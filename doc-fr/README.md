# PiouPiou — fabriquer une boîte qui reconnaît les oiseaux

*Un détecteur d'oiseaux autonome : un Raspberry Pi écoute le jardin en
permanence, identifie chaque chant avec BirdNET, et affiche l'oiseau, sa photo
et le score de confiance sur un petit écran. Un bouton fait défiler les
écrans, une LED respire quand la boîte est en vie et clignote quand elle
entend quelque chose.*

Ce guide est écrit pas à pas, façon *Instructables*, pour être reproduit sans
avoir suivi le projet d'origine. Chaque étape dit **ce qu'il faut**, **ce
qu'il faut faire** et surtout **comment vérifier** que ça a marché avant de
passer à la suite. Les pièges rencontrés en cours de route sont signalés avec
⚠️ : la plupart ont coûté des heures, aucun n'est évident.

> **Temps** : une bonne journée pour l'électronique et le logiciel, plus la
> découpe et le montage du boîtier. **Niveau** : bricoleur à l'aise avec un
> terminal Linux et un fer à souder. **Budget** : voir l'estimation en fin de
> liste de matériel — de l'ordre de 40 à 60 € hors Pi et hors alimentation.

---

## Sommaire

1. [Ce que fait la boîte](#1-ce-que-fait-la-boîte)
2. [Matériel](#2-matériel)
3. [Câblage](#3-câblage)
4. [Alimentation — lisez ceci avant tout](#4-alimentation--lisez-ceci-avant-tout)
5. [Étape 1 — Préparer le Raspberry Pi](#étape-1--préparer-le-raspberry-pi)
6. [Étape 2 — Activer SPI, I2S et les GPIO](#étape-2--activer-spi-i2s-et-les-gpio)
7. [Étape 3 — Configurer le micro (ALSA)](#étape-3--configurer-le-micro-alsa)
8. [Étape 4 — Installer BirdNET-Go](#étape-4--installer-birdnet-go)
9. [Étape 5 — Configurer BirdNET-Go](#étape-5--configurer-birdnet-go)
10. [Étape 6 — L'écran](#étape-6--lécran)
11. [Étape 7 — Le bouton et la LED](#étape-7--le-bouton-et-la-led)
12. [Étape 8 — Les services au démarrage](#étape-8--les-services-au-démarrage)
13. [Étape 9 — Les photos hors-ligne](#étape-9--les-photos-hors-ligne)
14. [Étape 10 — Le WiFi](#étape-10--le-wifi)
15. [Étape 11 — Le boîtier](#étape-11--le-boîtier)
16. [Comment ça marche au quotidien](#comment-ça-marche-au-quotidien)
17. [Dépannage — les leçons apprises](#dépannage--les-leçons-apprises)
18. [Fichiers du dépôt](#fichiers-du-dépôt)

---

## 1. Ce que fait la boîte

- **Écoute en continu** avec un micro MEMS I2S, sans carte son USB.
- **Identifie** chaque chant avec [BirdNET-Go](https://github.com/tphakala/birdnet-go),
  filtré sur les ~220 espèces plausibles à votre position et à la saison.
- **Affiche** sur un écran 240×280 : la photo de l'oiseau, son nom français,
  le nom latin, l'heure et le score. L'oiseau apparaît **3 à 4 secondes**
  après le chant — bien avant que BirdNET-Go ne l'ait écrit en base.
- **Fonctionne hors-ligne** : les photos des espèces de la région sont
  pré-téléchargées et rafraîchies chaque mois.
- **Un bouton** fait défiler trois écrans (attente, espèces du jour, état
  système) et permet d'éteindre proprement par un appui long.
- **Une LED** dans le bouton respire quand le Pi est allumé et clignote
  pendant qu'un oiseau est à l'écran.
- L'écran s'endort après 10 minutes de calme et **se réveille au bruit**.
- Une interface web complète (BirdNET-Go) reste accessible sur le port 8080.

---

## 2. Matériel

| Composant | Détail | Note |
|---|---|---|
| Raspberry Pi 3 Model B | rév. 1.2, 1 Go, 4 cœurs | Le projet est né en croyant avoir un **3 B+** ; c'était un **3 B**. Vérifiez : `cat /proc/device-tree/model`. Un Pi 4 marcherait aussi, avec plus de marge. |
| Carte microSD | ≥ 16 Go, classe A1 | 14 Go utilisés sur 16 après tout ça, il reste 9 Go. |
| **Alimentation 5 V ≥ 2,5 A de bonne qualité** | voir §4 | ⚠️ **Le point n°1.** Deux chargeurs USB et deux câbles ont échoué. |
| Micro INMP441 | breakout I2S MEMS, ~15×13 mm | Le canal L/R est relié à GND (canal gauche). |
| Écran TFT IPS 1,69" 240×280 | module **42 × 41 mm**, coins arrondis, contrôleur **NV3030B** | ⚠️ Beaucoup de modules "1,69 pouces" sont en **ST7789V3**, d'autres en **NV3030B**. Ils ont le même brochage mais **pas la même initialisation**. Le pilote fourni gère le NV3030B ; voir §6. |
| Bouton poussoir momentané Ø 5 mm avec LED intégrée | | La LED est pilotée en PWM logiciel par le noyau. |
| **Dissipateur** pour le SoC | obligatoire | 4 cœurs à fond = 79 °C sans rien, la limite est à 80 °C. |
| Fils Dupont femelle-femelle, entretoises M2,5 | | |
| MDF 3 mm (une plaque 600×200 suffit) | découpe laser | Fichier fourni, voir §11. |

**Ordre de grandeur des prix** (2026, revendeurs hobbyistes ; **indicatif**,
non vérifié pendant le projet) :

| Poste | ~ € |
|---|---|
| Micro INMP441 | 3–6 |
| Écran 1,69" 240×280 | 5–10 |
| Bouton à LED | 2–5 |
| Dissipateur | 2–5 |
| Fils Dupont, entretoises M2,5 | ~5 |
| Carte microSD 16–32 Go | 8–12 |
| MDF 3 mm + découpe laser (fablab) | 5–30 selon l'accès à une machine |
| **Total hors Pi et hors alimentation** | **~40–60** |

L'alimentation est à part : l'alim officielle Raspberry Pi coûte ~10–15 €,
une alim de laboratoire bien plus, mais vous en avez peut-être déjà une. Le
Raspberry Pi 3 B lui-même se trouve d'occasion.

**Logiciel** : Raspberry Pi OS Lite **64 bits** (Debian 13 « trixie », noyau 6.18),
BirdNET-Go version `20260823` (binaire arm64), Python 3.13.

---

## 3. Câblage

Tous les numéros de **broches** sont ceux du connecteur 40 broches (broche 1 =
3,3 V, coin côté carte SD). Les numéros **GPIO** sont ceux du BCM.

### Micro INMP441 (I2S)

| Micro | Broche | GPIO / fonction |
|---|---|---|
| VDD | 1 | 3,3 V |
| GND | 9 | GND |
| L/R | → GND | sélectionne le canal gauche |
| SD | 38 | GPIO 20 / PCM_DIN |
| SCK | 12 | GPIO 18 / PCM_CLK |
| WS | 35 | GPIO 19 / PCM_FS |

### Écran (SPI0)

| Écran | Couleur (au choix) | Broche | GPIO / fonction |
|---|---|---|---|
| GND | marron | **6** | GND |
| VCC | rouge | **17** | **3,3 V** |
| SCL | orange | 23 | GPIO 11 / SPI0_SCLK |
| SDA | jaune | 19 | GPIO 10 / SPI0_MOSI |
| RES | vert | 22 | GPIO 25 |
| DC | bleu | 18 | GPIO 24 |
| CS | violet | 24 | GPIO 8 / SPI0_CE0 |
| BLK | gris | 15 | GPIO 22 (rétro-éclairage) |

⚠️ **Le piège qui a tué le premier écran** : GND sur une broche 5 V (2 ou 4) et
VCC sur 3,3 V. Le contrôleur est mort en polarisation inverse ; le
**rétro-éclairage continuait de fonctionner**, ce qui a rendu la panne
invisible. Les broches 2 (5 V) et 6 (GND) sont voisines en diagonale : c'est
exactement comme ça que l'erreur arrive. **Vérifiez ces deux fils au
multimètre avant de mettre sous tension.**

Si le PCB de votre écran porte la mention **« CS low »** avec un pont de
soudure fermé, le CS est déjà relié à la masse sur la carte : **ne câblez pas
CS** sur la broche 24 (le Pi tire CE0 à l'état haut au repos, ce serait un
court-circuit sur GPIO 8). Le logiciel s'en fiche.

MISO (broche 21) reste libre : l'écran ne renvoie rien.

### Bouton et LED

| | Broche | GPIO |
|---|---|---|
| Bouton, une patte | **40** | GPIO 21 (pull-up interne) |
| Bouton, autre patte | **39** | GND |
| LED anode (+) | **37** | GPIO 26 |
| LED cathode (−) | GND | via une résistance ~220–330 Ω si le bouton n'en intègre pas |

Les broches 39 et 40 sont les deux dernières du connecteur, côte à côte : un
connecteur 2 points s'y enfiche sans risque de se tromper.

---

## 4. Alimentation — lisez ceci avant tout

C'est la cause de **la moitié des problèmes** rencontrés, et elle se déguise
en problèmes logiciels : lenteur, WiFi qui tombe, redémarrages, détections
qui prennent 20 secondes.

### Comment savoir si vous êtes concerné

```bash
vcgencmd get_throttled
vcgencmd measure_clock arm
```

| Résultat | Signification |
|---|---|
| `throttled=0x0` et `1200000000` | Tout va bien. |
| `throttled=0x50005` et `600000000` | ⚠️ **Sous-tension en cours**, le CPU tourne à **moitié vitesse**. |
| `throttled=0x50000` | Il y a eu de la sous-tension depuis le démarrage (bits collants). |

Bit 0 = sous-tension *maintenant*, bit 2 = bridé *maintenant*, bits 16/18 =
c'est arrivé. `dmesg | grep -i undervoltage` compte les événements.

### Pourquoi un chargeur « 5 V 2 A » ne suffit pas

Ce n'est **pas une question de puissance moyenne** — la boîte consomme 3 à 4 W.
C'est une question d'**impédance et de transitoires** :

- Un câble micro-USB fin fait 0,2 à 0,5 Ω aller-retour. Les rafales de calcul
  NEON de BirdNET tirent des pics de 1,5 A pendant quelques millisecondes :
  0,4 Ω × 1,5 A = 0,6 V de chute. Le Pi 3 coupe à **4,63 V**. Un chargeur à
  5,0 V arrive donc à 4,4 V sur la carte au moment où ça compte.
- Beaucoup de chargeurs tiennent 4,8 V sous charge et régulent trop lentement
  pour suivre ces transitoires.
- Le connecteur micro-USB et le polyfusible ajoutent encore de la résistance.

La preuve pendant le projet : **4 cœurs de calcul entier** en boucle
tenaient 1,2 GHz sans broncher, mais **l'inférence NEON** faisait chuter à
600 MHz immédiatement. Même puissance moyenne, pics différents.

### Ce qui a marché

Une **alimentation de laboratoire réglée à 5,1 V**, câblée **directement sur
les broches 5 V du GPIO** (broche 2 ou 4 = 5 V, broche 6 = GND). Résultat :
`throttled=0x0`, zéro événement de sous-tension, même à froid au démarrage.

⚠️ En alimentant par le GPIO, vous **contournez le polyfusible** du Pi :

- Réglez la **limite de courant de l'alim à 2–2,5 A**, pas plus.
- Une inversion de polarité sur ces broches **détruit la carte** instantanément
  et sans protection. Étiquetez les deux fils.

L'alimentation officielle Raspberry Pi (câble captif dimensionné pour ça) est
l'alternative propre si vous ne voulez pas d'alim de labo.

### Et la chaleur

Un dissipateur passif est **obligatoire**. Mesuré à nu : 55 °C au repos,
79 °C avec 4 cœurs chargés, pour une limite de bridage à 80 °C. Avec
dissipateur et en fonctionnement normal : 58–67 °C. Dans le boîtier, comptez
quelques degrés de plus — d'où les aérations (§11).

---

## Étape 1 — Préparer le Raspberry Pi

**Ce qu'il faut** : le Pi, la microSD, un PC avec Raspberry Pi Imager.

1. Avec **Raspberry Pi Imager**, flashez **Raspberry Pi OS Lite (64-bit)**.
   Dans les options : nom d'hôte `pioupiou`, utilisateur `piou`, activez
   **SSH**, renseignez votre WiFi.
2. Démarrez, connectez-vous : `ssh piou@pioupiou.local`.
3. Mettez à jour et installez les dépendances :

```bash
sudo apt update
sudo apt install -y ffmpeg sox libsox-fmt-all python3-venv python3-dev \
    libgpiod-dev python3-yaml rfkill iw
```

> `ffmpeg` tire ~500 Mo de dépendances sur un Lite et prend plusieurs minutes
> sur un Pi 3. C'est normal. Il sert aux clips audio et aux spectrogrammes de
> l'interface web.

**Vérifiez** :

```bash
cat /proc/device-tree/model     # "Raspberry Pi 3 Model B Rev 1.2"
cat /etc/os-release | head -2   # Debian GNU/Linux 13 (trixie)
free -h                         # ~905 Mi
```

---

## Étape 2 — Activer SPI, I2S et les GPIO

**Ce qu'il faut** : `config/config.txt.snippet` du dépôt.

1. Sauvegardez : `sudo cp /boot/firmware/config.txt /boot/firmware/config.txt.bak.orig`
2. Dans `/boot/firmware/config.txt`, changez la ligne existante
   `dtparam=audio=on` en **`dtparam=audio=off`** — sinon la carte son HDMI/analogique
   prend la place de carte 0 et le micro se retrouve en carte 1.
3. Ajoutez à la fin le bloc de `config/config.txt.snippet` :

```ini
[all]
dtparam=spi=on                        # écran
dtparam=i2s=on                        # micro
dtoverlay=googlevoicehat-soundcard    # le micro I2S devient une carte ALSA
gpio=22=op,dh                         # rétro-éclairage allumé dès le boot
dtoverlay=pwm-gpio,gpio=26            # PWM noyau pour la LED
```

4. `sudo reboot`

**Vérifiez** après redémarrage :

```bash
ls -l /dev/spidev0.0          # doit exister
arecord -l                    # card 0: sndrpigooglevoi [...] Google voiceHAT SoundCard
ls /sys/class/pwm/            # pwmchip0
```

> Pourquoi `googlevoicehat-soundcard` ? C'est l'overlay du Google AIY Voice
> HAT, qui utilise exactement le même bus I2S sur GPIO 18/19/20. Il expose
> un périphérique de capture **S32_LE, 48 kHz, 2 canaux** — le format natif
> de l'INMP441. C'est le raccourci standard pour ce micro sur Pi.

---

## Étape 3 — Configurer le micro (ALSA)

**Ce qu'il faut** : `config/asound.conf`.

Le périphérique brut est stéréo 32 bits, mais le micro n'émet que sur le
canal gauche et BirdNET-Go veut du mono 16 bits à 48 kHz. `asound.conf`
construit une chaîne : `hw` → `dsnoop` (partage entre plusieurs lecteurs) →
`plug` qui extrait le canal gauche, **applique +24 dB**, et convertit.

```bash
sudo cp config/asound.conf /etc/asound.conf
```

**Vérifiez** qu'on capture bien, puis mesurez le niveau :

```bash
arecord -D birdmic -f S16_LE -r 48000 -c 1 -d 5 /tmp/test.wav
python3 - <<'PY'
import wave, array, math
w=wave.open('/tmp/test.wav'); a=array.array('h'); a.frombytes(w.readframes(w.getnframes()))
pk=max(max(a),-min(a)); rms=(sum((v/32768.0)**2 for v in a)/len(a))**0.5
print(f"pic {20*math.log10(max(pk,1)/32768):.1f} dBFS ({pk} LSB)  rms {20*math.log10(max(rms,1e-12)):.1f} dBFS")
PY
```

Dans une pièce calme, attendez-vous à un pic vers **−35 à −40 dBFS** et un RMS
vers **−50 à −58 dBFS**. Parlez fort à côté : le pic doit monter sans dépasser
0 dBFS (pas d'écrêtage).

Testez aussi que **deux lecteurs simultanés** marchent (c'est ce qui permet à
l'écran de surveiller le niveau pendant que BirdNET-Go écoute) :

```bash
arecord -D birdmic -f S16_LE -r 48000 -c 1 -d 4 /tmp/a.wav &
sleep 1; arecord -D birdmic -f S16_LE -r 48000 -c 1 -d 2 /tmp/b.wav && echo OK
```

⚠️ **Deux pièges dans ce fichier, tous deux essentiels** :

- **Le bloc `hint { … }` n'est pas décoratif.** BirdNET-Go énumère les
  périphériques via les *name hints* ALSA. Un PCM sans `hint` est invisible
  pour lui — et le `sysdefault` de sa config par défaut **n'existe pas** dans
  cette énumération. Symptôme : `no device found matching "sysdefault"` dans
  `logs/audio.log`, et zéro capture.
- **Le gain se fait ici, en 32 bits, pas dans BirdNET-Go.** Sans lui, le
  pic ambiant était de **30 LSB sur 32768** : le signal n'utilisait que ~5
  des 16 bits. Le `gain` de BirdNET-Go s'applique *après* la conversion en
  16 bits et ne ferait qu'amplifier le bruit de quantification. `ttable.0.0 16`
  (×16 = +24 dB) sur les échantillons 32 bits a fait passer le pic à
  **~1000 LSB** — 11 bits utiles — sans changer le rapport signal/bruit du micro.

---

## Étape 4 — Installer BirdNET-Go

**Ce qu'il faut** : une connexion internet (~110 Mo à télécharger).

1. Récupérez la dernière version arm64 et son checksum :

```bash
V=20260823   # vérifiez la dernière sur https://github.com/tphakala/birdnet-go/releases
cd /tmp
curl -fL -o bng.tar.gz "https://github.com/tphakala/birdnet-go/releases/download/$V/birdnet-go-linux-arm64-$V.tar.gz"
curl -fL -o checksums.txt "https://github.com/tphakala/birdnet-go/releases/download/$V/checksums.txt"
grep linux-arm64 checksums.txt | sed "s#birdnet-go-linux-arm64-$V.tar.gz#bng.tar.gz#" | sha256sum -c -
```

2. Installez :

```bash
mkdir -p bng && tar xzf bng.tar.gz -C bng && cd bng
sudo install -m 0644 libonnxruntime.so libtensorflowlite_c.so /usr/local/lib/
sudo ldconfig
sudo install -m 0755 birdnet-go /usr/local/bin/birdnet-go
sudo mkdir -p /var/lib/birdnet-go && sudo chown piou:piou /var/lib/birdnet-go
```

3. Premier lancement — il crée le fichier de config et télécharge le modèle :

```bash
birdnet-go --version
# Created default config file at: /home/piou/.config/birdnet-go/config.yaml
```

**Vérifiez** que le Pi tient la charge avec le benchmark intégré :

```bash
birdnet-go benchmark
```

Attendu sur un Pi 3 B à **1,2 GHz** avec XNNPACK : ~300–450 ms par inférence.
Si vous lisez **~620 ms**, votre CPU est probablement bridé à 600 MHz — retournez
au §4.

---

## Étape 5 — Configurer BirdNET-Go

**Ce qu'il faut** : `config/birdnet-go.settings.yaml`, vos coordonnées GPS.

Le fichier généré fait 600 lignes. Ne le réécrivez pas ; **fusionnez** juste
les valeurs de `config/birdnet-go.settings.yaml`. Le plus sûr est un petit
patch Python :

```bash
python3 - <<'PY'
import yaml
p='/home/piou/.config/birdnet-go/config.yaml'
c=yaml.safe_load(open(p))
c['main']['name']='PiouPiou'
b=c['birdnet']; b['locale']='fr'; b['latitude']=43.9509; b['longitude']=4.8074; b['locationconfigured']=True
s=c['realtime']['audio']['sources'][0]; s['name']='Micro I2S INMP441'; s['device']='birdmic'; s['gain']=0
c['realtime']['log']={'enabled':True,'path':'birdnet.txt'}
c['realtime']['telemetry']['enabled']=False
c['realtime']['privacyfilter']['confidence']=0.7
for m in ('access','telemetry'): c['logging']['modules'][m]['enabled']=False
c['notification']['push']['enabled']=True
c['notification']['push']['providers']=[{'type':'script','enabled':True,'name':'piou-events',
  'command':'/opt/piou/bin/birdnet-event.sh','input_format':'both','timeout':'10s',
  'filter':{'types':['detection'],'priorities':[],'components':[]}}]
yaml.safe_dump(c,open(p,'w'),sort_keys=False,allow_unicode=True,default_flow_style=False)
print("ok")
PY
```

Remplacez la latitude/longitude par les vôtres. Tout le reste reste **à la
valeur par défaut**, et ce n'est pas par paresse : voir le dépannage pour ce
qui s'est passé en touchant à `threshold`, `overlap`, `export.length` et
`dynamicthreshold`.

Installez le script d'événements :

```bash
sudo mkdir -p /opt/piou/bin /var/lib/piou/imgcache && sudo chown -R piou:piou /opt/piou /var/lib/piou
cp bin/birdnet-event.sh /opt/piou/bin/ && chmod +x /opt/piou/bin/birdnet-event.sh
```

**Vérifiez** en lançant à la main 60 secondes :

```bash
cd /var/lib/birdnet-go && timeout 90 birdnet-go serve
grep -E 'capture started|capture failed' /var/lib/birdnet-go/logs/audio.log | tail -2
```

Vous devez voir `capture started … device_id=birdmic`. Ensuite l'interface web
répond sur `http://pioupiou.local:8080`.

⚠️ **`privacyfilter.confidence`** : la valeur d'origine est **0,05**. Elle
signifie « s'il y a 5 % de chances qu'un humain ait parlé dans cette fenêtre
de 3 s, jette **toutes** les détections d'oiseaux de la fenêtre ». Dans une
pièce où l'on discute, c'est presque toujours vrai. Symptôme, bien
déroutant : `max_confidence=0.96` mais `passed_filter=0` dans les stats.
À 0,7, le filtre garde son rôle (ne pas enregistrer de voix dans les clips)
sans manger les oiseaux.

---

## Étape 6 — L'écran

**Ce qu'il faut** : le dossier `display/` du dépôt, l'écran câblé.

### 6.1 L'environnement Python

```bash
python3 -m venv /opt/piou/venv
/opt/piou/venv/bin/pip install --upgrade pip wheel
/opt/piou/venv/bin/pip install --only-binary=:all: pillow gpiod gpiodevice numpy requests st7789
/opt/piou/venv/bin/pip install spidev      # pas de wheel arm64 : se compile en quelques secondes
```

Puis copiez les scripts :

```bash
mkdir -p /opt/piou/display && cp display/*.py /opt/piou/display/
```

### 6.2 Quel contrôleur avez-vous ?

Le module 1,69" 240×280 existe avec **deux contrôleurs différents** qui ont
le même brochage : **ST7789V3** et **NV3030B**. Le dépôt fournit
`display/nv3030b.py`, qui s'appuie sur la bibliothèque `st7789` de Pimoroni
pour toute la plomberie (SPI, gpiod, fenêtrage) mais remplace la **séquence
d'initialisation** par celle du NV3030B, vérifiée sur deux implémentations
indépendantes.

Si votre panneau est un vrai ST7789V3, la bibliothèque `st7789` seule devrait
suffire… **à condition de corriger son bug de reset** (§6.4).

### 6.3 Premier test

```bash
cd /opt/piou/display
/opt/piou/venv/bin/python piou_display.py --selftest --hold-oneshot 60
```

Un motif de test s'affiche 60 s : bordure blanche sur les **4 bords**, barres
rouge/vert/bleu **dans cet ordre**, un cercle **rond** (pas ovale), « HAUT »
en haut. Chaque défaut correspond à une option :

| Vous voyez | Correction |
|---|---|
| Bord haut ou bas coupé, ou une bande de 20 px décalée | `--offset-top 0` ou `40` (20 est la valeur normale pour un 240×280 dans la RAM 240×320 du contrôleur) |
| À l'envers | `--rotation 180` (90/270 sont refusés pour un panneau non carré) |
| Rouge et bleu inversés | `--no-bgr` |
| Image en négatif | `--no-invert` |
| Rien du tout, mais le rétro-éclairage s'allume | voir §6.4 — ce n'est probablement **pas** le câblage |

Puis une vraie trame de détection (télécharge une photo via BirdNET-Go, qui
doit tourner) :

```bash
/opt/piou/venv/bin/python piou_display.py --demo --hold-oneshot 60
```

### 6.4 ⚠️ Le bug qui a fait croire à deux écrans morts

La bibliothèque **`st7789` 1.0.0** (celle que `pip` installe) a un bug : son
constructeur demande la ligne **RES** en sortie **à l'état bas**… et **n'appelle
jamais `reset()`**. Le panneau reste en reset permanent et avale toutes les
commandes sans erreur. Résultat : le rétro-éclairage fonctionne, le SPI
« marche », rien ne s'affiche. Deux panneaux ont été soupçonnés à tort.

Le diagnostic qui l'a trouvé, à retenir :

```bash
pinctrl get 25        # RES doit être "op ... hi". Si "lo" pendant que le script tourne : c'est ça.
```

`nv3030b.py` contourne le problème : `hard_reset()` fait une vraie impulsion
de reset et **garde la ligne** (l'objet gpiod retourné doit rester référencé,
sinon la broche retombe à zéro et le panneau se re-bloque), puis le panneau
est construit avec `rst=None`. La version 1.0.1 de la bibliothèque corrige le
bug côté amont.

### 6.5 Mesurer, pas deviner

`pinctrl` vous dit l'état réel de chaque broche (`op`/`ip`, `hi`/`lo`, `a0` =
fonction SPI). Deux tests qui lèvent tout doute sur le câblage sans
instrument :

```bash
pinctrl set 25 ip pu ; pinctrl get 25    # pull-up interne : "lo" = court-circuit à la masse
pinctrl set 25 ip pd ; pinctrl get 25    # pull-down : "hi" = le module a sa propre résistance de tirage
                                         # (= le fil RES est bien connecté)
pinctrl set 25 op dh                     # remettre en sortie haute
```

---

## Étape 7 — Le bouton et la LED

**Ce qu'il faut** : `led/piou_led.py`, `systemd/piou-led.service`.

Le bouton est lu par `display/piou_button.py` (gpiod, pull-up interne,
anti-rebond 50 ms, appui long à 2 s). Rien à installer de plus : le service
d'affichage le gère.

La LED, en revanche, a son propre petit service qui **démarre avant le réseau
et avant BirdNET-Go** — c'est le seul signe que la boîte est en vie, il ne doit
dépendre de rien :

```bash
cp led/piou_led.py /opt/piou/bin/ && chmod +x /opt/piou/bin/piou_led.py
sudo install -m 0644 systemd/piou-led.service /etc/systemd/system/
```

Pourquoi le PWM **noyau** (`dtoverlay=pwm-gpio,gpio=26`, §2) et pas une boucle
Python ? GPIO 26 n'a pas de PWM matériel (seuls 12/13/18/19 en ont), et
basculer une broche à 400 Hz depuis Python scintille visiblement. Le noyau
tient la cadence ; le script ne fait que réécrire un rapport cyclique 50 fois
par seconde. Coût : négligeable.

La respiration est **corrigée en gamma** (2,2) : l'œil perçoit la luminosité
d'une LED comme la puissance 2,2 du rapport cyclique, une rampe linéaire
paraît traîner en haut et claquer en bas. Plancher à 2 % pour ne jamais
s'éteindre tout à fait.

**Le clignotement** vient de l'écran : quand un oiseau s'affiche, le service
d'affichage écrit une date-limite dans `/run/piou/led-blink-until`, et la LED
clignote à 4 Hz tant qu'elle n'est pas dépassée. Un fichier plutôt qu'une
socket, exprès : la LED n'hérite ainsi d'aucune dépendance.

**Vérifiez** après l'étape 8 :

```bash
echo $(( $(date +%s) + 8 )) > /run/piou/led-blink-until   # doit clignoter 8 s puis re-respirer
journalctl -u piou-led -n 3 -o cat                          # "blink" puis "breathe"
```

---

## Étape 8 — Les services au démarrage

**Ce qu'il faut** : le dossier `systemd/`, `config/sudoers-piou-poweroff`.

```bash
sudo install -m 0644 systemd/birdnet-go.service systemd/piou-display.service \
     systemd/piou-precache.service systemd/piou-precache.timer /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/piou-display.service.d
sudo install -m 0644 systemd/piou-display.service.d/10-runtime-dir.conf \
     /etc/systemd/system/piou-display.service.d/

# le bouton peut éteindre la boîte : une seule commande autorisée, sans mot de passe
sudo install -m 0440 -o root -g root config/sudoers-piou-poweroff /etc/sudoers.d/piou-poweroff
sudo visudo -c -f /etc/sudoers.d/piou-poweroff

sudo systemctl daemon-reload
sudo systemctl enable --now birdnet-go piou-led piou-display piou-precache.timer
```

**Vérifiez** :

```bash
systemctl is-active birdnet-go piou-led piou-display piou-precache.timer   # 4 × active
journalctl -u piou-display -n 8 -o cat
```

Attendu dans le journal de l'écran :

```
NV3030B ready: 240x280 rot=0 offs=(0,20) invert=True bgr=True spi=8.0 MHz
button ready on GPIO21 (to GND, internal pull-up)
level monitor reading birdmic
subscribed to detection stream
BirdNET-Go reachable
```

Puis **redémarrez** et vérifiez que tout revient tout seul : `sudo reboot`,
et les quatre services actifs. Au dernier test, la LED respirait **6 secondes
après la mise sous tension**, sans attendre les ~40 s de chargement du modèle.

---

## Étape 9 — Les photos hors-ligne

**Ce qu'il faut** : `bin/piou_precache.py`, BirdNET-Go en marche, internet.

L'écran obtient chaque photo via le proxy d'images de BirdNET-Go
(`/api/v2/media/image/<nom latin>`) et la garde en cache. Pour être autonome
sans réseau, on pré-remplit ce cache avec les espèces que le **filtre
géographique** de BirdNET-Go juge plausibles chez vous :

```bash
cp bin/piou_precache.py /opt/piou/bin/ && chmod +x /opt/piou/bin/piou_precache.py
/opt/piou/venv/bin/python /opt/piou/bin/piou_precache.py --dry-run
```

Le `--dry-run` annonce le nombre d'espèces avant de télécharger quoi que ce
soit (**222** en Provence début septembre, ~3 Mo, ~7 minutes à raison d'une
requête toutes les 2 s pour ménager Wikimedia/Avicommons). Puis :

```bash
sudo systemctl start piou-precache.service
journalctl -u piou-precache -f
```

Le **timer mensuel** installé à l'étape 8 rafraîchit ensuite le cache tout
seul, parce que le filtre géographique dépend de la **semaine de l'année** :
les migrateurs vont et viennent. Chaque passage ne télécharge que les
nouvelles espèces ; celles sans photo sont mémorisées dans
`_no_photo.json` pour ne pas être redemandées.

---

## Étape 10 — Le WiFi

Raspberry Pi OS Bookworm/Trixie utilise **NetworkManager**. Pour ajouter un
réseau sans passer le mot de passe sur la ligne de commande (il apparaîtrait
dans `ps`), écrivez directement le profil :

```bash
sudo tee /etc/NetworkManager/system-connections/MONRESEAU.nmconnection >/dev/null <<EOF
[connection]
id=MONRESEAU
uuid=$(uuidgen)
type=wifi
interface-name=wlan0
autoconnect=true
autoconnect-retries=0
autoconnect-priority=5

[wifi]
mode=infrastructure
ssid=MONRESEAU

[wifi-security]
key-mgmt=wpa-psk
psk=LE_MOT_DE_PASSE

[ipv4]
method=auto
[ipv6]
method=auto
EOF
sudo chmod 0600 /etc/NetworkManager/system-connections/MONRESEAU.nmconnection
sudo nmcli connection reload
```

`autoconnect-retries=0` signifie « réessaie indéfiniment » : par défaut NM
abandonne après 4 échecs, et la boîte s'est retrouvée sans WiFi une fois pour
cette raison. `autoconnect-priority` départage plusieurs réseaux connus.

**Vérifiez** : `nmcli device status` puis `sudo reboot` — le WiFi doit revenir
seul.

---

## Étape 11 — Le boîtier

**Ce qu'il faut** : `box/piou_box.py`, une plaque de MDF 3 mm, une découpeuse
laser.

Le boîtier est **paramétrique** : chaque cote est un champ nommé en tête de
`box/piou_box.py`. Il génère `box/piou_box.svg` avec les 13 pièces imbriquées
sur une plaque de **576 × 184 mm**. Rouge = découpe, bleu = gravure (repères
de placement, ne pas découper).

```bash
python3 box/piou_box.py
```

Le script **se vérifie avant d'écrire** : chaque paire d'arêtes qui
s'emboîtent est contrôlée complémentaire, chaque contour est contrôlé
rectiligne (une version antérieure coupait des pointes en diagonale dans les
coins), et il affiche les dégagements du Pi, la course de l'écran et la
position du bouton.

Avant de couper, **mesurez trois choses** au pied à coulisse et mettez-les
dans `Params` :

1. **Le contour du module écran** — `disp_pcb_w`/`disp_pcb_h` (42 × 41 mm
   ici). La poche a 0,4 mm de jeu par côté.
2. **Où se trouve le verre dans ce contour** — `disp_act_off_y`, distance du
   bord haut du PCB au haut de la dalle (4,2 mm si centré).
3. **Le trou du bouton** — `btn_hole_d` (5,2 mm pour un bouton Ø 5).

Coupez **une seule paroi latérale d'abord** pour tester l'ajustement : si les
tenons forcent trop, augmentez `kerf` ; s'ils flottent, diminuez-le.

Choix de conception à connaître :

- **Le panneau arrière n'est pas collé** — ses tenons sont coupés 0,1 mm plus
  petits et il a une fente « TIRER ». Sans ça, le Pi serait scellé pour
  toujours. Collez les 5 autres.
- **Aucune aération dans le fond** : une boîte posée sur une table bouche une
  aération basse. La convection se fait par des fentes **basses sur les
  côtés** (entrée) et **hautes + dessus** (sortie). Sans ce couple
  entrée/sortie, on obtient une poche d'air chaud, pas un flux.
- L'écran est **coincé dans une poche** (deux cadres empilés collés derrière
  la face avant), pas vissé : seul son contour compte, pas ses trous.
- Le micro va **sur le dessus**, à l'opposé des fentes de sortie pour que
  l'air chaud ne balaie pas son orifice. Son port acoustique doit être
  **plaqué** contre le trou de 5 mm.
- Les 4 rondelles surélèvent le Pi pour laisser l'air circuler dessous.

Une page de référence avec le plan, l'ordre d'assemblage et le schéma de
ventilation accompagne le fichier (générée depuis le même script).

---

## Comment ça marche au quotidien

### Les écrans

| Écran | Contenu | Comment y aller |
|---|---|---|
| **Attente** | « PiouPiou », l'heure, la date en français, « à l'écoute… », le nombre de détections du jour, la dernière espèce, et un **vu-mètre** discret dans l'en-tête | par défaut, ou appui court |
| **Espèces du jour** | liste triée par fréquence avec le compte | appui court |
| **Système** | IP, charge, température, mémoire, disque, uptime, **état de l'alimentation**, état de BirdNET-Go | appui court |
| **Extinction** | « Éteindre ? » avec compte à rebours 12 s | **appui long** (2 s) ; appui court = confirmer, appui long = annuler |

Le vu-mètre de l'en-tête (5 barres) indique le niveau **au-dessus du bruit de
fond** courant, qui se recalibre en permanence (25ᵉ percentile sur 20 s). Il
s'allume en vert à +9 dB. Il est redessiné 3 fois par seconde par une
**écriture partielle** de 43 × 13 px (~1 ms), pas une trame complète (134 ms).

### Une détection

```
chant                          0 s
nom + photo, "reconnaissance…" ~3–4 s   <- via le flux SSE "pending" de BirdNET-Go
score de confiance             ~15 s    <- quand BirdNET-Go l'écrit en base
retour à l'écran d'attente     +10 s après le score
```

Le nom apparaît **avant** l'écriture en base parce que l'écran s'abonne au
flux d'événements `pending` de BirdNET-Go — le même que son propre tableau de
bord utilise pour sa carte « en cours d'écoute ». Sans ça, il faudrait
attendre `export.length − precapture` = **12 s** de plus. Le score n'est pas
affiché tant qu'il n'est pas définitif : une détection en attente peut encore
être rejetée.

Une **nouvelle espèce** remplace l'affichage et relance les 10 s. Un appui sur
le bouton l'interrompt.

### Veille et réveil

- Après **10 minutes** sans oiseau ni bouton, l'écran s'éteint.
- Il se rallume sur un **appui** (qui ne fait que réveiller ; l'appui suivant
  fait défiler) ou sur un **bruit à +15 dB** au-dessus du fond. Le seuil de
  réveil est volontairement plus haut que celui du vu-mètre pour qu'une
  conversation ne le garde pas allumé toute la journée — et comme le fond se
  recalibre, une discussion continue finit par ne plus le déclencher.

### La LED

| État | LED |
|---|---|
| Pi allumé | respiration lente, cycle 4 s |
| Oiseau à l'écran | clignotement 4 Hz |
| Éteinte, Pi alimenté | quelque chose ne va pas (overlay PWM absent ?) |

### Le flux d'événements

Chaque *nouvelle* espèce (pas chaque détection — c'est une limite de
BirdNET-Go) est aussi ajoutée en JSON à `/var/lib/piou/events.jsonl`, pour
brancher autre chose dessus (domotique, notification…).

---

## Dépannage — les leçons apprises

Classées par ordre de temps perdu. Si quelque chose est lent, bizarre ou
intermittent, **commencez par le n°1**.

### 1. Tout est lent, ça plante, le WiFi tombe → alimentation

`vcgencmd get_throttled` ≠ `0x0` ou `measure_clock arm` = 600 MHz. Relisez le
§4. Aucun réglage logiciel ne compense un CPU à mi-vitesse : l'inférence tombe
sous la cadence audio, la file d'attente grandit et **le délai de détection
augmente à chaque minute** au lieu d'être constant.

### 2. L'écran reste noir (mais le rétro-éclairage marche)

Dans l'ordre :

1. `pinctrl get 25` pendant que le script tourne. **`lo` = bug de reset**
   (§6.4). Utilisez `nv3030b.py`.
2. Est-ce un NV3030B ? Le ST7789 ne l'initialise pas. La bibliothèque
   Pimoroni seule donnera du bruit ou rien.
3. GND et VCC : un panneau qui a vu 5 V sur GND est mort, rétro-éclairage
   compris ou non.
4. Vitesse SPI : 8 MHz a été validé sur des fils Dupont. 32 MHz peut donner
   du bruit en bas/à droite (trame tronquée).
5. `pinctrl get 8,10,11` doit montrer 10 et 11 en `a0` (SPI).

### 3. « no device found matching "sysdefault" »

BirdNET-Go ne voit que les PCM ALSA qui ont un bloc `hint`. Le `sysdefault`
de sa config n'en est pas un. Mettez `device: birdmic` et vérifiez avec
`grep "probing device" /var/lib/birdnet-go/logs/audio.log` que `birdmic` y
figure. Le fait qu'`arecord` fonctionne **ne prouve rien** : il ouvre des
périphériques que BirdNET-Go ne peut pas sélectionner.

### 4. Aucune détection alors que le micro entend

Cherchez la ligne `pipeline stats` dans `journalctl -u birdnet-go` :

```
inferences=199 raw_results=1990 passed_filter=0 max_confidence=0.96 threshold=0.7
```

`max_confidence` au-dessus du seuil avec `passed_filter=0` = **un filtre aval
jette tout**. Neuf fois sur dix : `privacyfilter.confidence` à 0,05 (§5), qui
se voit dans le journal en `human detection filtered confidence=0.051`. Le
`dogbarkfilter` (0,1, mémoire 5 min) a la même pathologie en puissance.

### 5. La détection met 15–20 s à s'afficher

Ce **n'est pas** `realtime.interval` (c'est la suppression de doublons, on s'y
est trompé). Le délai vient de :

```
detectionWindow = export.length − export.precapture   (15 − 3 = 12 s)
```

C'est le temps qu'une détection passe en attente avant d'être écrite en base
et visible par l'API REST. Le validateur impose `10 ≤ length ≤ 60` et
`precapture ≤ length/2`, donc le plancher est **5 s** (10/5) sans désactiver
l'export des clips. La vraie solution est celle de l'écran : **s'abonner au
flux SSE `pending`** (`/api/v2/detections/stream`), qui donne l'espèce dès
la création, et garder les clips à 15 s.

⚠️ Le payload de l'événement `pending` est un **tableau** (instantané de toutes
les détections en attente, tableau vide = plus rien en attente), pas un objet.
Un client qui attend un objet les ignore en silence.

### 6. Le score affiché est bas alors que l'oiseau était net

`dynamicthreshold.min: 0.2` (défaut) : après une détection à 90 %+, le seuil
de cette espèce descend à 0,2, et les fenêtres faibles qui suivent deviennent
des détections **séparées** (99 %, puis 52 %, puis 39 %). L'écran montre la
plus récente, donc la plus faible. Et chacune coûte un encodage de clip et un
spectrogramme — c'est aussi ce qui a créé une file d'attente.

### 7. Le délai augmente avec le temps

Comparez dans `pipeline stats` le nombre d'inférences sur 5 min à la demande :
avec `overlap 1.5` la fenêtre avance de 1,5 s, soit **0,667 inférence/s**
nécessaires. En dessous, la file grandit sans limite. Causes vues :
`threads: 3` (un cœur inutilisé), CPU bridé (§4), trop de détections
« poubelle » (§6) qui volent du CPU à l'inférence.

### 8. Le micro est trop faible

Pic de ~30 LSB → 5 bits utiles. Gain **en ALSA, en 32 bits** (§3), pas dans
BirdNET-Go. Un oiseau **lointain** reste un problème de rapport
signal/bruit que le gain ne crée pas : le placement du micro (dehors, ou à
une fenêtre ouverte) vaut plus que tous les réglages.

### 9. `OSError: [Errno 16] Device or resource busy` au redémarrage du service

Course entre l'ancien processus qui libère une ligne gpiod et le nouveau qui
la demande. Les scripts réessaient 5 s ; sans ça, systemd finit par gagner la
course mais après des échecs.

### 10. L'écran se rallume puis s'éteint aussitôt sur un appui

Le compteur d'inactivité n'était remis à zéro que par une détection, pas par
un appui. Un seul horodatage `last_activity` mis à jour par **tout** ce qui
allume l'écran règle ça.

### 11. L'oiseau disparaît puis revient avec son score

Deux minuteries non coordonnées, et un `hold` (10 s) plus court que le délai
de flush (12 s) : la fenêtre expirait avant le score. Désormais une seule
date-limite, et les 10 s sont comptées **à partir du score**. Le test qui
aurait dû l'attraper simulait une confirmation *dans* la fenêtre : un test
qui passe pour la mauvaise raison ne vaut rien.

### 12. Coins en diagonale sur le fichier laser

Les arêtes voisines de phases différentes étaient reliées en ligne droite au
lieu d'un escalier, et la compensation de kerf s'appliquait aux extrémités.
Invisible sur la face avant (toutes ses arêtes « hautes » aux coins), donc
invisible en n'inspectant qu'elle. Le générateur refuse maintenant tout
segment qui change x **et** y.

---

## Fichiers du dépôt

| Dépôt | Destination sur le Pi | Rôle |
|---|---|---|
| `display/piou_display.py` | `/opt/piou/display/` | l'application écran (écrans, détections, veille) |
| `display/nv3030b.py` | `/opt/piou/display/` | pilote NV3030B + reset correct + écriture partielle |
| `display/piou_button.py` | `/opt/piou/display/` | bouton, appuis courts/longs |
| `display/piou_listen.py` | `/opt/piou/display/` | niveau micro, bruit de fond, réveil au son |
| `display/piou_sse.py` | `/opt/piou/display/` | abonnement au flux `pending` |
| `led/piou_led.py` | `/opt/piou/bin/` | LED respiration / clignotement |
| `bin/piou_precache.py` | `/opt/piou/bin/` | pré-téléchargement des photos régionales |
| `bin/birdnet-event.sh` | `/opt/piou/bin/` | flux JSON des nouvelles espèces |
| `systemd/*.service`, `*.timer` | `/etc/systemd/system/` | démarrage automatique |
| `systemd/piou-display.service.d/` | `/etc/systemd/system/piou-display.service.d/` | crée `/run/piou` |
| `config/asound.conf` | `/etc/asound.conf` | chaîne micro `birdmic` |
| `config/config.txt.snippet` | à ajouter à `/boot/firmware/config.txt` | SPI, I2S, GPIO, PWM |
| `config/birdnet-go.settings.yaml` | à fusionner dans `~/.config/birdnet-go/config.yaml` | réglages hors défaut |
| `config/sudoers-piou-poweroff` | `/etc/sudoers.d/piou-poweroff` | extinction par le bouton |
| `box/piou_box.py` → `box/piou_box.svg` | — | boîtier paramétrique, fichier laser |

Dossiers à créer, propriété `piou` : `/opt/piou`, `/var/lib/birdnet-go`,
`/var/lib/piou/imgcache`.

Chaque script accepte `--help` ; les valeurs par défaut sont aussi
surchargeables par variables d'environnement (`PIOU_HOLD`, `PIOU_SLEEP`,
`PIOU_WAKE_TRIG`, `PIOU_LED_CYCLE`…) — pratique dans un *drop-in* systemd sans
toucher au code.

---

*Construit en septembre 2026. BirdNET-Go est l'œuvre de Tomi P. Hakala ;
le modèle BirdNET, celle de la Cornell Lab of Ornithology et de la TU Chemnitz.
La bibliothèque `st7789` est de Pimoroni ; la séquence NV3030B est
recoupée entre `circuitpython_NV3030B` et `STM32_Lib_TFT_NV3030B`.*
