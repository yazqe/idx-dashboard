import json, os, subprocess, sys
from datetime import datetime
from flask import Flask, jsonify, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from scraper import fetch_all

WIB  = pytz.timezone('Asia/Jakarta')
app  = Flask(__name__)
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "latest.json")
os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Juga simpan ke scraper_static path (untuk git push ke GitHub Pages)
    static_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "latest.json")
    if static_file != DATA_FILE:
        os.makedirs(os.path.dirname(static_file), exist_ok=True)
        with open(static_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return None

def label_for_hour(h):
    if h < 11:  return "pagi"
    if h < 14:  return "siang"
    return "penutupan"

def notify(title, message):
    """macOS notification via osascript."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}" sound name "Glass"'],
            check=False, capture_output=True
        )
    except Exception:
        pass

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

def git_push():
    """Commit & push latest.json ke GitHub Pages."""
    try:
        wib_time = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")
        subprocess.run(["git", "-C", REPO_DIR, "pull", "--rebase", "origin", "main"],
                       capture_output=True, timeout=30)
        subprocess.run(["git", "-C", REPO_DIR, "add", "data/latest.json"],
                       capture_output=True, timeout=10)
        result = subprocess.run(
            ["git", "-C", REPO_DIR, "diff", "--staged", "--quiet"],
            capture_output=True
        )
        if result.returncode != 0:  # ada perubahan
            subprocess.run(
                ["git", "-C", REPO_DIR, "commit", "-m", f"data: update IDX {wib_time}"],
                capture_output=True, timeout=10
            )
            subprocess.run(["git", "-C", REPO_DIR, "push", "origin", "main"],
                           capture_output=True, timeout=30)
            print(f"[{datetime.now(WIB).strftime('%H:%M')}] Pushed to GitHub Pages ✅")
    except Exception as e:
        print(f"[git_push] error: {e}", file=sys.stderr)

def refresh(session_label=None):
    now = datetime.now(WIB)
    label = session_label or label_for_hour(now.hour)
    label_display = {"pagi": "🌅 Sesi Pagi", "siang": "☀️ Sesi Siang", "penutupan": "🌆 Menjelang Tutup"}.get(label, label)
    print(f"[{now.strftime('%H:%M')}] Fetching IDX data — sesi {label}…")
    try:
        data = fetch_all(label)
        save(data)
        git_push()
        # Ringkasan untuk notifikasi
        top3 = ", ".join(f"{s['code']} {s['change_pct']:+.1f}%" for s in data["gainers"][:3])
        inter_count = len(data["intersection"])
        notify(
            f"IDX Dashboard — {label_display}",
            f"Top: {top3} | {inter_count} intersection"
        )
        print(f"[{now.strftime('%H:%M')}] Done — {len(data['gainers'])} gainers, {inter_count} intersection.")
    except Exception as e:
        print(f"[{now.strftime('%H:%M')}] Error: {e}", file=sys.stderr)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/data")
def api_data():
    d = load()
    if not d:
        return jsonify({"error": "No data yet — waiting for first scheduled fetch."}), 404
    return jsonify(d)

@app.route("/api/refresh")
def api_refresh():
    refresh()
    return jsonify({"status": "ok", "time": datetime.now(WIB).strftime("%H:%M WIB")})


# ── Scheduler ─────────────────────────────────────────────────────────────────
# IDX: buka 09:00, istirahat 11:30-13:30, tutup 15:50 WIB

scheduler = BackgroundScheduler(timezone=WIB)

# Tiap menit selama jam bursa (09:00–16:00, Senin–Jumat)
scheduler.add_job(
    lambda: refresh(),
    CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*", timezone=WIB),
    id="minutely"
)

# Notifikasi macOS di 3 waktu kunci
scheduler.add_job(lambda: refresh("pagi"),       CronTrigger(day_of_week="mon-fri", hour=9,  minute=17, timezone=WIB), id="notif_pagi")
scheduler.add_job(lambda: refresh("siang"),      CronTrigger(day_of_week="mon-fri", hour=12, minute=3,  timezone=WIB), id="notif_siang")
scheduler.add_job(lambda: refresh("penutupan"),  CronTrigger(day_of_week="mon-fri", hour=15, minute=37, timezone=WIB), id="notif_tutup")


if __name__ == "__main__":
    scheduler.start()
    print("Scheduler aktif: 09:17 | 12:03 | 15:37 WIB (Senin–Jumat)")
    # Fetch sekali saat startup jika belum ada data
    if not load():
        refresh()
    app.run(host="0.0.0.0", port=5050, debug=False)
