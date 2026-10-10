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
download_dir: /media/downloads
```

| Option         | Beschreibung                                                                 |
| -------------- | ---------------------------------------------------------------------------- |
| `download_dir` | Zielordner. `/media/...` (im Medien-Browser sichtbar) oder `/share/...`.     |

## Zugriff ohne Home Assistant

Standardmäßig ist die Oberfläche nur über die Home-Assistant-Seitenleiste (Ingress) erreichbar.
Unter **Netzwerk** kann optional Port `8099` freigegeben werden. Achtung: Dieser Port hat
keine Anmeldung – jeder im Netzwerk könnte dann Downloads hinzufügen.
