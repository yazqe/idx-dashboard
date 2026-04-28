#!/bin/bash
# IDX Dashboard — Service Manager
# Usage: ./manage.sh [start|stop|restart|status|logs|install|uninstall]

PLIST_NAME="com.idx.dashboard"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$(dirname "$0")/logs"
URL="http://localhost:5050"

green() { echo -e "\033[0;32m$1\033[0m"; }
red()   { echo -e "\033[0;31m$1\033[0m"; }
yellow(){ echo -e "\033[0;33m$1\033[0m"; }

case "$1" in

  install)
    yellow "Installing IDX Dashboard as launchd service…"
    # Install dependencies dulu
    "$(dirname "$0")/.venv/bin/pip" install -q flask apscheduler requests pytz 2>/dev/null || \
      (python3 -m venv "$(dirname "$0")/.venv" && "$(dirname "$0")/.venv/bin/pip" install -q flask apscheduler requests pytz)
    launchctl load "$PLIST_PATH" 2>/dev/null
    sleep 2
    if curl -sf "$URL/api/data" >/dev/null 2>&1 || curl -sf "$URL" >/dev/null 2>&1; then
      green "✅ Service installed & running → $URL"
    else
      yellow "⏳ Service installed, sedang startup…"
    fi
    ;;

  uninstall)
    yellow "Removing IDX Dashboard service…"
    launchctl unload "$PLIST_PATH" 2>/dev/null
    green "✅ Service removed. File plist tetap ada, tinggal ./manage.sh install untuk pasang lagi."
    ;;

  start)
    launchctl load "$PLIST_PATH" 2>/dev/null
    sleep 2
    green "▶ Started → $URL"
    ;;

  stop)
    launchctl unload "$PLIST_PATH" 2>/dev/null
    red "⏹ Stopped."
    ;;

  restart)
    launchctl unload "$PLIST_PATH" 2>/dev/null
    sleep 1
    launchctl load "$PLIST_PATH" 2>/dev/null
    sleep 2
    green "🔄 Restarted → $URL"
    ;;

  status)
    if launchctl list | grep -q "$PLIST_NAME"; then
      PID=$(launchctl list | grep "$PLIST_NAME" | awk '{print $1}')
      green "✅ Running (PID: $PID) → $URL"
      echo ""
      echo "Jadwal otomatis:"
      echo "  🌅 09:17 WIB  — Sesi Pagi"
      echo "  ☀️  12:03 WIB  — Sesi Siang"
      echo "  🌆 15:37 WIB  — Menjelang Tutup"
    else
      red "⏹ Not running. Jalankan: ./manage.sh start"
    fi
    ;;

  logs)
    echo "=== STDOUT (tail -50) ==="
    tail -50 "$LOG_DIR/dashboard.log" 2>/dev/null || echo "(kosong)"
    echo ""
    echo "=== STDERR ==="
    tail -20 "$LOG_DIR/dashboard.error.log" 2>/dev/null || echo "(kosong)"
    ;;

  open)
    open "$URL"
    ;;

  *)
    echo "IDX Dashboard Manager"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "  install    Install & start sebagai launchd service (auto-start saat login)"
    echo "  uninstall  Hapus dari launchd"
    echo "  start      Start service"
    echo "  stop       Stop service"
    echo "  restart    Restart service"
    echo "  status     Cek status"
    echo "  logs       Lihat log output"
    echo "  open       Buka dashboard di browser"
    ;;
esac
