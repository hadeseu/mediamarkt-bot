#!/data/data/com.termux/files/usr/bin/bash
# Startet den Bot im Hintergrund (läuft weiter, auch wenn Termux geschlossen wird).
APP="$HOME/mediamarkt-bot"
PIDFILE="$APP/data/bot.pid"
mkdir -p "$APP/data"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Der Bot läuft schon."
  exit 0
fi

# Verhindert, dass Android Termux im Hintergrund schlafen legt
command -v termux-wake-lock >/dev/null && termux-wake-lock

cd "$APP"
nohup bash -c '
  while true; do
    # Vor jedem Start neueste Version holen – so repariert sich der Bot auch,
    # falls eine Version beim Starten abstürzt.
    git fetch -q origin && git reset -q --hard origin/main
    python bot.py
    echo "$(date) Bot beendet – Neustart in 10 Sekunden"
    sleep 10
  done
' >> "$APP/data/bot.log" 2>&1 &
echo $! > "$PIDFILE"
echo "Bot gestartet."
