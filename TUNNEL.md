# Über das Internet erreichbar machen (Cloudflare Tunnel)

Mit **einem** Cloudflare Tunnel machst du Downloader, Video-Downloader und Spieleabend unter
deiner eigenen Domain erreichbar – ohne Portfreigabe im Router, ohne Tailscale, mit HTTPS.
Home Assistant selbst bleibt privat.

| Add-on | Adresse (Beispiel) | Ziel im Tunnel |
| --- | --- | --- |
| Downloader | `https://downloads.deine-domain.de` | `192.168.178.103:8099` |
| Video-Downloader | `https://videos.deine-domain.de` | `192.168.178.103:8097` |
| Spieleabend | `https://spiele.deine-domain.de` | `192.168.178.103:8098` |

`192.168.178.103` ist die IP deines Home Assistant – bei dir ggf. anders
(Einstellungen → System → Netzwerk).

## 1. Zugangscodes setzen (zuerst!)

In jedem Add-on unter **Konfiguration → Zugangscode** einen Code eintragen, speichern, neu
starten. Ohne Code sperren die Add-ons Aufrufe aus dem Internet automatisch.

- **Downloader / Video-Downloader:** Der Code wird nur über das Internet abgefragt. Im
  Heimnetz, in Home Assistant und für das Claude Gateway ändert sich nichts.
- **Spieleabend:** Der Code gilt für alle, die nicht über Home Assistant spielen (auch im WLAN).

Nimm für die Downloader einen langen Code, den nur du kennst – wer ihn hat, kann über deinen
Anschluss herunterladen und deine Dateien sehen. Den Spiele-Code darfst du an Freunde geben.

## 2. Domain bei Cloudflare (einmalig)

1. Auf [dash.cloudflare.com](https://dash.cloudflare.com) anmelden → **Domain hinzufügen** →
   Free-Tarif.
2. Die zwei angezeigten Cloudflare-Nameserver bei deinem Domain-Anbieter eintragen.
3. Warten, bis Cloudflare die Domain als **Aktiv** zeigt.

## 3. Tunnel anlegen (einmalig)

1. In Cloudflare **Zero Trust** öffnen (beim ersten Mal Teamnamen wählen, Free-Tarif).
2. **Networks → Tunnels → Create a tunnel → Cloudflared**, Name z. B. `homeassistant`.
3. Den **Token** kopieren (die lange Zeichenkette nach `--token`, beginnt meist mit `eyJ`).
4. In Home Assistant das Repository `https://github.com/brenner-tobias/ha-addons` hinzufügen,
   **Cloudflared** installieren, unter Konfiguration **Optionale Konfigurationsoptionen
   anzeigen** einschalten, den Token bei **Cloudflare Tunnel Token** einfügen (sonst nichts),
   speichern, starten.
5. Bei Cloudflare erscheint der Connector als **Connected**.

## 4. Eine Adresse pro Add-on

Im Tunnel unter **Public Hostname → Add a public hostname** für jedes Add-on einen Eintrag:

| Subdomain | Domain | Service-Typ | URL |
| --- | --- | --- | --- |
| `downloads` | deine Domain | HTTP | `192.168.178.103:8099` |
| `videos` | deine Domain | HTTP | `192.168.178.103:8097` |
| `spiele` | deine Domain | HTTP | `192.168.178.103:8098` |

Path leer lassen. Speichern – die Adresse funktioniert nach wenigen Sekunden.

## 5. Testen

Am Handy **WLAN aus** und die Adressen öffnen: Es muss die Abfrage des Zugangscodes erscheinen.
Nach der Eingabe merkt sich das Gerät den Code ein Jahr lang.

## Abschalten

Einen Eintrag unter **Public Hostname** löschen – dann ist das Add-on sofort nicht mehr aus dem
Internet erreichbar. Oder das Cloudflared-Add-on stoppen, dann ist alles wieder nur im Heimnetz.
