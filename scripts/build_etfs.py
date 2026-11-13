#!/usr/bin/env python3
"""
Leverage Scout data builder.

Finds every leveraged and inverse ETF/ETN listed in the US, works out what
each one tracks, and writes data/etfs.json and data/etfs.js for the web page.

Sources
  Massive (formerly Polygon)  - full list of active ETFs, ETNs and stocks
  Financial Modeling Prep     - company name, sector and industry for each
                                underlying stock, plus ETF expense ratio,
                                AUM and inception date when available

Keys are read from environment variables FMP_API_KEY and MASSIVE_API_KEY,
or from a .env file in the project root (never commit that file).

Only the Python standard library is used, so there is nothing to pip install.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE_FILE = DATA / "cache.json"
OVERRIDES_FILE = DATA / "overrides.json"
OUT_JSON = DATA / "etfs.json"
OUT_JS = DATA / "etfs.js"

MASSIVE_BASE = "https://api.massive.com"
FMP_BASE = "https://financialmodelingprep.com/stable"

MASSIVE_DELAY = 13          # free plan allows 5 calls per minute
FMP_DELAY = 0.4
FMP_BUDGET = int(os.environ.get("FMP_BUDGET", "200"))   # free plan is 250/day
CACHE_DAYS = 30             # refetch profiles/ETF info after this many days


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def log(msg):
    print(msg, flush=True)


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class HttpError(Exception):
    def __init__(self, code, body=""):
        super().__init__(f"HTTP {code}: {body[:200]}")
        self.code = code


def http_json(url, retries=3):
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": "LeverageScout/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore") if e.fp else ""
            if e.code == 429 and attempt < retries - 1:
                log("  rate limited, waiting 65s...")
                time.sleep(65)
                continue
            raise HttpError(e.code, body)
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(5)
                continue
            raise HttpError(0, str(e))
    raise HttpError(0, "retries exhausted")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def is_fresh(entry):
    try:
        ts = datetime.fromisoformat(entry["_fetched"])
        return datetime.now(timezone.utc) - ts < timedelta(days=CACHE_DAYS)
    except (KeyError, TypeError, ValueError):
        return False


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Massive: ticker lists
# --------------------------------------------------------------------------

def massive_list(ticker_type, key):
    params = {"market": "stocks", "type": ticker_type, "active": "true",
              "limit": "1000", "apiKey": key}
    url = f"{MASSIVE_BASE}/v3/reference/tickers?" + urllib.parse.urlencode(params)
    out = []
    while url:
        data = http_json(url)
        out.extend(data.get("results", []) or [])
        nxt = data.get("next_url")
        if nxt:
            sep = "&" if "?" in nxt else "?"
            url = f"{nxt}{sep}apiKey={key}"
            time.sleep(MASSIVE_DELAY)
        else:
            url = None
    log(f"  {ticker_type}: {len(out)} tickers")
    time.sleep(MASSIVE_DELAY)
    return out


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

# Phrases that look like "short" or "ultra" but are bond duration or income
# products, not leverage.
EXCLUDE_PHRASES = [
    "short-term", "short term", "short duration", "short maturity",
    "ultra-short", "ultra short", "ultrashort income", "ultrashort bond",
    "short treasury", "short-dated", "option income", "covered call",
    "buffer", "premium income", "yieldmax", "income strategy",
    "short high yield", "short-duration",
]

ISSUERS = [
    ("direxion", "Direxion"), ("proshares", "ProShares"),
    ("graniteshares", "GraniteShares"), ("tradr", "Tradr"),
    ("defiance", "Defiance"), ("t-rex", "REX / Tuttle"),
    ("rex ", "REX Shares"), ("leverage shares", "Leverage Shares"),
    ("roundhill", "Roundhill"), ("volatility shares", "Volatility Shares"),
    ("microsectors", "MicroSectors (BMO)"), ("axs", "AXS"),
    ("kurv", "Kurv"), ("ishares", "iShares"), ("tuttle", "Tuttle Capital"),
    ("valkyrie", "Valkyrie"), ("cyber hornet", "Cyber Hornet"),
    ("21shares", "21Shares"), ("2x", "Other"),
]

# Words in fund names that look like tickers but are not.
STOPWORDS = {
    "ETF", "ETN", "ETFS", "ETNS", "DAILY", "LONG", "SHORT", "BULL", "BEAR",
    "TARGET", "US", "USA", "X", "II", "III", "INC", "LLC", "LP", "TRUST",
    "FUND", "SHARES", "INDEX", "THE", "AND", "OF", "S", "P", "NYSE", "FANG",
    "CSI", "MSCI", "FTSE", "BMO", "REX", "AXS", "GX", "UBS", "NA", "BTC",
    "ETH", "SOL", "XRP", "VIX", "AI", "A", "I", "IN", "ON", "UP", "DOWN",
    "PLUS", "PRO", "MAX", "NEW", "ONE", "TWO", "DJ", "GDX", "GDXJ", "WTI",
    "ADR", "ADRS", "CL", "CLASS", "SER", "SERIES", "ULTRA", "SP", "NDX",
}

# (pattern, underlying label, kind, sector, industry); first match wins
THEMES = [
    (r"fang", "NYSE FANG+ Index", "Index", "Technology", "Mega-Cap Tech"),
    (r"magnificent|mag 7|mag7", "Magnificent 7", "Index", "Technology", "Mega-Cap Tech"),
    (r"semiconductor|\bsox\b", "Semiconductor Index (SOXX)", "Sector", "Technology", "Semiconductors"),
    (r"nasdaq[- ]?100|\bqqq\b", "Nasdaq-100 (QQQ)", "Index", "Broad Market", "Large-Cap Growth"),
    (r"s&p ?500|\bspy\b|s&p500", "S&P 500 (SPY)", "Index", "Broad Market", "Large-Cap Blend"),
    (r"dow ?30|dow jones|\bdow\b", "Dow Jones Industrial Average (DIA)", "Index", "Broad Market", "Large-Cap Blend"),
    (r"russell ?2000|small ?cap", "Russell 2000 (IWM)", "Index", "Broad Market", "Small-Cap"),
    (r"mid ?cap", "S&P MidCap 400 (MDY)", "Index", "Broad Market", "Mid-Cap"),
    (r"vix|volatility", "VIX Futures", "Volatility", "Volatility", "VIX Futures"),
    (r"bitcoin", "Bitcoin", "Crypto", "Crypto", "Bitcoin"),
    (r"\bether\b|ethereum", "Ether", "Crypto", "Crypto", "Ether"),
    (r"solana", "Solana", "Crypto", "Crypto", "Solana"),
    (r"\bxrp\b", "XRP", "Crypto", "Crypto", "XRP"),
    (r"crypto|blockchain", "Crypto basket", "Crypto", "Crypto", "Crypto Basket"),
    (r"biotech", "Biotech Index (XBI)", "Sector", "Healthcare", "Biotechnology"),
    (r"pharma", "Pharmaceutical Index", "Sector", "Healthcare", "Drug Manufacturers"),
    (r"health ?care", "Health Care Sector (XLV)", "Sector", "Healthcare", "Healthcare Sector"),
    (r"regional bank", "Regional Banks (KRE)", "Sector", "Financial Services", "Banks - Regional"),
    (r"\bbank", "Banks", "Sector", "Financial Services", "Banks"),
    (r"financial", "Financial Sector (XLF)", "Sector", "Financial Services", "Financial Sector"),
    (r"junior gold", "Junior Gold Miners (GDXJ)", "Sector", "Basic Materials", "Gold Miners"),
    (r"gold miner", "Gold Miners (GDX)", "Sector", "Basic Materials", "Gold Miners"),
    (r"silver miner", "Silver Miners", "Sector", "Basic Materials", "Silver Miners"),
    (r"\bgold\b", "Gold (GLD)", "Commodity", "Commodities", "Gold"),
    (r"\bsilver\b", "Silver (SLV)", "Commodity", "Commodities", "Silver"),
    (r"natural gas", "Natural Gas (UNG)", "Commodity", "Commodities", "Natural Gas"),
    (r"oil ?& ?gas|oil and gas|exploration", "Oil & Gas E&P (XOP)", "Sector", "Energy", "Oil & Gas E&P"),
    (r"crude|\boil\b", "Crude Oil (USO)", "Commodity", "Commodities", "Crude Oil"),
    (r"energy", "Energy Sector (XLE)", "Sector", "Energy", "Energy Sector"),
    (r"uranium|nuclear", "Uranium / Nuclear", "Sector", "Energy", "Uranium"),
    (r"20\+ ?y|long[- ]term treasur", "20+ Year Treasuries (TLT)", "Bonds", "Fixed Income", "Long-Term Treasuries"),
    (r"7-10 ?y", "7-10 Year Treasuries", "Bonds", "Fixed Income", "Intermediate Treasuries"),
    (r"treasur|bond", "Treasuries", "Bonds", "Fixed Income", "Treasuries"),
    (r"china|csi 300", "China", "International", "International", "China"),
    (r"emerging", "Emerging Markets", "International", "International", "Emerging Markets"),
    (r"india", "India", "International", "International", "India"),
    (r"brazil", "Brazil", "International", "International", "Brazil"),
    (r"mexico", "Mexico", "International", "International", "Mexico"),
    (r"korea", "South Korea", "International", "International", "South Korea"),
    (r"japan", "Japan", "International", "International", "Japan"),
    (r"europe|eurozone", "Europe", "International", "International", "Europe"),
    (r"developed markets|eafe", "Developed Markets", "International", "International", "Developed Markets"),
    (r"real estate|reit", "Real Estate Sector (XLRE)", "Sector", "Real Estate", "Real Estate Sector"),
    (r"homebuilder", "Homebuilders (XHB)", "Sector", "Consumer Cyclical", "Residential Construction"),
    (r"retail", "Retail", "Sector", "Consumer Cyclical", "Retail"),
    (r"consumer discretionary", "Consumer Discretionary", "Sector", "Consumer Cyclical", "Consumer Discretionary"),
    (r"consumer staples", "Consumer Staples", "Sector", "Consumer Defensive", "Consumer Staples"),
    (r"utilit", "Utilities Sector (XLU)", "Sector", "Utilities", "Utilities Sector"),
    (r"aerospace|defense", "Aerospace & Defense", "Sector", "Industrials", "Aerospace & Defense"),
    (r"transport", "Transportation", "Sector", "Industrials", "Transportation"),
    (r"industrial", "Industrials Sector (XLI)", "Sector", "Industrials", "Industrials Sector"),
    (r"materials", "Materials Sector", "Sector", "Basic Materials", "Materials Sector"),
    (r"communication", "Communication Services", "Sector", "Communication Services", "Communication Services"),
    (r"cloud", "Cloud Computing", "Sector", "Technology", "Cloud Computing"),
    (r"cyber", "Cybersecurity", "Sector", "Technology", "Cybersecurity"),
    (r"quantum", "Quantum Computing", "Sector", "Technology", "Quantum Computing"),
    (r"artificial intelligence|\bai\b|robotics", "AI & Robotics", "Sector", "Technology", "AI & Robotics"),
    (r"internet", "Internet", "Sector", "Technology", "Internet"),
    (r"innovation", "Innovation", "Sector", "Technology", "Innovation"),
    (r"technology|\btech\b", "Technology Sector (XLK)", "Sector", "Technology", "Technology Sector"),
    (r"cannabis", "Cannabis", "Sector", "Healthcare", "Cannabis"),
]


def parse_leverage(name):
    """Return (leverage, direction) or None if the fund is not leveraged/inverse."""
    low = name.lower()
    inverse_word = re.search(r"\b(short|inverse|bear|ultrashort)\b", low) is not None

    m = re.search(r"(-?\d+(?:\.\d+)?)\s*x\b", low)
    if m:
        val = float(m.group(1))
        if val < 0:
            return abs(val), "Inverse"
        if 1 <= val <= 5:
            direction = "Inverse" if inverse_word else "Long"
            if direction == "Long" and val == 1:
                return None
            return val, direction

    if "ultrapro short" in low:
        return 3.0, "Inverse"
    if "ultrapro" in low:
        return 3.0, "Long"
    if "ultrashort" in low:
        return 2.0, "Inverse"
    if re.search(r"\bultra\b", low) and "proshares" in low:
        return 2.0, "Long"
    if low.startswith("proshares short"):
        return 1.0, "Inverse"
    if re.search(r"\b(bear|inverse)\b", low):
        return 1.0, "Inverse"
    if re.search(r"\bshort\b", low) and "daily" in low:
        return 1.0, "Inverse"
    return None


def is_excluded(name):
    low = name.lower()
    if "vix" in low or "volatility" in low:
        return False
    return any(p in low for p in EXCLUDE_PHRASES)


def issuer_of(name):
    low = name.lower()
    for key, label in ISSUERS:
        if key in low:
            return label
    return name.split()[0] if name else ""


def fmt_lev(v):
    return int(v) if float(v).is_integer() else v


def find_underlying(name, own_ticker, stock_syms, etf_syms, aliases):
    """Return dict with underlying info based on the fund name."""
    # 1. explicit ticker in the name, e.g. "GraniteShares 2x Long NVDA Daily ETF"
    for tok in re.findall(r"\b[A-Z][A-Z.]{0,5}\b", name):
        tok = tok.rstrip(".")
        if len(tok) < 2 or tok in STOPWORDS or tok == own_ticker:
            continue
        if tok in stock_syms:
            return {"u": tok, "kind": "Single Stock"}

    # 2. company name in the fund name, e.g. "T-Rex 2X Long Tesla Daily Target ETF"
    low = name.lower()
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(r"\b" + re.escape(alias) + r"\b", low):
            return {"u": aliases[alias], "kind": "Single Stock"}

    # 3. index, sector, commodity or crypto theme
    for pat, label, kind, sector, industry in THEMES:
        if re.search(pat, low):
            return {"u": "", "un": label, "kind": kind, "sec": sector, "ind": industry}

    # 4. another ETF named in the fund name
    for tok in re.findall(r"\b[A-Z]{2,5}\b", name):
        if tok not in STOPWORDS and tok != own_ticker and tok in etf_syms:
            return {"u": tok, "un": etf_syms[tok], "kind": "ETF", "sec": "Other", "ind": ""}

    return {"u": "", "un": "", "kind": "Other", "sec": "Other", "ind": ""}


# --------------------------------------------------------------------------
# FMP enrichment
# --------------------------------------------------------------------------

class FMP:
    def __init__(self, key, cache):
        self.key = key
        self.cache = cache
        self.calls = 0
        self.etf_info_ok = not cache.get("etf_info_blocked_until") or \
            cache["etf_info_blocked_until"] < now_iso()

    def _get(self, path, symbol):
        if self.calls >= FMP_BUDGET:
            return None
        url = f"{FMP_BASE}/{path}?" + urllib.parse.urlencode({"symbol": symbol, "apikey": self.key})
        self.calls += 1
        time.sleep(FMP_DELAY)
        data = http_json(url)
        if isinstance(data, list):
            return data[0] if data else {}
        if isinstance(data, dict) and ("Error Message" in data or "error" in data):
            raise HttpError(402, json.dumps(data))
        return data

    def profile(self, symbol):
        store = self.cache.setdefault("profiles", {})
        if symbol in store and is_fresh(store[symbol]):
            return store[symbol]
        try:
            p = self._get("profile", symbol)
        except HttpError as e:
            log(f"  FMP profile {symbol}: {e}")
            return store.get(symbol)
        if p is None:
            return store.get(symbol)
        store[symbol] = {"name": p.get("companyName", ""), "sec": p.get("sector", ""),
                         "ind": p.get("industry", ""), "_fetched": now_iso()}
        return store[symbol]

    def etf_info(self, symbol):
        store = self.cache.setdefault("etf_info", {})
        if symbol in store and is_fresh(store[symbol]):
            return store[symbol]
        if not self.etf_info_ok:
            return store.get(symbol)
        try:
            d = self._get("etf/info", symbol)
        except HttpError as e:
            if e.code in (401, 402, 403):
                log("  FMP etf/info is not available on this plan; skipping ETF details for 30 days.")
                self.etf_info_ok = False
                self.cache["etf_info_blocked_until"] = (
                    datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec="seconds")
            else:
                log(f"  FMP etf/info {symbol}: {e}")
            return store.get(symbol)
        if d is None:
            return store.get(symbol)
        store[symbol] = {
            "er": d.get("expenseRatio"),
            "aum": d.get("assetsUnderManagement") or d.get("aum"),
            "inc": (d.get("inceptionDate") or "")[:10],
            "_fetched": now_iso(),
        }
        return store[symbol]


# --------------------------------------------------------------------------
# Massive: daily volume (grouped daily bars, one call = every ticker for a day)
# --------------------------------------------------------------------------

VOLUME_DAYS = 20        # trading days used for averages


def fetch_daily_bars(key, cache, wanted):
    """Keep the last VOLUME_DAYS trading days of bars for the wanted tickers in
    the cache. Only days not already cached are downloaded."""
    daily = cache.setdefault("daily", {})
    # drop tickers we no longer care about to keep the cache small
    for d in list(daily):
        daily[d] = {t: v for t, v in daily[d].items() if t in wanted}

    day = datetime.now(timezone.utc).date()
    calls = 0
    for _ in range(VOLUME_DAYS * 2 + 10):
        ds = day.isoformat()
        day -= timedelta(days=1)
        # stop once we hold VOLUME_DAYS trading days at or after this date
        if len([d for d in daily if daily[d] and d >= ds]) >= VOLUME_DAYS:
            break
        if datetime.fromisoformat(ds).weekday() >= 5 or ds in daily:
            continue
        url = (f"{MASSIVE_BASE}/v2/aggs/grouped/locale/us/market/stocks/{ds}?"
               + urllib.parse.urlencode({"adjusted": "true", "apiKey": key}))
        calls += 1
        try:
            data = http_json(url)
        except HttpError as e:
            log(f"  {ds}: not available yet ({e.code})")
            time.sleep(MASSIVE_DELAY)
            continue
        res = data.get("results") or []
        if res:                             # empty = holiday or not published yet
            daily[ds] = {b["T"]: [b.get("v", 0), b.get("h", 0), b.get("l", 0), b.get("c", 0)]
                         for b in res if b.get("T") in wanted}
            log(f"  {ds}: {len(daily[ds])} tickers")
        time.sleep(MASSIVE_DELAY)

    # keep only the most recent VOLUME_DAYS trading days
    for d in sorted([d for d in daily if daily[d]], reverse=True)[VOLUME_DAYS:]:
        del daily[d]
    for d in [d for d in daily if not daily[d]]:
        del daily[d]
    return calls


def volume_stats(cache, ticker):
    daily = cache.get("daily", {})
    bars = [daily[d][ticker] for d in sorted(daily, reverse=True) if ticker in daily[d]]
    bars = [b for b in bars if b[3] and b[2]]
    if not bars:
        return {}
    vols = [b[0] for b in bars]
    dollar = [b[0] * b[3] for b in bars]
    ranges = [(b[1] / b[2] - 1) * 100 for b in bars if b[2] > 0]
    return {
        "px": round(bars[0][3], 2),
        "lv": int(bars[0][0]),
        "av": int(sum(vols) / len(vols)),
        "adv": int(sum(dollar) / len(dollar)),
        "adr": round(sum(ranges) / len(ranges), 2) if ranges else None,
        "nd": len(bars),
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    load_env()
    massive_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    fmp_key = os.environ.get("FMP_API_KEY", "").strip()
    if not massive_key:
        sys.exit("MASSIVE_API_KEY is missing. Add it to .env or your environment.")
    if not fmp_key:
        log("FMP_API_KEY is missing; sector/industry details will be limited.")

    DATA.mkdir(exist_ok=True)
    cache = load_json(CACHE_FILE, {})
    overrides = load_json(OVERRIDES_FILE, {})
    aliases = {k.lower(): v for k, v in overrides.get("aliases", {}).items()}
    force_include = set(overrides.get("include", []))
    force_exclude = set(overrides.get("exclude", []))
    fixes = overrides.get("etfs", {})

    log("Downloading ticker lists from Massive (about 4 minutes on the free plan)...")
    funds = massive_list("ETF", massive_key) + massive_list("ETN", massive_key)
    stocks = massive_list("CS", massive_key) + massive_list("ADRC", massive_key)
    stock_syms = {s["ticker"]: s.get("name", "") for s in stocks}
    etf_syms = {f["ticker"]: f.get("name", "") for f in funds}

    log("Classifying funds...")
    rows = []
    for f in funds:
        t, name = f["ticker"], f.get("name", "") or ""
        if t in force_exclude:
            continue
        lev = parse_leverage(name)
        if t not in force_include:
            if lev is None or is_excluded(name):
                continue
        if lev is None:
            lev = (2.0, "Long")
        row = {
            "t": t, "n": name, "iss": issuer_of(name),
            "dir": lev[1], "lev": fmt_lev(lev[0]),
            "type": "ETN" if f.get("type") == "ETN" else "ETF",
        }
        row.update(find_underlying(name, t, stock_syms, etf_syms, aliases))
        if row["kind"] == "Single Stock" and not row.get("un"):
            row["un"] = stock_syms.get(row["u"], "")
        row.update(fixes.get(t, {}))
        rows.append(row)
    log(f"  {len(rows)} leveraged/inverse funds found")

    log("Downloading daily volume from Massive (first run about 5 minutes, then 1 call a day)...")
    wanted = {r["t"] for r in rows} | {r["u"] for r in rows if r.get("u")}
    fetch_daily_bars(massive_key, cache, wanted)

    if fmp_key:
        fmp = FMP(fmp_key, cache)
        log(f"Enriching from FMP (budget {FMP_BUDGET} calls)...")
        # single-stock profiles first, most valuable
        for sym in sorted({r["u"] for r in rows if r["kind"] == "Single Stock" and r["u"]}):
            fmp.profile(sym)
        for r in rows:
            fmp.etf_info(r["t"])
        log(f"  used {fmp.calls} FMP calls")

    profiles = cache.get("profiles", {})
    infos = cache.get("etf_info", {})
    for r in rows:
        if r["kind"] == "Single Stock":
            p = profiles.get(r["u"]) or {}
            r["un"] = p.get("name") or r.get("un", "")
            r.setdefault("sec", p.get("sec") or "Unknown")
            r.setdefault("ind", p.get("ind") or "")
            if not r["sec"]:
                r["sec"] = "Unknown"
        i = infos.get(r["t"]) or {}
        r["er"] = i.get("er")
        r["aum"] = i.get("aum")
        r["inc"] = i.get("inc") or ""
        r.update(volume_stats(cache, r["t"]))
        if r.get("u"):
            us = volume_stats(cache, r["u"])
            r["uadr"] = us.get("adr")
            r["uadv"] = us.get("adv")
        r.update(fixes.get(r["t"], {}))   # manual fixes always win

    rows.sort(key=lambda r: -(r.get("adv") or 0))
    payload = {"updated": now_iso(), "source": "Massive + Financial Modeling Prep",
               "count": len(rows), "etfs": rows}

    OUT_JSON.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    OUT_JS.write_text("window.LEVERAGE_SCOUT = " + json.dumps(payload) + ";\n", encoding="utf-8")
    CACHE_FILE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    log(f"Done. Wrote {len(rows)} funds to {OUT_JSON.relative_to(ROOT)} and {OUT_JS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
