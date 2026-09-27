Je configure un Raspberry Pi 3 B+ sous Raspberry Pi OS Lite (64-bit) pour exécuter BirdNET-Go localement avec un micro MEMS I2S et un petit écran TFT SPI.

Le rpi est accessible sur pioupiou.local. User piou (mot de passe retiré de ce dépôt).
You can send my ssh pubkey

### Matériel connecté
1. Micro MEMS I2S (type INMP441) :
   - VDD -> Pin 1 (3.3V)
   - GND -> Pin 9 (GND)
   - L/R -> Relié à GND (canal gauche)
   - SD  -> Pin 38 (GPIO 20 / PCM_DIN)
   - SCK -> Pin 12 (GPIO 18 / PCM_CLK)
   - WS  -> Pin 35 (GPIO 19 / PCM_FS)

2. Écran TFT 1.69" ST7789V3 (240x280) en SPI :
   - GND -> Pin 6 (GND)
   - VCC -> Pin 17 (3.3V)
   - SCL -> Pin 23 (GPIO 11 / SPI0_SCLK)
   - SDA -> Pin 19 (GPIO 10 / SPI0_MOSI)
   - RES -> Pin 22 (GPIO 25)
   - DC  -> Pin 18 (GPIO 24)
   - CS  -> Pin 24 (GPIO 8 / SPI0_CE0)
   - BLK -> Pin 15 (GPIO 22, rétroéclairage pilotable)

---

### Ce que tu dois faire pas à pas

1. Configuration du système (/boot/firmware/config.txt ou /boot/config.txt selon l'OS) :
   - Activer le bus SPI (`dtparam=spi=on`).
   - Activer l'I2S pour le microphone en configurant le bon overlay (ex. `googlevoicehat-soundcard`).
   - Forcer le GPIO 22 en sortie haute au démarrage (`gpio=22=op,dh`) pour alimenter le rétroéclairage de l'écran.
   - Prévoir une configuration ALSA propre (`/etc/asound.conf`) pour que le périphérique I2S soit reconnu comme entrée audio valide en mono/stéréo 16 ou 24 bits.

2. Vérification matérielle :
   - Fournir les commandes pour tester la détection de la carte son I2S (`arecord -l`).
   - Fournir une commande courte d'enregistrement de test (`arecord -D ... -d 5 test.wav`).

3. Installation et configuration de BirdNET-Go :
   - Télécharger et installer la version binaire de BirdNET-Go adaptée à l'architecture (ARM64).
   - Configurer BirdNET-Go pour capturer le flux audio depuis le périphérique ALSA configuré.
   - Paramétrer la géolocalisation pour la France (Provence / région PACA) afin d'optimiser le filtrage des oiseaux locaux.
   - Configurer une sortie d'événements (webhook HTTP local, MQTT ou écriture de logs/JSON) pour notifier les détections d'oiseaux.

4. Script de notification pour l'écran ST7789 :
   - Mettre en place un environnement virtuel Python avec les dépendances nécessaires (`st7789`, `pillow`, `gpiod`).
   - Créer un script léger en Python qui tourne en arrière-plan :
     - Écoute les détections émises par BirdNET-Go.
     - Affiche sur l'écran ST7789 (240x280) le nom de l'oiseau détecté, l'heure et le score de confiance.
     - Éteint l'écran ou passe en veille/écran d'attente après un temps d'inactivité.

5. Automatisation :
   - Créer les services `systemd` nécessaires pour lancer BirdNET-Go et le script d'affichage automatiquement au boot.