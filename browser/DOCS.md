# Browser

Ein echter **Google Chrome**, der im Home Assistant läuft. Du bedienst ihn in der Seitenleiste –
am PC mit Maus und Tastatur, am Handy per Touch.

## Wofür?

- Webseiten im Heimnetz öffnen (Router, Drucker, Kameras), auch wenn du unterwegs nur Home Assistant erreichst.
- Logins bleiben gespeichert: Chrome läuft dauerhaft weiter, auch wenn du die Seite schließt.
- Downloads landen direkt in `/media/downloads/browser` (über **Medien** in Home Assistant sichtbar).

## Einrichten

1. Add-on **Browser** installieren und starten.
2. **Seitenleiste anzeigen** einschalten.
3. Seitenleiste → **Browser**. Nach ein paar Sekunden erscheint Chrome.

## Optionen

| Option | Bedeutung |
| ------ | --------- |
| `start_url` | Seite, die beim Start geöffnet wird. |
| `resolution` | Startgröße des Bildschirms. Das Bild passt sich danach automatisch an dein Fenster an. |
| `download_dir` | Ordner für Downloads (unter `/media`). |

## Bedienung

- Links am Rand öffnet sich das noVNC-Menü: Tastatur fürs Handy, Zwischenablage, Vollbild.
- **Text kopieren:** Über das Menü → Zwischenablage kannst du Text zwischen deinem Gerät und Chrome austauschen.
- Wird Chrome geschlossen oder stürzt ab, startet er nach einer Sekunde neu.

## Gut zu wissen

- Nur über Home Assistant erreichbar – direkt im Heimnetz oder aus dem Internet ist der Browser gesperrt.
  Trotzdem gilt: Wer Zugriff auf dein Home Assistant hat, kann diesen Browser samt eingeloggten Konten nutzen.
- Kein Ton (nur Bild).
- Läuft nur auf Intel/AMD (amd64), weil es Google Chrome nur dafür gibt.
- Chrome braucht etwa 400–800 MB RAM. Bei 4 GB im Server lieber nicht dauerhaft viele Tabs offen lassen.
