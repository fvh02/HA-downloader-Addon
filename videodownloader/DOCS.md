# Video-Downloader

Lädt Videos von YouTube und vielen anderen Seiten herunter (alles, was
[yt-dlp](https://github.com/yt-dlp/yt-dlp) unterstützt, plus direkte Videolinks) – in der
höchsten verfügbaren Qualität oder in der Qualität deiner Wahl. Dazu gibt es eine Mediathek,
in der du die Videos ansehen, herunterladen, umbenennen und löschen kannst.

## Downloader

- Link einfügen, Qualität wählen, **Hinzufügen**. Mehrere Links auf einmal (durch Leerzeichen
  oder Zeilenumbruch getrennt) und ganze Playlists gehen auch.
- Qualitäten: **Beste Qualität**, 4K, 1440p, 1080p, 720p, 480p, 360p oder **Nur Audio (MP3)**.
  Solange ein Video noch wartet, lässt sich die Qualität in der Liste ändern; angeboten werden
  nur Auflösungen, die das Video wirklich hat.
- Die Videos werden nacheinander geladen. Die Liste zeigt Vorschaubild, Titel, Größe,
  Fortschritt, Geschwindigkeit und Restzeit. Der Mülleimer entfernt einen Eintrag und bricht
  einen laufenden Download ab (Teildateien werden gelöscht).
- Videos werden als MP4 gespeichert (Bild und Ton zusammengeführt), Audio als MP3.

## Mediathek

Eigene Seite (oben **Mediathek**): alle Videos und Audiodateien im Download-Ordner mit
Vorschaubild und Dauer. Suche, Filter (Videos/Audio) und Sortierung; ein Klick öffnet den
Player mit **Herunterladen**, **Umbenennen** und **Löschen**. Oben siehst du, wie viel
Speicherplatz noch frei ist.

## Zugriff

- Über die Home-Assistant-Seitenleiste (**Videos**).
- Im Heimnetz unter `http://<home-assistant-ip>:8097` (ohne Anmeldung; im Reiter **Netzwerk**
  änderbar oder abschaltbar).
- Aus dem Internet (z. B. per Cloudflare Tunnel unter deiner Domain) mit dem **Zugangscode**
  (Option `access_code`), einmal pro Gerät. Ohne gesetzten Code ist der Zugriff aus dem
  Internet gesperrt. Anleitung: [Über das Internet erreichbar machen](https://github.com/fvh02/HA-downloader-Addon/blob/HEAD/TUNNEL.md)

## Videos von beliebigen Webseiten

Der Downloader kennt über 1.800 Seiten direkt (YouTube, Vimeo, Dailymotion, Twitch, Instagram,
TikTok, X, Mediatheken von ARD/ZDF und viele mehr). Bei allen anderen Seiten einfach den Link der
Seite einfügen, auf der das Video läuft:

1. **Seiten-Scan:** Der Downloader lädt die Seite und sucht darin nach Videos (`<video>`,
   MP4-/HLS-/DASH-Links, eingebettete Player).
2. **Browser-Scan:** Findet er so nichts, öffnet ein unsichtbarer Browser die Seite, startet den
   Player und fängt die Video-Adresse ab – das klappt auch bei Playern, die das Video erst per
   JavaScript laden. Das dauert bis zu einer halben Minute.

Die Datei bekommt den Titel der Seite. Mit eingeschaltetem VPN laufen auch Seiten-Scan und Browser
nur über Proton.

Was nicht geht: **kopiergeschützte** Streams (Netflix, Disney+, Prime Video, Sky …) und Videos
hinter einem Login, das der Downloader nicht kennt.

## YouTube-Konto (Premium)

Mit deinem YouTube-Konto lädt der Downloader auch Inhalte, die eine Anmeldung brauchen:
**Premium-Qualität** (z. B. „1080p Premium“ mit höherer Bitrate), Premium-Inhalte,
Kanalmitgliedschaften und altersbeschränkte Videos.

YouTube erlaubt Programmen keine Anmeldung mit E-Mail und Passwort mehr. Deshalb nutzt der
Downloader die **Anmelde-Cookies** deines Browsers:

1. Am PC ein **privates Fenster** öffnen (Chrome: Inkognito, Firefox: Privates Fenster) und auf
   youtube.com mit deinem Premium-Konto anmelden.
2. Mit der Erweiterung **„Get cookies.txt LOCALLY“** (Chrome/Edge) bzw. **„cookies.txt“**
   (Firefox) die Cookies von youtube.com als `cookies.txt` speichern. Die Erweiterung muss im
   privaten Fenster erlaubt sein.
3. Das private Fenster **schließen, ohne dich abzumelden** (Abmelden macht die Cookies ungültig).
4. In Home Assistant den Video-Downloader öffnen und unten bei **YouTube-Konto** die Datei hochladen.
   Danach steht dort „✓ verbunden“.

Hochladen, Prüfen und Trennen geht nur über Home Assistant, nicht im Heimnetz oder über das
Internet. Gespeichert werden nur die Cookies von youtube.com und google.com, im privaten Speicher
des Add-ons; angezeigt wird nur der Status. Meldet „Prüfen“ irgendwann, dass YouTube die Anmeldung
nicht mehr annimmt, einfach neu exportieren und hochladen.

Hinweis: Lade nur Videos herunter, die du privat nutzen darfst. YouTube untersagt das Herunterladen
außerhalb der App in seinen Nutzungsbedingungen – die Nutzung geschieht auf eigene Verantwortung.

## VPN (Proton, kostenlos)

Auf Wunsch laufen alle Downloads über **Proton VPN**. YouTube und andere Seiten sehen dann eine
Proton-Adresse (z. B. Niederlande) statt deiner IP, und dein Internetanbieter sieht nicht, was du
lädst. Nur der Video-Downloader nutzt das VPN – Home Assistant und die anderen Add-ons nicht.

1. Auf [proton.me/vpn](https://proton.me/vpn) ein **kostenloses** Konto anlegen (Plan „Free“).
2. Auf [account.protonvpn.com](https://account.protonvpn.com) → **Downloads** → **WireGuard
   configuration**: Namen eingeben (z. B. „Home Assistant“), Plattform **GNU/Linux**,
   **NetShield aus**, bei einem **Free-Server** auf **Create** und die `.conf`-Datei herunterladen.
3. In Home Assistant den Video-Downloader öffnen und unten bei **🛡 VPN (Proton)** die Datei
   hochladen. Danach steht dort z. B. „🔒 aktiv · Amsterdam, Niederlande · IP 185.…“.

- **Notbremse:** Fällt das VPN aus, warten die Downloads und starten automatisch, sobald es wieder
  verbunden ist. Sie laufen nie heimlich über deine eigene IP. Auch Vorschaubilder kommen dann
  über das VPN.
- **Ausschalten** löscht die Datei; danach laufen Downloads wieder direkt.
- Im kostenlosen Proton-Plan ist **ein Gerät gleichzeitig** erlaubt – die Datei nicht zusätzlich
  auf dem Handy nutzen. Ist ein Free-Server überlastet, einfach eine Datei für einen anderen
  Server erstellen und hochladen.
- Die Datei enthält einen privaten Schlüssel: Sie bleibt im privaten Speicher des Add-ons, wird nie
  angezeigt, und Hochladen/Ausschalten geht nur über Home Assistant.
- YouTube fragt bei VPN-Adressen manchmal nach einer Bestätigung („kein Bot“). Mit verbundenem
  YouTube-Konto passiert das seltener; sonst hilft ein anderer Proton-Server.
- Das VPN ändert nichts daran, was du herunterladen darfst.

## Konfiguration

| Option          | Beschreibung                                                                 |
| --------------- | ---------------------------------------------------------------------------- |
| `design`        | `glass` (Milchglas wie in den Spielen), `modern` oder `terminal`.            |
| `theme`         | `dark` oder `light`.                                                          |
| `quality`       | Vorauswahl: `best`, `2160`, `1440`, `1080`, `720`, `480`, `360` oder `audio`. |
| `download_dir`  | Zielordner, Standard `/media/videos`.                                         |
| `update_ytdlp`  | yt-dlp bei jedem Start aktualisieren (empfohlen).                             |
| `access_code`   | Zugangscode für Aufrufe aus dem Internet. Leer = Internet gesperrt.           |

Hinweis: Lade nur Videos herunter, bei denen du das darfst (eigene Inhalte, freie Lizenzen,
private Kopie, soweit erlaubt). Manche Seiten verbieten das Herunterladen in ihren Bedingungen.
