"""
fetch_scores.py
Runs via GitHub Actions every 30 min during market hours.
Fetches daily + weekly time_series from Twelve Data for all tickers,
computes BBW(20), ATR(14), RSI(14) client-side, writes scores.json.
"""

import os, json, time, math, requests
from datetime import datetime, timezone

TD_KEY  = os.environ["TD_KEY"]
BASE    = "https://api.twelvedata.com"
BATCH   = 8
DELAY   = 2.5   # seconds between batches (keeps under 55 calls/min)

TICKERS = [
    "AA","AAL","AAPL","ABBV","ABCL","ABT","ABTC","ABVX","ACHR","ACN",
    "ADP","AG","AGI","AMC","AMD","AMPX","AMSC","AMZN","APA","APH",
    "APLD","ARM","ASTS","AVAV","AVGO","AZN","B","BA","BABA","BAC",
    "BB","BBAI","BBY","BE","BIDU","BMNR","BMY","BP","BSX","BTBT",
    "BTDR","BTG","BULL","BX","C","CAG","CCJ","CCL","CDE","CDNS",
    "CE","CELH","CF","CHTR","CIFR","CLF","CLOV","CLSK","CLX","CMCSA",
    "CMG","CNC","CNI","CNQ","COF","COHR","COIN","COP","CORZ","CPNG",
    "CPRI","CRCL","CRDO","CRM","CRML","CRWD","CRWV","CSCO","CSX","CTRA",
    "CVE","CVI","CVNA","CVS","CVX","DAL","DELL","DINO","DIS","DOW",
    "DUOL","DVN","EH","ELF","ENPH","ENVX","EOSE","EQT","EQX","ET",
    "EXE","F","FANG","FCX","FIG","FLEX","FLY","FRMI","FSLR","FSLY",
    "FTAI","GE","GFS","GIS","GLW","GLXY","GM","GME","GOOG","GOOGL",
    "GRPN","GS","GSK","GT","HAL","HCA","HD","HIMS","HIVE","HL",
    "HON","HOOD","HPE","HPQ","HUM","HUT","IAG","IBM","IBRX","INDI",
    "INTC","IONQ","IQ","IREN","JBLU","JD","JMIA","JNJ","JOBY","JPM",
    "KGC","KHC","KLAR","KMI","KO","LAC","LAES","LCID","LI","LLY",
    "LMND","LNG","LRCX","LULU","LUNR","LUV","LYV","M","MA","MARA",
    "MCD","MCHP","MDLZ","MDT","META","MO","MOS","MP","MPC","MRK",
    "MRNA","MRVL","MS","MSFT","MSTR","MU","NBIS","NEE","NEM","NET",
    "NG","NIO","NKE","NNE","NOK","NOW","NTLA","NTR","NU","NVDA",
    "NVO","NVTS","NXPI","OKLO","ON","ONDS","OPEN","ORCL","OSCR","OWL",
    "OXY","PAAS","PANW","PATH","PBR","PCG","PDD","PEP","PFE","PG",
    "PGR","PL","PLTR","PLUG","PSX","PTON","PYPL","PZZA","QBTS","QCOM",
    "QS","QUBT","QXO","RBLX","RCL","RDDT","RDW","RGTI","RIG","RIOT",
    "RIVN","RKLB","RKT","RR","RTX","RUN","SA","SATS","SBET","SBUX",
    "SEDG","SHOP","SIRI","SLB","SMCI","SMR","SNAP","SNDK","SNOW","SOFI",
    "SOUN","SPOT","SRAD","STM","STNE","STX","T","TDOC","TEAM","TEM",
    "TER","TEVA","TFC","TIGR","TJX","TLRY","TMC","TMUS","TSCO","TSLA",
    "TSM","TTD","TTWO","TWLO","TXN","U","UAL","UAMY","UBER","UEC",
    "UMC","UNH","UNP","UPS","UPST","USAR","UUUU","UWMC","V","VALE",
    "VG","VIAV","VLO","VNET","VRT","VZ","VZLA","WDC","WEN","WFC",
    "WMT","WPM","WULF","XOM","XYL","YPF","ZETA","ZIM","ZM",
]

# ── Indicator calculations ────────────────────────────────────────────────────

def calc_bbw(closes, period=20, lookback=252):
    arr = []
    for i in range(period - 1, len(closes)):
        sl = closes[i - period + 1 : i + 1]
        m  = sum(sl) / period
        sd = math.sqrt(sum((v - m) ** 2 for v in sl) / period)
        arr.append((4 * sd) / m if m else 0)
    if not arr:
        return None
    cur     = arr[-1]
    window  = arr[-lookback:]
    min_bbw = min(window)
    return {"currentBBW": cur, "minBBW": min_bbw, "relativeBBW": cur / min_bbw if min_bbw else 0}


def calc_atr(highs, lows, closes, period=14):
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        ))
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


def calc_rsi(closes, period=14):
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    if len(changes) < period:
        return None, None
    ag = sum(c for c in changes[:period] if c > 0) / period
    al = sum(-c for c in changes[:period] if c < 0) / period
    rsis = []
    for i in range(period, len(changes)):
        ag = (ag * (period - 1) + max(changes[i], 0)) / period
        al = (al * (period - 1) + max(-changes[i], 0)) / period
        rsis.append(100 if al == 0 else 100 - (100 / (1 + ag / al)))
    if not rsis:
        return None, None
    current_rsi = rsis[-1]
    desc = list(reversed(rsis))
    last_signal = None
    for i in range(len(desc) - 1):
        if desc[i] >= 70 and desc[i + 1] < 70:
            last_signal = {"signal": "OB", "barsAgo": i}
            break
        if desc[i] <= 30 and desc[i + 1] > 30:
            last_signal = {"signal": "OS", "barsAgo": i}
            break
    return current_rsi, last_signal


