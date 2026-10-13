# Changelog

## 1.4.0

- **Videos von (fast) jeder Webseite:** Kennt yt-dlp eine Seite nicht, sucht der Downloader das
  Video selbst – zuerst im Quelltext (`<video>`, MP4/HLS/DASH-Links, og:video, eingebettete Player),
  dann in einem unsichtbaren Browser, der die Seite öffnet, den Player startet und die
  Video-Adresse abfängt. Die Datei bekommt den Titel der Seite.
- Auch die Video-Suche und der Browser laufen über das VPN, wenn es eingeschaltet ist (inklusive
  Namensauflösung; WebRTC/QUIC sind gesperrt). Ist das VPN aus, wird nichts geöffnet.
- Die Liste zeigt, was gerade passiert („suche das Video auf der Seite …“).

## 1.3.0

- **VPN mit Proton (kostenlos):** In Home Assistant lässt sich unten auf der Downloader-Seite die
  WireGuard-Datei eines (kostenlosen) Proton-VPN-Kontos hochladen. Danach laufen alle Abfragen,
  Downloads und Vorschaubilder nur noch über Proton – YouTube & Co. sehen nicht mehr deine IP.
  Der Rest von Home Assistant bleibt unberührt.
- **Notbremse:** Ist das VPN eingeschaltet, aber nicht verbunden, warten die Downloads, statt über
  deinen eigenen Anschluss zu laufen. Die Seite zeigt Land und IP, über die geladen wird.

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
