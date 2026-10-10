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
api_token: ""
inkbox_api_key: ""
imessage_to: ""
```

| Option         | Beschreibung                                                                          |
| -------------- | ------------------------------------------------------------------------------------- |
| `design`       | `modern`: zentrierte Suchleiste mit Dropdown-Liste. `terminal`: klassischer Terminal-Look, Eingabezeile unten links, Liste darüber. |
| `theme`        | `dark` oder `light`.                                                                   |
| `download_dir` | Zielordner. `/media/...` (im Medien-Browser sichtbar) oder `/share/...`.               |
| `api_token`    | Optional. Schaltet den direkten Zugriff über Port 8100 frei (siehe unten).                   |
| `inkbox_api_key` | Optional. API-Key deiner Inkbox-Identität für iMessage-Benachrichtigungen.           |
| `imessage_to`  | Optional. Deine Handynummer (`+491701234567`), an die Benachrichtigungen gehen.        |

Nach einer Änderung das Add-on neu starten und die Seite neu laden.

## Zugriff ohne Home Assistant

Standardmäßig ist die Oberfläche nur über die Home-Assistant-Seitenleiste (Ingress) erreichbar.
Unter **Netzwerk** kann optional Port `8100` freigegeben werden. Dieser Port funktioniert nur
mit gesetztem `api_token`; ohne Token lehnt er alle Anfragen ab.

Mit Token öffnest du die Seite direkt über `http://<home-assistant>:8100/?token=<api_token>`.
Über die Seitenleiste ist nie ein Token nötig.

## iMessage über deinen Assistenten

### Benachrichtigungen

Trage `inkbox_api_key` und `imessage_to` ein. Das Add-on schickt dann über deine
Inkbox-Identität eine iMessage, sobald ein Download fertig ist oder fehlschlägt:

> ✅ Download fertig: Ubuntu 24.04 Desktop.iso (500,0 MB)

Den API-Key erstellst du in der [Inkbox-Konsole](https://inkbox.ai) für die Identität, mit
der du per iMessage schreibst (am besten ein auf diese Identität beschränkter Key).

### Status abfragen und Links hinzufügen

Dein Assistent braucht dafür Zugriff auf die API des Add-ons:

1. Port `8100` unter **Netzwerk** freigeben und einen `api_token` setzen.
2. Den Port aus dem Internet erreichbar machen, z. B. per Portweiterleitung im Router
   (am besten mit HTTPS über einen Reverse-Proxy) oder mit dem Cloudflared-Add-on.
3. Dem Assistenten die Adresse und den Token als `DOWNLOADER_URL` und `DOWNLOADER_TOKEN`
   geben (als Secrets, nicht im Klartext in ein Repository).

Die Endpunkte (alle mit `Authorization: Bearer <api_token>`):

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
