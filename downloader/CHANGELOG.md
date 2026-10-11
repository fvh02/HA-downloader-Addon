# Changelog

## 1.3.1

- Das Add-on wird jetzt auf GitHub gebaut; Home Assistant lädt nur noch das fertige Image
  herunter, statt es selbst zu bauen. Installation und Updates gehen dadurch deutlich schneller.

## 1.3.0

- API-Token und Port 8100 entfernt. Die Seitenleiste zeigt keine Token-Fehler mehr; das
  Inkbox Claude Gateway erreicht den Downloader über das interne Netz auf Port 8099.

## 1.2.2

- API-Token und Inkbox-Key ignorieren Leerzeichen und Zeilenumbrüche am Anfang/Ende
  (passiert leicht beim Kopieren).

## 1.2.1

- Fix: In der Seitenleiste erschien „Ungültiger oder fehlender API-Token“, sobald ein Token
  gesetzt war. Seitenleiste (Port 8099, intern) und direkter Zugriff (neu: Port 8100) sind jetzt
  getrennt; nur Port 8100 verlangt den Token.

## 1.2.0

- iMessage-Benachrichtigungen über Inkbox, wenn ein Download fertig ist oder fehlschlägt
  (Optionen `inkbox_api_key`, `imessage_to`).
- Neuer Endpunkt `/api/status` mit kurzer Statuszusammenfassung für Assistenten.
- Option `api_token` schützt den direkten Zugriff über Port 8099.

## 1.1.0

- Neues Design „Terminal“: Eingabezeile unten links, Warteliste darüber,
  farbige Dateigrößen, Hover-Farbe für Dateinamen, Pixel-Art-Mülleimer.
- Optionen `design` (modern/terminal) und `theme` (dark/light).

## 1.0.0

- Erste Version: Warteschlange mit Weboberfläche, sequenzielle Downloads,
  Fortschrittsanzeige, Entfernen per Mülleimer.
