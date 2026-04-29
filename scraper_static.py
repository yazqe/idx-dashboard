"""Standalone scraper for GitHub Actions — no Flask dependency."""
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
COLUMNS = ["name", "description", "close", "change", "volume", "Value.Traded"]
OUT = os.path.join(os.path.dirname(__file__), "data", "latest.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)


def scan(sort_by, sort_order="desc", limit=20, filters=None):
    payload = {
        "filter": filters or [],
        "symbols": {"query": {"types": ["stock"]}},
        "columns": COLUMNS,
        "sort": {"sortBy": sort_by, "sortOrder": sort_order},
        "range": [0, limit]
    }
    r = requests.post(SCANNER_URL, headers=HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    out = []
    for item in r.json().get("data", []):
        d = item.get("d", [None]*6)
        out.append({
            "code":       (d[0] or "").replace("IDX:", ""),
            "name":       d[1] or "",
            "price":      d[2],
            "change_pct": round(d[3] or 0, 2),
            "volume":     int(d[4] or 0),
            "value":      d[5] or 0,
        })
    return out


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
            "close":       round(close, 2) if close else None,
            "change_pct":  chgp,
            "change_abs":  chg,
            "high":        meta.get("regularMarketDayHigh"),
            "low":         meta.get("regularMarketDayLow"),
            "open":        meta.get("regularMarketOpen"),
            "volume":      int(meta.get("regularMarketVolume") or 0),
            "market_open": meta.get("marketState") == "REGULAR",
            "market_state": meta.get("marketState", "CLOSED"),
            "as_of":       datetime.now(WIB).strftime("%d %b %Y %H:%M WIB"),
        }
    except Exception as e:
        print(f"IHSG error: {e}")
        return {}


def find_intersection(gainers, volume, value):
    reg = {}
    def add(s, cat):
        c = s["code"]
        if c not in reg:
            reg[c] = {**s, "categories": []}
        if cat not in reg[c]["categories"]:
            reg[c]["categories"].append(cat)
    for s in gainers: add(s, "gainer")
    for s in volume:  add(s, "volume")
    for s in value:   add(s, "value")
    multi = [v for v in reg.values() if len(v["categories"]) >= 2]
    multi.sort(key=lambda x: (len(x["categories"]), x.get("volume", 0)), reverse=True)
    return multi


def build_watchlist(intersection, gainers):
    seen, picks = set(), []
    for s in sorted(intersection, key=lambda x: len(x["categories"]), reverse=True):
        if s["code"] not in seen:
            picks.append(s); seen.add(s["code"])
        if len(picks) >= 5: break
    if len(picks) < 5:
        for s in sorted(gainers, key=lambda x: x.get("volume", 0), reverse=True):
            if s["code"] not in seen:
                picks.append(s); seen.add(s["code"])
            if len(picks) >= 5: break
    return picks[:5]


def fmt_vol(v):
    if not v: return "–"
    if v >= 1e12: return f"{v/1e12:.2f}T"
    if v >= 1e9:  return f"{v/1e9:.2f}B"
    if v >= 1e6:  return f"{v/1e6:.1f}M"
    return f"{v/1e3:.0f}K"


def generate_analysis(ihsg, gainers, volume, value, inters, watch, now):
    """Auto-generate scalper analysis from market data."""

    triple  = [s for s in inters if len(s["categories"]) == 3]
    crashes = [s for s in gainers + volume + value if (s.get("change_pct") or 0) < -8]
    seen_crash = set()
    unique_crashes = []
    for s in crashes:
        if s["code"] not in seen_crash:
            unique_crashes.append(s); seen_crash.add(s["code"])

    # Watchlist reasons
    watchlist_notes = []
    for s in watch:
        cats = s.get("categories", [])
        vol_str  = fmt_vol(s.get("volume", 0))
        val_str  = fmt_vol(s.get("value", 0))
        chg      = s.get("change_pct", 0)
        cat_str  = " + ".join(c.capitalize() for c in cats)

        if len(cats) == 3:
            reason = f"Triple intersection ({cat_str}). Vol {vol_str} sangat liquid. Momentum terkuat hari ini."
        elif "gainer" in cats and "volume" in cats:
            reason = f"Gain +{chg:.1f}% dengan volume {vol_str} — momentum kuat, liquid untuk scalp."
        elif "volume" in cats and "value" in cats:
            reason = f"Volume {vol_str} & nilai Rp{val_str} — paling liquid, spread kecil."
        else:
            reason = f"Kategori: {cat_str}. Vol {vol_str}, Nilai Rp{val_str}."

        # Entry/exit guidance
        price = s.get("price", 0) or 0
        if price > 0 and chg > 0:
            entry_low  = round(price * 0.96 / (1 if price >= 100 else 5)) * (1 if price >= 100 else 5)
            target     = round(price * 1.04 / (1 if price >= 100 else 5)) * (1 if price >= 100 else 5)
            stop       = round(price * 0.93 / (1 if price >= 100 else 5)) * (1 if price >= 100 else 5)
            guidance   = f"Entry area Rp{entry_low:,} | Target Rp{target:,} | Stop Rp{stop:,}"
        else:
            guidance = "Pantau open besok untuk konfirmasi arah."

        watchlist_notes.append({
            "code":    s["code"],
            "name":    s.get("name", ""),
            "price":   price,
            "change":  chg,
            "volume":  s.get("volume", 0),
            "value":   s.get("value", 0),
            "cats":    cats,
            "reason":  reason,
            "guidance": guidance,
        })

    # Signals — positive
    signals = []
    for s in triple:
        signals.append({
            "type": "bullish",
            "icon": "🔥",
            "code": s["code"],
            "text": f"Triple intersection — masuk Gainer + Volume + Value sekaligus. Sinyal terkuat."
        })
    vol_king = sorted(volume, key=lambda x: x.get("volume", 0), reverse=True)
    if vol_king:
        v = vol_king[0]
        signals.append({
            "type": "info",
            "icon": "📈",
            "code": v["code"],
            "text": f"Volume king hari ini: {fmt_vol(v.get('volume',0))} shares — paling liquid untuk scalp."
        })

    # Warnings
    warnings = []
    for s in unique_crashes[:3]:
        warnings.append({
            "code": s["code"],
            "change": s.get("change_pct", 0),
            "text": f"Turun {s.get('change_pct',0):.1f}% — hindari untuk long, potensi tekanan berlanjut."
        })
    # High gain low volume = pump risk
    for s in gainers[:5]:
        vol = s.get("volume", 0)
        chg = s.get("change_pct", 0)
        if chg > 20 and vol < 10_000_000:
            warnings.append({
                "code": s["code"],
                "change": chg,
                "text": f"Naik +{chg:.1f}% tapi volume hanya {fmt_vol(vol)} — rentan profit taking, tidak liquid."
            })

    # Market summary
    is_positive = (ihsg.get("change_pct") or 0) >= 0
    ihsg_chg    = ihsg.get("change_pct") or 0
    ihsg_close  = ihsg.get("close") or 0
    ihsg_h      = ihsg.get("high") or 0
    ihsg_l      = ihsg.get("low") or 0
    day_range   = round(ihsg_h - ihsg_l, 2) if ihsg_h and ihsg_l else 0

    # Window dressing check (last 3 days of month)
    is_month_end = now.day >= 28
    session_label = {"pagi": "Sesi Pagi", "siang": "Sesi Siang", "penutupan": "Menjelang Penutupan"}.get(
        ("pagi" if now.hour < 11 else "siang" if now.hour < 14 else "penutupan"), "")

    summary = {
        "ihsg_close":   ihsg_close,
        "ihsg_change":  ihsg_chg,
        "ihsg_high":    ihsg_h,
        "ihsg_low":     ihsg_l,
        "day_range":    day_range,
        "is_positive":  is_positive,
        "is_month_end": is_month_end,
        "session_label": session_label,
        "top_gainer":   gainers[0]["code"] if gainers else "–",
        "top_gainer_chg": gainers[0].get("change_pct", 0) if gainers else 0,
        "vol_king":     volume[0]["code"] if volume else "–",
        "vol_king_vol": fmt_vol(volume[0].get("volume", 0)) if volume else "–",
        "triple_count": len(triple),
        "intersection_count": len(inters),
    }

    return {
        "watchlist_notes": watchlist_notes,
        "signals":  signals,
        "warnings": warnings,
        "summary":  summary,
    }


now = datetime.now(WIB)
hour = now.hour
session = "pagi" if hour < 11 else "siang" if hour < 14 else "penutupan"

ihsg    = get_ihsg()
gainers = scan("change", "desc", 20, [{"left":"change","operation":"greater","right":0},{"left":"volume","operation":"greater","right":500_000}])
volume  = scan("volume", "desc", 20)
value   = scan("Value.Traded", "desc", 20)
inters  = find_intersection(gainers, volume, value)
watch   = build_watchlist(inters, gainers)
analysis = generate_analysis(ihsg, gainers, volume, value, inters, watch, now)

data = {
    "session":      session,
    "timestamp":    now.isoformat(),
    "date":         now.strftime("%d %B %Y"),
    "time":         now.strftime("%H:%M WIB"),
    "ihsg":         ihsg,
    "gainers":      gainers,
    "volume":       volume,
    "value":        value,
    "intersection": inters,
    "watchlist":    watch,
    "analysis":     analysis,
}

with open(OUT, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"✅ {now.strftime('%H:%M WIB')} | IHSG: {ihsg.get('close')} | Gainers: {len(gainers)} | Intersection: {len(inters)}")
