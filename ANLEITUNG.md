# MediaMarkt.at Verfügbarkeits-Bot – Anleitung

Der Bot prüft alle 10 Sekunden deine Produkte auf **mediamarkt.at** und pingt dich im Discord-Channel,
sobald eins **bei MediaMarkt selbst** bestellbar ist (teure Marktplatz-Händler werden ignoriert).

**Gleichmäßiges Prüfen:** Die Produkte werden reihum in gleichen Abständen geprüft, nie öfter als
1 Anfrage alle 3 Sekunden. Bei bis zu 3 Produkten heißt das: jedes alle 10 Sek. Bei mehr Produkten
wird es pro Produkt etwas langsamer (z. B. 6 Produkte → jedes alle 18 Sek.), die Last bleibt gleich.

**Selbstregelnd:** Blockt MediaMarkt trotzdem, macht der Bot 1 Minute Pause und prüft danach
doppelt so langsam. Läuft es wieder 100 Anfragen lang stabil, wird er schrittweise wieder schneller.

## Befehle in Discord

| Befehl | Was er macht |
|---|---|
| `/add <Link>` | Produkt überwachen |
| `/check <Link>` | Sofort nachschauen, ob verfügbar |
| `/list` | Alle überwachten Produkte |
| `/remove <Nummer>` | Produkt entfernen (Nummer aus `/list`) |

---

## Einrichtung (nur einmal, ca. 30 Min.)

### 1. Discord-Bot anlegen
1. Öffne https://discord.com/developers/applications → **New Application** → Name z. B. „MediaMarkt Bot“.
2. Links **Bot** → **Reset Token** → Token kopieren und kurz sicher aufheben (z. B. Notepad, **nicht** teilen!).
3. Links **OAuth2 → URL Generator**:
   - Scopes: `bot` und `applications.commands`
   - Bot Permissions: `View Channels`, `Send Messages`, `Embed Links`
   - Unten den Link öffnen und den Bot auf deinen Server einladen.
4. In Discord: **Einstellungen → Erweitert → Entwicklermodus** einschalten.
   - Rechtsklick auf den Channel → **Kanal-ID kopieren**
   - Rechtsklick auf deinen Namen → **Benutzer-ID kopieren**

### 2. GitHub
1. Konto anlegen auf https://github.com (gratis).
2. Den Rest (Repo anlegen, Code hochladen) mache ich für dich.

> Das Repo ist **öffentlich**, damit der Server es ohne Passwort holen kann.
> Das ist sicher: Token und IDs stehen **nie** im Code, sondern nur auf dem Server.

### 3. Oracle Cloud Server (gratis)
1. Konto anlegen: https://www.oracle.com/cloud/free/ – Region **Germany Central (Frankfurt)**.
   Die Kreditkarte dient nur zur Prüfung, „Always Free“ kostet nichts.
2. **Compute → Instances → Create instance**
   - Image: **Ubuntu 24.04**
   - Shape: **Ampere → VM.Standard.A1.Flex**, 1 OCPU, 6 GB RAM (gratis)
   - SSH keys: **Save private key** → Datei gut aufheben
   - **Create**. Steht „Out of capacity“ da: später nochmal versuchen.
3. Die **Public IP address** der Instanz notieren.

### 4. Bot auf dem Server starten
In PowerShell (Pfad zur Schlüsseldatei und IP anpassen):

```powershell
ssh -i C:\Pfad\zum\ssh-key.key ubuntu@DEINE-IP
```

Auf dem Server diesen einen Befehl einfügen (ich schicke dir die fertige Zeile mit deinem GitHub-Namen):

```bash
curl -fsSL https://raw.githubusercontent.com/<NAME>/mediamarkt-bot/main/deploy/setup.sh | bash -s -- https://github.com/<NAME>/mediamarkt-bot.git
```

Das Skript fragt nach Token, Channel-ID und User-ID – einfügen, fertig. ✅

---

## Updates
Sag mir einfach, was der Bot anders machen soll. Ich lade die Änderung auf GitHub hoch,
der Server holt sie sich innerhalb von 1 Minute und startet den Bot neu.

## Hilfe auf dem Server
```bash
sudo systemctl status mmbot      # läuft er?
sudo journalctl -u mmbot -f      # Live-Log (Strg+C zum Beenden)
sudo nano /opt/mediamarkt-bot/.env && sudo systemctl restart mmbot   # Einstellungen ändern
```