def score_from_vals(values, lookback=252):
    """values = list of dicts (newest-first from API). Reverse before processing."""
    v      = list(reversed(values))
    closes = [float(x["close"]) for x in v]
    highs  = [float(x["high"])  for x in v]
    lows   = [float(x["low"])   for x in v]
    price  = closes[-1]
    bb     = calc_bbw(closes, 20, lookback)
    atr    = calc_atr(highs, lows, closes, 14)
    if not bb or not atr:
        raise ValueError("insufficient data")
    nm    = bb["currentBBW"] / (atr / price)
    score = 100 - (bb["relativeBBW"] * nm)
    return {
        "score":         round(score, 2),
        "currentBBW":   round(bb["currentBBW"], 6),
        "minBBW":       round(bb["minBBW"], 6),
        "atr":          round(atr, 4),
        "price":        round(price, 2),
        "relativeBBW":  round(bb["relativeBBW"], 4),
        "normalizedBBW":round(nm, 4),
    }

# ── API helpers ───────────────────────────────────────────────────────────────

def td_fetch(url, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            d = r.json()
            if d.get("status") == "error":
                msg = d.get("message", "API error")
                if "limit" in msg.lower() or "minute" in msg.lower():
                    wait = 6 * (attempt + 1)
                    print(f"  Rate limited, waiting {wait}s…")
                    time.sleep(wait)
                    continue
                raise ValueError(msg)
            return d
        except Exception as e:
            if attempt == retries:
                raise
            time.sleep(3 * (attempt + 1))


def norm_batch(data, syms):
    return {syms[0]: data} if len(syms) == 1 else data


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    scores = {}
    errors = {}
    total  = len(TICKERS)

    for i, batch in enumerate(chunks(TICKERS, BATCH)):
        sym_str = ",".join(batch)
        print(f"Batch {i+1}/{math.ceil(total/BATCH)}: {sym_str}")

        try:
            day_data = td_fetch(
                f"{BASE}/time_series?symbol={sym_str}&interval=1day&outputsize=350&apikey={TD_KEY}"
            )
            wk_data  = td_fetch(
                f"{BASE}/time_series?symbol={sym_str}&interval=1week&outputsize=310&apikey={TD_KEY}"
            )
        except Exception as e:
            print(f"  Batch fetch failed: {e} — skipping batch")
            for s in batch:
                errors[s] = str(e)
            time.sleep(DELAY)
            continue

        day_norm = norm_batch(day_data, batch)
        wk_norm  = norm_batch(wk_data,  batch)

        for sym in batch:
            try:
                dd = day_norm.get(sym, {})
                wd = wk_norm.get(sym,  {})
                if dd.get("status") == "error":
                    raise ValueError(dd.get("message", "day error"))
                if wd.get("status") == "error":
                    raise ValueError(wd.get("message", "week error"))
                day_vals = dd.get("values", [])
                wk_vals  = wd.get("values", [])
                if len(day_vals) < 50:
                    raise ValueError(f"only {len(day_vals)} daily bars")
                if len(wk_vals)  < 50:
                    raise ValueError(f"only {len(wk_vals)} weekly bars")

                st = score_from_vals(day_vals, 252)
                lt = score_from_vals(wk_vals,  252)

                day_closes = [float(x["close"]) for x in reversed(day_vals)]
                rsi, last_signal = calc_rsi(day_closes, 14)

                scores[sym] = {
                    "st":         st,
                    "lt":         lt,
                    "rsi":        round(rsi, 2) if rsi is not None else None,
                    "lastSignal": last_signal,
                }
                print(f"  {sym}: ST={st['score']:.1f}  LT={lt['score']:.1f}  RSI={rsi:.1f if rsi else '—'}")

            except Exception as e:
                print(f"  {sym} error: {e}")
                errors[sym] = str(e)

        time.sleep(DELAY)

    # ── Fetch earnings from Yahoo Finance (no key, no rate limit) ───────────────
    earnings = {}
    print("\nFetching earnings calendar from Yahoo Finance…")
    from datetime import date as date_cls
    today = date_cls.today()
    ticker_set = set(TICKERS)
    for sym in TICKERS:
        try:
            url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}?modules=calendarEvents"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if not r.ok:
                continue
            data = r.json()
            dates = data.get("quoteSummary", {}).get("result", [{}])[0].get("calendarEvents", {}).get("earnings", {}).get("earningsDate", [])
            if not dates:
                continue
            candidates = []
            for e in dates:
                raw = e.get("raw")
                if raw is None:
                    continue
                import datetime
                d = datetime.date.fromtimestamp(raw)
                days = (d - today).days
                candidates.append({"date": str(d), "days": days})
            if candidates:
                # Pick nearest upcoming, or most recent past
                upcoming = [c for c in candidates if c["days"] >= 0]
                pick = min(upcoming, key=lambda x: x["days"]) if upcoming else min(candidates, key=lambda x: abs(x["days"]))
                earnings[sym] = pick["date"]
                print(f"  {sym}: {pick['date']} ({pick['days']}d)")
        except Exception as e:
            pass  # silently skip — static table is fallback
        time.sleep(0.1)
    print(f"  Earnings loaded for {len(earnings)} tickers")

    output = {
        "updated":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count":    len(scores),
        "scores":   scores,
        "earnings": {sym: v["date"] for sym, v in earnings.items()},
        "errors":   errors,
    }

    with open("scores.json", "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"\nDone — {len(scores)} scores written, {len(errors)} errors.")
    if errors:
        print("Errors:", list(errors.keys()))


if __name__ == "__main__":
    main()
