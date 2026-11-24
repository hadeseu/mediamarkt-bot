# Verfügbarkeits-Bot – Schritt für Schritt

Der Bot prüft deine Produkte in Online-Shops und pingt dich im Discord-Channel, sobald eins
bestellbar ist. Einfach den Produkt-Link mit `/add` reinwerfen. Updates holt er sich jede Minute
selbst von GitHub.

## Befehle in Discord

| Befehl | Was er macht |
|---|---|
| `/add <Link>` | Produkt überwachen (Link aus irgendeinem Shop) |
| `/check <Link>` | Sofort nachschauen, ob verfügbar |
| `/checkall` | Alle Produkte aus der Liste sofort prüfen |
| `/list` | Alle überwachten Produkte |
| `/remove <Nummer>` | Produkt entfernen (Nummer aus `/list`) |
| `/shops` | Welche Shops funktionieren |

## Welche Shops?
- **Funktioniert sicher:** MediaMarkt AT (unterscheidet MediaMarkt vs. teure Marktplatz-Händler), Alza, Boozt, Thalia
- **Sollte gehen:** Saturn/MediaMarkt DE, kleine Kartenshops auf Shopify und alle Shops, die
  Google-Produktdaten (schema.org) in die Seite schreiben. Einfach `/check` mit dem Link probieren.
- **Geht nicht (Bot-Schutz):** Pagro, Libro, Müller, Smyths, Conrad, Galaxus, Interspar, Kaufland, Amazon

Jeder Shop wird **für sich** gleichmäßig geprüft (max. 1 Anfrage alle 3 Sek. pro Shop),
ein Shop bremst die anderen also nicht aus.

---

## Schritt 1 – Bot bei Discord anlegen

1. Öffne https://discord.com/developers/applications → **New Application** → Name z. B. „MediaMarkt Bot“ → **Create**.
2. Links **Bot** → **Reset Token** → **Copy**. Den Token in Notepad zwischenspeichern.
   ⚠️ Niemandem zeigen – wer den Token hat, steuert deinen Bot.
3. Links **OAuth2** → runter zu **OAuth2 URL Generator**:
   - Bei *Scopes* anhaken: `bot` und `applications.commands`
   - Bei *Bot Permissions* anhaken: `View Channels`, `Send Messages`, `Embed Links`
   - Ganz unten den **Generated URL** kopieren, im Browser öffnen, deinen Server wählen → **Autorisieren**.
4. In Discord: **Einstellungen (Zahnrad) → Erweitert → Entwicklermodus** einschalten.
   - Rechtsklick auf den Channel, in dem der Bot pingen soll → **Kanal-ID kopieren** → in Notepad.
   - Rechtsklick auf deinen eigenen Namen → **Benutzer-ID kopieren** → in Notepad.

## Schritt 2 – GitHub (für automatische Updates)

1. Konto anlegen auf https://github.com (gratis).
2. In PowerShell GitHub CLI installieren:
   ```powershell
   winget install --id GitHub.cli
   ```
3. PowerShell **schließen und neu öffnen**, dann anmelden (öffnet den Browser):
   ```powershell
   gh auth login --web
   ```
4. Sag mir hier Bescheid → ich lade den Bot auf GitHub hoch und sage dir deinen `UPDATE_REPO`-Namen.

## Schritt 3 – Bot bei Wispbyte starten

1. Im Wispbyte-Panel einen **Python**-Server erstellen und öffnen.
2. **Files** → **Upload** → diese 4 Dateien aus dem Bot-Ordner hochladen:
   `bot.py`, `checker.py`, `updater.py`, `requirements.txt`
3. **Files** → **New File** → Name: `.env` → das hier einfügen und ausfüllen:
   ```
   DISCORD_TOKEN=dein-token-aus-schritt-1
   CHANNEL_ID=deine-kanal-id
   PING_USER_ID=deine-benutzer-id
   UPDATE_REPO=hadeseu/mediamarkt-bot
   CHECK_SECONDS=10
   MIN_GAP_SECONDS=3
   ALLOW_MARKETPLACE=false
   ```
   → **Save**.
   Mehrere Leute pingen: IDs mit Komma trennen, z. B. `PING_USER_ID=111111111111111111,222222222222222222`
4. **Startup** → bei der Startdatei (heißt z. B. *App py file* / *Startup File*) `bot.py` eintragen.
5. **Console** → **Start**. Nach ein paar Sekunden sollte dort stehen:
   `Eingeloggt als MediaMarkt Bot#…`
   Beim ersten Start holt er sich die neueste Version von GitHub, startet neu und schreibt
   „🔄 Update installiert“ in deinen Channel.
6. Im Channel testen: `/add` + einen MediaMarkt.at-Link. ✅

## Updates
Sag mir hier, was der Bot anders machen soll. Ich lade es auf GitHub hoch,
innerhalb von 1 Minute holt der Bot es sich selbst und schreibt „🔄 Update installiert“ in den Channel.

## Wenn was nicht geht
- **Bot ist offline:** Wispbyte → Console anschauen, die letzte rote Zeile mir hier schicken
  (aber **nie den Token**!).
- **Slash-Befehle erscheinen nicht:** Discord einmal neu laden (Strg+R).
- **Token aus Versehen geteilt:** Discord Developer Portal → Bot → **Reset Token** → neuen Token in `.env` eintragen → Restart.

## Wie er MediaMarkt schont
Die Produkte werden reihum in gleichen Abständen geprüft, höchstens 1 Anfrage alle 3 Sekunden.
Bis 3 Produkte: jedes alle 10 Sek. Mehr Produkte: pro Produkt etwas langsamer, die Last bleibt gleich.
Blockt MediaMarkt trotzdem, macht der Bot 1 Minute Pause und wird langsamer; läuft es wieder
stabil, wird er schrittweise wieder schneller.

---

## Alternative: Bot auf einem Android-Handy (Termux)

Nötig, wenn MediaMarkt den Hoster sperrt (`HTTP 403`). Vom Internet zu Hause wird nicht gesperrt.

1. **F-Droid** installieren: https://f-droid.org → über F-Droid **Termux** und **Termux:Boot** installieren
   (nicht aus dem Play Store).
2. **Termux:Boot** einmal öffnen (damit der Autostart aktiv wird).
3. Android-Einstellungen → Apps → **Termux** → Akku → **Nicht optimieren / Uneingeschränkt**.
4. **Termux** öffnen und einfügen:
   ```bash
   pkg install -y curl && curl -fsSL https://raw.githubusercontent.com/hadeseu/mediamarkt-bot/main/termux/install.sh | bash
   ```
5. Nach Token, Channel-ID und User-ID(s) gefragt → einfügen. Fertig. ✅
6. Den Bot bei Wispbyte **stoppen** (sonst läuft er doppelt).

Kurzbefehle in Termux: `bot-log` (Log ansehen), `bot-stop`, `bot-start`.
Handy am Ladekabel und im WLAN lassen.
