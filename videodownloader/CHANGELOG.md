# Changelog

## 1.2.0

- **YouTube-Konto (z. B. Premium):** Auf der Downloader-Seite lässt sich in Home Assistant eine
  cookies.txt deines YouTube-Kontos hochladen. Damit lädt der Downloader Inhalte, die eine
  Anmeldung brauchen (Premium-Qualität, Premium-, Mitglieder- und altersbeschränkte Videos).
  Gespeichert werden nur die Cookies von youtube.com/google.com, nur lesbar für das Add-on;
  die Seite zeigt nur den Status. „Prüfen“ testet die Anmeldung, „Trennen“ löscht sie.

## 1.1.0

- **Zugangscode** (Option `access_code`) für Aufrufe aus dem Internet, z. B. über einen
  Cloudflare Tunnel. Ohne Code ist der Zugriff aus dem Internet gesperrt. Heimnetz und Home
  Assistant brauchen weiterhin keinen Code.

## 1.0.0

- Erste Version: Video-Downloader mit yt-dlp (YouTube und viele weitere Seiten),
  Qualitätsauswahl, Warteschlange mit Fortschritt, Mediathek mit Player.
- Drei Designs (glass, modern, terminal) jeweils hell und dunkel.
