#!/data/data/com.termux/files/usr/bin/bash
# Richtet den MediaMarkt-Bot auf einem Android-Handy in Termux ein.
# Aufruf in Termux:
#   pkg install -y curl && curl -fsSL https://raw.githubusercontent.com/hadeseu/mediamarkt-bot/main/termux/install.sh | bash
set -e

APP="$HOME/mediamarkt-bot"
REPO="https://github.com/hadeseu/mediamarkt-bot"
OPTS=(-y -o Dpkg::Options::=--force-confnew)

echo "==> Pakete installieren (kann ein paar Minuten dauern)"
pkg update "${OPTS[@]}" || true
pkg install "${OPTS[@]}" python git clang

echo "==> Bot herunterladen"
if [ ! -d "$APP" ]; then
  git clone -q "$REPO" "$APP"
fi
cd "$APP"
mkdir -p data

echo "==> Python-Pakete installieren"
export AIOHTTP_NO_EXTENSIONS=1 MULTIDICT_NO_EXTENSIONS=1 YARL_NO_EXTENSIONS=1 \
       FROZENLIST_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  echo
  echo "==> Bot-Einstellungen (werden NUR auf diesem Handy gespeichert)"
  read -rsp "Discord Bot-Token (Eingabe wird nicht angezeigt): " TOKEN < /dev/tty; echo
  read -rp  "Channel-ID: " CHANNEL < /dev/tty
  read -rp  "User-ID(s) zum Pingen (mehrere mit Komma): " USERID < /dev/tty
  umask 077
  cat > .env <<EOF
DISCORD_TOKEN=$TOKEN
CHANNEL_ID=$CHANNEL
PING_USER_ID=$USERID
UPDATE_REPO=hadeseu/mediamarkt-bot
CHECK_SECONDS=10
MIN_GAP_SECONDS=3
ALLOW_MARKETPLACE=false
EOF
fi

echo "==> Kurzbefehle einrichten: bot-start, bot-stop, bot-log"
sed -i '/# mediamarkt-bot/d' "$HOME/.bashrc" 2>/dev/null || true
cat >> "$HOME/.bashrc" <<'EOF'
alias bot-start='bash ~/mediamarkt-bot/termux/start.sh'   # mediamarkt-bot
alias bot-stop='bash ~/mediamarkt-bot/termux/stop.sh'     # mediamarkt-bot
alias bot-log='tail -n 50 -f ~/mediamarkt-bot/data/bot.log'  # mediamarkt-bot
EOF

echo "==> Autostart nach Handy-Neustart (braucht die App Termux:Boot)"
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/mediamarkt-bot" <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
bash ~/mediamarkt-bot/termux/start.sh
EOF
chmod +x "$HOME/.termux/boot/mediamarkt-bot"

bash "$APP/termux/start.sh"

echo
echo "✅ Fertig! Der Bot läuft jetzt im Hintergrund."
echo "   Log ansehen:  bot-log   (beenden mit Strg+C – der Bot läuft weiter)"
echo "   Stoppen:      bot-stop"
echo "   Starten:      bot-start"
echo "   (Die Kurzbefehle gehen ab dem nächsten Öffnen von Termux.)"
