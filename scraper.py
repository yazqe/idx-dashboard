import json
import os
import requests
import pytz
from datetime import datetime

WIB = pytz.timezone('Asia/Jakarta')
SCANNER_URL = "https://scanner.tradingview.com/indonesia/scan"
HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://id.tradingview.com",
    "Referer": "https://id.tradingview.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
COLUMNS = ["name", "description", "close", "change", "volume", "Value.Traded"]


def _scan(sort_by, sort_order="desc", limit=20, filters=None):
    payload = {
        "filter": filters or [],
        "options": {},
        "symbols": {"query": {"types": ["stock"]}},
        "columns": COLUMNS,
        "sort": {"sortBy": sort_by, "sortOrder": sort_order},
        "range": [0, limit]
    }
    try:
        r = requests.post(SCANNER_URL, headers=HEADERS, json=payload, timeout=12)
        r.raise_for_status()
        out = []
        for item in r.json().get("data", []):
            d = item.get("d", [None] * 6)
            out.append({
                "code":       (d[0] or "").replace("IDX:", ""),
                "name":       d[1] or "",
                "price":      d[2],
                "change_pct": round(d[3] or 0, 2),
                "volume":     int(d[4] or 0),
                "value":      d[5] or 0,
            })
        return out
    except Exception as e:
        print(f"[scraper] error {sort_by}: {e}")
        return []


def get_top_gainers(limit=20):
    return _scan("change", "desc", limit, [
        {"left": "change",  "operation": "greater", "right": 0},
        {"left": "volume",  "operation": "greater", "right": 500_000},
    ])


def get_top_volume(limit=20):
    return _scan("volume", "desc", limit)


def get_top_value(limit=20):
    return _scan("Value.Traded", "desc", limit)


def find_intersection(gainers, volume, value):
    registry = {}

    def register(stock, cat):
        c = stock["code"]
        if c not in registry:
            registry[c] = {**stock, "categories": []}
        if cat not in registry[c]["categories"]:
            registry[c]["categories"].append(cat)

    for s in gainers: register(s, "gainer")
    for s in volume:  register(s, "volume")
    for s in value:   register(s, "value")

    multi = [v for v in registry.values() if len(v["categories"]) >= 2]
    multi.sort(key=lambda x: (len(x["categories"]), x.get("volume", 0)), reverse=True)
    return multi


def build_watchlist(intersection, gainers):
    seen = set()
    picks = []

    for s in sorted(intersection, key=lambda x: len(x["categories"]), reverse=True):
        if s["code"] not in seen:
            picks.append(s)
            seen.add(s["code"])
        if len(picks) >= 5:
            break

    if len(picks) < 5:
        for s in sorted(gainers, key=lambda x: x.get("volume", 0), reverse=True):
            if s["code"] not in seen:
                picks.append(s)
                seen.add(s["code"])
            if len(picks) >= 5:
                break

    result = picks[:5]
    for s in result:
        s["analysis"] = _analyze_stock(s)
    return result


def _tick_round(price):
    if price <= 0:     return 0
    if price < 200:    return round(price)
    if price < 500:    return round(price / 2) * 2
    if price < 2000:   return round(price / 5) * 5
    if price < 5000:   return round(price / 10) * 10
    return round(price / 25) * 25


def _analyze_stock(stock):
    price      = stock.get("price") or 0
    change_pct = stock.get("change_pct") or 0
    volume     = stock.get("volume") or 0
    value      = stock.get("value") or 0
    categories = stock.get("categories", [])
    cat_count  = len(categories)

    if price <= 0:
        return {}

    # Estimated previous close & ARA
    prev_close      = price / (1 + change_pct / 100) if change_pct != -100 else price
    ara_price       = _tick_round(prev_close * 1.25)
    ara_dist        = round((ara_price - price) / price * 100, 1) if price else 0
    ara_hit         = ara_dist <= 2

    # Key levels
    sl       = _tick_round(price * 0.95)
    target1  = _tick_round(price * 1.04)
    target2  = ara_price if ara_dist > 3 else _tick_round(price * 1.08)
    rr       = round((target1 - price) / (price - sl), 1) if price > sl else 0

    # Signal & pattern
    if ara_hit:
        signal, pattern = "WAIT",         "Mendekati Ceiling ARA"
    elif cat_count == 3 and change_pct >= 15:
        signal, pattern = "STRONG BUY",   "Triple Intersection + Momentum Kuat"
    elif cat_count == 3:
        signal, pattern = "BUY",          "Triple Intersection"
    elif cat_count == 2 and change_pct >= 15:
        signal, pattern = "BUY",          "Double Intersection + Gainer Kuat"
    elif cat_count == 2:
        signal, pattern = "WATCH",        "Double Intersection"
    else:
        signal, pattern = "WATCH",        "Single Momentum"

    # Risk
    if ara_hit:            risk, risk_cls = "CEILING",  "risk-ceiling"
    elif change_pct >= 20: risk, risk_cls = "Tinggi",   "risk-high"
    elif change_pct >= 10: risk, risk_cls = "Moderat",  "risk-mod"
    else:                  risk, risk_cls = "Rendah",   "risk-low"

    # Pro tip
    if ara_hit:
        tip = (f"Harga sudah di ceiling ARA (Rp{ara_price:,}). "
               "Tidak ada ruang naik hari ini. Tunggu besok, cek opening candle.")
    elif cat_count == 3 and ara_dist >= 8:
        tip = (f"Setup terkuat — triple intersection, {ara_dist}% ruang ke ARA Rp{ara_price:,}. "
               f"Entry area sekarang, target 1 Rp{target1:,} · target 2 Rp{target2:,}. SL Rp{sl:,} · R/R {rr}x.")
    elif cat_count >= 2 and ara_dist >= 6:
        tip = (f"Double intersection, {ara_dist}% ruang ke ARA Rp{ara_price:,}. "
               f"Entry Rp{price:,}, target Rp{target1:,}, SL Rp{sl:,}. "
               "Konfirmasi volume sebelum masuk.")
    else:
        tip = (f"Pantau apakah harga hold di atas Rp{sl:,}. "
               f"ARA target Rp{ara_price:,} (+{ara_dist}%). Masuk hanya jika volume naik.")

    return {
        "prev_close":  round(prev_close),
        "ara_price":   ara_price,
        "ara_dist":    ara_dist,
        "ara_hit":     ara_hit,
        "sl":          sl,
        "target1":     target1,
        "target2":     target2,
        "rr":          rr,
        "risk":        risk,
        "risk_cls":    risk_cls,
        "pattern":     pattern,
        "signal":      signal,
        "tip":         tip,
        "value_b":     round(value / 1e9, 1),
        "cat_count":   cat_count,
    }


