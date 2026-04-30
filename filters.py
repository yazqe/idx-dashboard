# Daftar saham yang di-exclude dari dashboard
# Update manual kalau ada saham baru kena suspend/UMA/delisting

SUSPENDED = {
    "WBSA",  # Suspensi
    "BAPA",  # Suspensi
}

# Auto-filter: saham dengan tanda-tanda manipulasi/tidak liquid
# Gain > 25% tapi volume < 10 juta = rawan pump & dump, tidak cocok scalp
MIN_VOLUME_GAINER = 10_000_000   # minimum volume untuk masuk top gainers
MIN_VOLUME_GENERAL = 500_000     # minimum volume untuk masuk top volume/value


def is_valid(stock, list_type="gainer"):
    """Return True kalau saham layak ditampilkan."""
    code = stock.get("code", "")
    vol  = stock.get("volume", 0) or 0
    chg  = stock.get("change_pct", 0) or 0

    # Exclude suspended/blacklisted
    if code in SUSPENDED:
        return False

    # Untuk gainers: min volume lebih tinggi
    if list_type == "gainer" and vol < MIN_VOLUME_GAINER:
        return False

    # General: min volume dasar
    if vol < MIN_VOLUME_GENERAL:
        return False

    # Exclude ARA (Auto Rejection Above) tanpa volume — harga naik tapi
    # tidak ada yang beli/jual = tidak liquid untuk scalp
    if chg >= 34 and vol < 5_000_000:
        return False

    return True
