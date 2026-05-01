"""IDX Swing Trading Dashboard Scraper."""
import json, os, requests, pytz
from datetime import datetime

WIB = pytz.timezone('Asia/Jakarta')
SCANNER_URL = "https://scanner.tradingview.com/indonesia/scan"
HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://id.tradingview.com",
    "Referer": "https://id.tradingview.com/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
}
OUT = os.path.join(os.path.dirname(__file__), "data", "latest.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

# Suspended / blacklisted stocks
SUSPENDED = {"WBSA", "BAPA"}

def fmt_vol(v):
    if not v: return "–"
    if v >= 1e12: return f"{v/1e12:.2f}T"
    if v >= 1e9:  return f"{v/1e9:.2f}B"
    if v >= 1e6:  return f"{v/1e6:.1f}M"
    return f"{v/1e3:.0f}K"


def scan(sort_by, sort_order="desc", limit=25, filters=None, columns=None):
    cols = columns or [
        "name", "description", "close", "change",
        "Perf.W", "Perf.1M", "volume",
        "average_volume_10d_calc", "Value.Traded",
        "sector", "price_52_week_high", "price_52_week_low",
        "relative_volume_10d_calc"
    ]
    payload = {
        "filter": filters or [],
        "symbols": {"query": {"types": ["stock"]}},
        "columns": cols,
        "sort": {"sortBy": sort_by, "sortOrder": sort_order},
        "range": [0, limit]
    }
    try:
        r = requests.post(SCANNER_URL, headers=HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        out = []
        for item in r.json().get("data", []):
            d = item.get("d", [None]*13)
            code = (d[0] or "").replace("IDX:", "")
            if code in SUSPENDED: continue
            high52 = d[10] or 0
            close  = d[2] or 0
            pct_from_high = round((close - high52) / high52 * 100, 1) if high52 else 0
            out.append({
                "code":         code,
                "name":         (d[1] or "")[:35],
                "price":        close,
                "change_d":     round(d[3] or 0, 2),
                "change_1w":    round(d[4] or 0, 2),   # Perf.W
                "change_1m":    round(d[5] or 0, 2),   # Perf.1M
                "volume":       int(d[6] or 0),
                "avg_vol_10d":  int(d[7] or 0),
                "value":        d[8] or 0,
                "sector":       d[9] or "–",
                "high_52w":     high52,
                "low_52w":      d[11] or 0,
                "rel_volume":   round(d[12] or 0, 2),
                "pct_from_high": pct_from_high,
            })
        return out
    except Exception as e:
        print(f"[scraper_swing] error {sort_by}: {e}")
        return []


def get_ihsg():
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        meta = r.json()["chart"]["result"][0]["meta"]
        close = meta.get("regularMarketPrice")
        prev  = meta.get("previousClose") or meta.get("chartPreviousClose")
        chg   = round(close - prev, 2) if close and prev else 0
        chgp  = round(chg / prev * 100, 2) if prev else 0
        return {
            "close":        round(close, 2) if close else None,
            "change_pct":   chgp,
            "change_abs":   chg,
            "high":         meta.get("regularMarketDayHigh"),
            "low":          meta.get("regularMarketDayLow"),
            "market_open":  meta.get("marketState") == "REGULAR",
            "market_state": meta.get("marketState", "CLOSED"),
            "as_of":        datetime.now(WIB).strftime("%d %b %Y %H:%M WIB"),
        }
    except Exception as e:
        print(f"[scraper_swing] ihsg error: {e}")
        return {}


def get_weekly_gainers():
    """Saham dengan kinerja mingguan terbaik + volume memadai."""
    return scan("Perf.W", "desc", 25, [
        {"left": "Perf.W",  "operation": "greater", "right": 5},
        {"left": "volume",  "operation": "greater", "right": 5_000_000},
        {"left": "close",   "operation": "greater", "right": 50},
    ])


def get_breakout_candidates():
    """Saham yang dekat 52-week high dengan volume surge."""
    all_stocks = scan("Perf.W", "desc", 40, [
        {"left": "volume",  "operation": "greater", "right": 10_000_000},
        {"left": "change",  "operation": "greater", "right": 0},
        {"left": "close",   "operation": "greater", "right": 100},
    ])
    # Filter: dalam 15% dari 52-week high
    candidates = [s for s in all_stocks
                  if s["high_52w"] and s["price"]
                  and s["price"] >= s["high_52w"] * 0.85
                  and s["rel_volume"] >= 1.5]
    return sorted(candidates, key=lambda x: x.get("change_1w", 0), reverse=True)[:15]


def get_sector_leaders():
    """Top gainers per sektor — identifikasi sektor rotation."""
    stocks = scan("Perf.W", "desc", 50, [
        {"left": "Perf.W",  "operation": "greater", "right": 0},
        {"left": "volume",  "operation": "greater", "right": 5_000_000},
    ])
    sectors = {}
    for s in stocks:
        sec = s["sector"]
        if sec not in sectors or s["change_1w"] > sectors[sec]["change_1w"]:
            sectors[sec] = s
    return sorted(sectors.values(), key=lambda x: x["change_1w"], reverse=True)


def get_volume_surge():
    """Saham dengan volume jauh di atas rata-rata 10 hari — potensi akumulasi."""
    return scan("relative_volume_10d_calc", "desc", 20, [
        {"left": "relative_volume_10d_calc", "operation": "greater", "right": 1.5},
        {"left": "volume",                   "operation": "greater", "right": 20_000_000},
        {"left": "Perf.W",                   "operation": "greater", "right": 0},
    ])


def generate_swing_analysis(weekly_gainers, breakouts, sector_leaders, vol_surge, ihsg):
    """Generate swing trading analysis."""
    # Watchlist: prioritas breakout + weekly gainer + vol surge
    seen, watchlist = set(), []

    # Triple quality: breakout + weekly gain > 10% + rel vol > 2x
    triple = [s for s in breakouts if s["change_1w"] > 10 and s["rel_volume"] > 2.0]
    for s in triple[:3]:
        if s["code"] not in seen:
            watchlist.append({**s, "swing_type": "breakout_momentum"})
            seen.add(s["code"])

    # Strong weekly gainers with vol surge
    for s in vol_surge[:5]:
        if s["code"] not in seen and len(watchlist) < 8:
            watchlist.append({**s, "swing_type": "accumulation"})
            seen.add(s["code"])

    # Fill with top weekly gainers
    for s in weekly_gainers[:5]:
        if s["code"] not in seen and len(watchlist) < 8:
            watchlist.append({**s, "swing_type": "momentum"})
            seen.add(s["code"])

    # Generate notes per watchlist stock
    notes = []
    for s in watchlist[:5]:
        price = s.get("price", 0) or 0
        chg1w = s.get("change_1w", 0) or 0
        chg1m = s.get("change_1m", 0) or 0
        relv  = s.get("rel_volume", 0) or 0
        high52 = s.get("high_52w", 0) or 0
        pct_h  = s.get("pct_from_high", 0) or 0
        swing_type = s.get("swing_type", "")

        if swing_type == "breakout_momentum":
            reason = (f"Breakout — harga {abs(pct_h):.1f}% dari 52W high. "
                      f"Weekly gain +{chg1w:.1f}%, volume {relv:.1f}x rata-rata. "
                      f"Momentum kuat dengan institutional interest.")
            strategy = "Swing buy on dip | Hold 1-2 minggu"
        elif swing_type == "accumulation":
            reason = (f"Akumulasi terdeteksi — volume {relv:.1f}x normal. "
                      f"Weekly +{chg1w:.1f}%, monthly {'+' if chg1m>=0 else ''}{chg1m:.1f}%. "
                      f"Smart money kemungkinan masuk posisi.")
            strategy = "Akumulasi bertahap | Hold 2-4 minggu"
        else:
            reason = (f"Momentum mingguan +{chg1w:.1f}%. "
                      f"Monthly {'+' if chg1m>=0 else ''}{chg1m:.1f}%. "
                      f"Rel vol {relv:.1f}x — likuiditas memadai untuk swing.")
            strategy = "Entry on pullback | Target +15-20%"

        # Entry/target calculation
        if price > 0 and chg1w > 0:
            entry = round(price * 0.97 / (5 if price < 200 else 50)) * (5 if price < 200 else 50)
            target = round(price * 1.15 / (5 if price < 200 else 50)) * (5 if price < 200 else 50)
            stop   = round(price * 0.92 / (5 if price < 200 else 50)) * (5 if price < 200 else 50)
            guidance = f"Entry: Rp{entry:,} | Target: Rp{target:,} (+15%) | Stop: Rp{stop:,} (-8%)"
        else:
            guidance = "Tunggu konfirmasi arah sebelum entry."

        notes.append({
            "code":     s["code"],
            "name":     s.get("name", ""),
            "price":    price,
            "change_d": s.get("change_d", 0),
            "change_1w": chg1w,
            "change_1m": chg1m,
            "volume":   s.get("volume", 0),
            "rel_volume": relv,
            "sector":   s.get("sector", "–"),
            "pct_from_high": pct_h,
            "swing_type": swing_type,
            "reason":   reason,
            "strategy": strategy,
            "guidance": guidance,
        })

    # Top sectors
    top_sectors = [{"sector": s["sector"], "change_1w": s["change_1w"],
                    "leader": s["code"]} for s in sector_leaders[:6]]

    ihsg_chg = ihsg.get("change_pct", 0) or 0
    return {
        "watchlist_notes": notes,
        "top_sectors":     top_sectors,
        "summary": {
            "ihsg_close":   ihsg.get("close"),
            "ihsg_change":  ihsg_chg,
            "is_positive":  ihsg_chg >= 0,
            "market_open":  ihsg.get("market_open", False),
            "breakout_count": len(breakouts),
            "weekly_gainer_count": len(weekly_gainers),
            "vol_surge_count": len(vol_surge),
            "top_sector": sector_leaders[0]["sector"] if sector_leaders else "–",
            "top_sector_gain": sector_leaders[0]["change_1w"] if sector_leaders else 0,
        }
    }


# ── Main ──────────────────────────────────────────────────────────────────────
now = datetime.now(WIB)

ihsg           = get_ihsg()
weekly_gainers = get_weekly_gainers()
breakouts      = get_breakout_candidates()
sector_leaders = get_sector_leaders()
vol_surge      = get_volume_surge()
analysis       = generate_swing_analysis(weekly_gainers, breakouts, sector_leaders, vol_surge, ihsg)

data = {
    "updated":        now.strftime("%d %B %Y %H:%M WIB"),
    "date":           now.strftime("%d %B %Y"),
    "time":           now.strftime("%H:%M WIB"),
    "ihsg":           ihsg,
    "weekly_gainers": weekly_gainers[:15],
    "breakouts":      breakouts[:12],
    "sector_leaders": sector_leaders[:8],
    "vol_surge":      vol_surge[:12],
    "analysis":       analysis,
}

with open(OUT, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"✅ {now.strftime('%H:%M WIB')} | Weekly gainers: {len(weekly_gainers)} | Breakouts: {len(breakouts)} | Vol surge: {len(vol_surge)}")