IHSG_CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "ihsg_last.json")

def _save_ihsg(data):
    os.makedirs(os.path.dirname(IHSG_CACHE_FILE), exist_ok=True)
    with open(IHSG_CACHE_FILE, "w") as f:
        json.dump(data, f)

def _load_ihsg():
    if os.path.exists(IHSG_CACHE_FILE):
        with open(IHSG_CACHE_FILE) as f:
            return json.load(f)
    return {}

def _get_ihsg_yahoo():
    """Fallback: Yahoo Finance always has EOD data even when market is closed."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
        meta = r.json()["chart"]["result"][0]["meta"]
        # regularMarketPrice = last close, previousClose = prev day close
        close  = meta.get("regularMarketPrice")
        prev   = meta.get("previousClose") or meta.get("chartPreviousClose")
        high   = meta.get("regularMarketDayHigh")
        low    = meta.get("regularMarketDayLow")
        open_  = meta.get("regularMarketOpen")
        volume = meta.get("regularMarketVolume", 0)
        change_abs = round((close - prev), 2) if close and prev else 0
        change_pct = round((change_abs / prev * 100), 2) if prev else 0
        # Determine if market is currently open
        market_state = meta.get("marketState", "CLOSED")  # REGULAR, PRE, POST, CLOSED
        is_open = market_state == "REGULAR"
        return {
            "close":       round(close, 2) if close else None,
            "change_pct":  change_pct,
            "change_abs":  change_abs,
            "high":        round(high, 2) if high else None,
            "low":         round(low, 2) if low else None,
            "open":        round(open_, 2) if open_ else None,
            "volume":      int(volume or 0),
            "value":       0,
            "market_open": is_open,
            "market_state": market_state,
            "as_of":       datetime.now(WIB).strftime("%d %b %Y %H:%M WIB"),
        }
    except Exception as e:
        print(f"[scraper] ihsg yahoo error: {e}")
        return None


def get_ihsg():
    # 1. Try TradingView scanner (real-time during market hours)
    payload = {
        "symbols": {"tickers": ["IDX:COMPOSITE"]},
        "columns": ["close", "change", "change_abs", "high", "low", "open", "volume", "Value.Traded"]
    }
    try:
        r = requests.post(SCANNER_URL, headers=HEADERS, json=payload, timeout=10)
        r.raise_for_status()
        d = r.json().get("data", [{}])[0].get("d", [None]*8)
        if d[0] is not None:
            result = {
                "close":       d[0],
                "change_pct":  round(d[1] or 0, 2),
                "change_abs":  round(d[2] or 0, 2),
                "high":        d[3],
                "low":         d[4],
                "open":        d[5],
                "volume":      int(d[6] or 0),
                "value":       d[7] or 0,
                "market_open": True,
                "market_state": "REGULAR",
                "as_of":       datetime.now(WIB).strftime("%d %b %Y %H:%M WIB"),
            }
            _save_ihsg(result)
            return result
    except Exception as e:
        print(f"[scraper] ihsg tv error: {e}")

    # 2. Fallback: Yahoo Finance (always has data)
    ydata = _get_ihsg_yahoo()
    if ydata and ydata.get("close"):
        _save_ihsg(ydata)
        return ydata

    # 3. Last resort: cached data
    last = _load_ihsg()
    if last:
        last["market_open"] = False
        return last
    return {"market_open": False}


def fetch_all(session_label="pagi"):
    now = datetime.now(WIB)
    ihsg    = get_ihsg()
    gainers = get_top_gainers()
    volume  = get_top_volume()
    value   = get_top_value()
    inters  = find_intersection(gainers, volume, value)
    watch   = build_watchlist(inters, gainers)

    return {
        "session":      session_label,
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
