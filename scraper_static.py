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


now = datetime.now(WIB)
hour = now.hour
session = "pagi" if hour < 11 else "siang" if hour < 14 else "penutupan"

ihsg    = get_ihsg()
gainers = scan("change", "desc", 20, [{"left":"change","operation":"greater","right":0},{"left":"volume","operation":"greater","right":500_000}])
volume  = scan("volume", "desc", 20)
value   = scan("Value.Traded", "desc", 20)
inters  = find_intersection(gainers, volume, value)
watch   = build_watchlist(inters, gainers)

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
}

with open(OUT, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"✅ {now.strftime('%H:%M WIB')} | IHSG: {ihsg.get('close')} | Gainers: {len(gainers)} | Intersection: {len(inters)}")
