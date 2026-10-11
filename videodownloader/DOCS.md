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
