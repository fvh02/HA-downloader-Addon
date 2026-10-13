# Home Assistant Downloader Add-on

Ein Home-Assistant-Add-on mit moderner Weboberfläche: Links zu Dateien einfügen,
und das Add-on lädt sie der Reihe nach herunter.

![Downloader](https://img.shields.io/badge/Home%20Assistant-Add--on-41BDF5)

## Installation

### Mit einem Klick

[![Repository zu Home Assistant hinzufügen](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Ffvh02%2FHA-downloader-Addon)

Der Button öffnet deine Home-Assistant-Instanz und fügt dieses Repository zum Add-on Store hinzu.
Danach **Downloader** auswählen, installieren und starten.

### Manuell

1. In Home Assistant **Einstellungen → Add-ons → Add-on Store** öffnen.
2. Oben rechts im Menü (⋮) **Repositories** wählen und diese URL hinzufügen:
   `https://github.com/fvh02/HA-downloader-Addon`
3. Das Add-on **Downloader** installieren und starten.
4. Über **Seitenleiste anzeigen** erscheint der Downloader direkt in der Home-Assistant-Seitenleiste.

Details zur Konfiguration stehen in [`downloader/DOCS.md`](downloader/DOCS.md).

## Add-ons in diesem Repository

| Add-on | Beschreibung |
| ------ | ------------ |
| [Downloader](downloader/DOCS.md) | Dateien per Link in eine Warteschlange legen und nacheinander herunterladen. |
| [Video-Downloader](videodownloader/DOCS.md) | YouTube- und Online-Videos in wählbarer Qualität herunterladen, mit Mediathek. |
| [Browser](browser/DOCS.md) | Google Chrome in der Home-Assistant-Seitenleiste (nur amd64). |

Alle werden auf GitHub gebaut; Home Assistant lädt nur die fertigen Images.

## Über das Internet

Anleitung für Cloudflare Tunnel und Zugangscodes: [TUNNEL.md](TUNNEL.md)
