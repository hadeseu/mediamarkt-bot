#!/data/data/com.termux/files/usr/bin/bash
APP="$HOME/mediamarkt-bot"
PIDFILE="$APP/data/bot.pid"
if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE")"
  pkill -P "$PID" 2>/dev/null || true   # python bot.py
  kill "$PID" 2>/dev/null || true       # die Neustart-Schleife
  rm -f "$PIDFILE"
fi
command -v termux-wake-unlock >/dev/null && termux-wake-unlock
echo "Bot gestoppt."
