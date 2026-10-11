# Downloader

Fügt Links zu Dateien in eine Warteschlange ein und lädt sie nacheinander herunter.

## Bedienung

- Link in das Suchfeld einfügen und **Hinzufügen** klicken (oder Enter drücken).
  Mehrere Links auf einmal (durch Leerzeichen oder Zeilenumbruch getrennt) sind möglich.
- Unter dem Suchfeld erscheint die Warteliste mit Dateiname, Größe und Fortschritt.
- Der **Mülleimer** entfernt einen Eintrag aus der Liste. Ein laufender Download wird dabei
  abgebrochen und die unvollständige Datei gelöscht. Bereits fertige Dateien bleiben erhalten.
- **Erledigte entfernen** räumt fertige und fehlgeschlagene Einträge aus der Liste.

Die Warteliste bleibt über Neustarts des Add-ons erhalten; ein unterbrochener Download
beginnt nach dem Neustart von vorn.

## Konfiguration

```yaml
design: modern
theme: dark
download_dir: /media/downloads
inkbox_api_key: ""
imessage_to: ""
```

| Option         | Beschreibung                                                                          |
| -------------- | ------------------------------------------------------------------------------------- |
| `design`       | `modern`: zentrierte Suchleiste mit Dropdown-Liste. `terminal`: klassischer Terminal-Look, Eingabezeile unten links, Liste darüber. |
| `theme`        | `dark` oder `light`.                                                                   |
| `download_dir` | Zielordner. `/media/...` (im Medien-Browser sichtbar) oder `/share/...`.               |
| `inkbox_api_key` | Optional. API-Key deiner Inkbox-Identität für iMessage-Benachrichtigungen.           |
| `imessage_to`  | Optional. Deine Handynummer (`+491701234567`), an die Benachrichtigungen gehen.        |

Nach einer Änderung das Add-on neu starten und die Seite neu laden.

## Zugriff

Die Oberfläche ist über die Home-Assistant-Seitenleiste erreichbar. Andere Add-ons erreichen
den Downloader im internen Netz von Home Assistant unter `http://<hostname>:8099` (den
Hostnamen zeigt der Reiter **Info**). Von außen ist er nicht erreichbar.

## iMessage über deinen Assistenten

### Benachrichtigungen

Trage `inkbox_api_key` und `imessage_to` ein. Das Add-on schickt dann über deine
Inkbox-Identität eine iMessage, sobald ein Download fertig ist oder fehlschlägt:

> ✅ Download fertig: Ubuntu 24.04 Desktop.iso (500,0 MB)

Den API-Key erstellst du in der [Inkbox-Konsole](https://inkbox.ai) für die Identität, mit
der du per iMessage schreibst (am besten ein auf diese Identität beschränkter Key).

### Status abfragen und Links hinzufügen

Das übernimmt das [Inkbox Claude Gateway](https://github.com/fvh02/fabiaiagent) mit seinem
`downloader`-Befehl. Es spricht den Downloader über das interne Netz an; einzurichten ist dort
nur die **Downloader-Adresse**.

Die Endpunkte:

| Methode  | Pfad                | Zweck                                                         |
| -------- | ------------------- | ------------------------------------------------------------- |
| `GET`    | `/api/status`       | Status inkl. fertigem Text im Feld `summary` für die Antwort. |
| `POST`   | `/api/items`        | Links hinzufügen: `{"url": "https://… https://…"}`             |
| `DELETE` | `/api/items/<id>`   | Eintrag entfernen bzw. laufenden Download abbrechen.          |

Beispiel für `summary`:

```
⬇️ Ubuntu 24.04 Desktop.iso: 42 % von 500,0 MB, 1,2 MB/s
⏳ 2 in der Warteschlange: backup.tar.gz, video.mp4
✅ 3 fertig
```
