"""
generate_daily_note.py
Runs at 9:00am ET Mon-Fri via GitHub Actions.
Reads scores.json + active portfolio from Google Sheet.
Calls GitHub Models (free, uses GITHUB_TOKEN — no API key needed).
Generates daily note in Strazza's voice.
"""

import json, os, requests, csv, io
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────
SCORES_FILE  = "scores.json"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
PUB_BASE     = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRnBssDB2zK9HpOp9kb0zYGWAjlhR-GWxSKpqag06rzDm9myu_rN_-wXmGhcFxVchwqXr-jatRToc2b/pub"
OPEN_CSV     = f"{PUB_BASE}?gid=975618056&single=true&output=csv"

# ── Load scores.json ────────────────────────────────────────────────────────
def load_scores():
    try:
        with open(SCORES_FILE) as f:
            data = json.load(f)
        return data.get("scores", {})
    except Exception as e:
        print(f"Error loading scores.json: {e}")
        return {}

# ── Load active portfolio ───────────────────────────────────────────────────
def load_portfolio():
    try:
        r = requests.get(OPEN_CSV, timeout=15)
        r.raise_for_status()
        reader = csv.reader(io.StringIO(r.text))
        positions = []
        for row in reader:
            if len(row) < 9: continue
            ticker = (row[1] or "").strip().upper()
            if not ticker or not ticker.replace(".", "").isalpha(): continue
            if ticker in ["TICKER","STOCK","NAME","ENTRY"]: continue
            entry_date = (row[0] or "").strip()
            if not entry_date or "/" not in entry_date: continue
            try:
                entry = float(str(row[8]).replace("$","").replace(",","").strip())
                if entry <= 0: continue
            except: continue
            try: max_pct = float(str(row[10] if len(row)>10 else 0).replace("%","").strip())
            except: max_pct = 0
            theme   = (row[5] if len(row) > 5 else "").strip()
            contract= (row[7] if len(row) > 7 else "").strip()
            doubled = (row[11] if len(row) > 11 else "").strip().upper() == "YES"
            positions.append({
                "ticker": ticker, "name": (row[2] or ticker).strip(),
                "theme": theme, "entry": entry, "max_pct": max_pct,
                "contract": contract, "entry_date": entry_date, "doubled": doubled,
            })
        return positions
    except Exception as e:
        print(f"Error loading portfolio: {e}")
        return []

# ── Regime helper ───────────────────────────────────────────────────────────
def get_regime(d):
    rsi = d.get("rsi")
    sig = d.get("lastSignal", {})
    if not sig or rsi is None: return "Neutral"
    if sig.get("signal") == "OB" and rsi >= 50: return "Bullish"
    if sig.get("signal") == "OS" and rsi < 50:  return "Bearish"
    return "Neutral"

# ── Build context string for the prompt ────────────────────────────────────
def build_context(scores, portfolio):
    hot  = sorted([(s,d) for s,d in scores.items() if d.get("st",{}).get("score",0)>=90],
                   key=lambda x: x[1]["st"]["score"], reverse=True)
    warm = sorted([(s,d) for s,d in scores.items() if 75<=d.get("st",{}).get("score",0)<90],
                   key=lambda x: x[1]["st"]["score"], reverse=True)
    bullish_hot = [(s,d) for s,d in hot if get_regime(d)=="Bullish"]

    port_enriched = []
    for p in portfolio:
        sq = scores.get(p["ticker"], {})
        port_enriched.append({
            **p,
            "st":     sq.get("st",{}).get("score"),
            "lt":     sq.get("lt",{}).get("score"),
            "regime": get_regime(sq),
        })

    still_on  = [p for p in port_enriched if p["st"] and p["st"]>=75 and p["regime"]=="Bullish" and not p["doubled"]]
    double_dn = [p for p in port_enriched if p["st"] and p["st"]>=90 and p["regime"]=="Bullish" and p["doubled"]]

    hot_lines  = "\n".join([f"  {s}: Daily={d['st']['score']:.1f}, Weekly={d.get('lt',{}).get('score',0):.1f}, Regime={get_regime(d)}" for s,d in hot[:12]])
    warm_lines = "\n".join([f"  {s}: Daily={d['st']['score']:.1f}, Regime={get_regime(d)}" for s,d in warm[:8]])
    port_lines = "\n".join([
        f"  {p['ticker']} ({p['theme']}): Entry=${p['entry']:.2f}, Max={p['max_pct']:.0f}%, Squeeze={p['st'] or 'N/A':.1f}, Regime={p['regime']}, {'SOLD 50% AT 2x' if p['doubled'] else 'FULL POSITION'}"
        for p in port_enriched
    ])
    dd_lines   = "\n".join([f"  {p['ticker']}: Squeeze={p['st']:.1f}, Regime={p['regime']} — already sold 50% at 2x" for p in double_dn])

    return hot_lines, warm_lines, port_lines, dd_lines, len(hot), len(warm), len(scores), still_on, double_dn

# ── Call GitHub Models API ──────────────────────────────────────────────────
def generate_note(hot_lines, warm_lines, port_lines, dd_lines, hot_count, warm_count, total, still_on, double_dn):
    today = datetime.now().strftime("%A, %B %d, %Y")

    system_prompt = """You are Steve Strazza from All Star Charts. Write exactly like him:
- High energy, casual, like texting a trade idea at 7am
- Contrarian hook to open
- Top-down always: macro → sector → individual names
- Bold the single most important sentence with **bold**
- No bullet points — flowing paragraphs only
- No sign-off, no name at the end
- Sentence case, not Title Case
- No "very", no passive voice, no caveats
- Use $ prefix on tickers: $NVDA, $TSLA
- 400-550 words
- Signature phrases used organically: "You gotta be kidding me", "Here's your cheat code", "Risk is on. Full stop.", "That's leadership.", "The market is telling us something. Are we listening?", "And the bears? They've got nothing."
- Never use the same opening twice"""

    user_prompt = f"""Today is {today}. Write the daily pre-market note for Breakout Multiplier members.

DATA:

HOT squeeze tickers (daily score ≥90) — {hot_count} total:
{hot_lines}

WARM squeeze tickers (75-90) — {warm_count} total:
{warm_lines}

Active portfolio positions:
{port_lines}

Double-down candidates (already sold 50% at 2x, squeeze still HOT):
{dd_lines if dd_lines else "None today"}

Total universe tracked: {total} tickers

Write the note covering:
1. Hook — what the squeeze data is telling us right now, contrarian angle
2. Market overview — what {hot_count} HOT setups out of {total} means for risk appetite
3. Top 2-3 HOT setups — pick ones that tell a story together (theme, rotation)
4. Portfolio update — which positions are still actionable for late entries, and any double-down alerts
5. What to watch today — forward-looking close

Make it fresh, different from yesterday, real conviction."""

    response = requests.post(
        "https://models.inference.ai.azure.com/chat/completions",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "max_tokens": 800,
            "temperature": 0.9,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print("Loading scores.json...")
    scores = load_scores()
    print(f"  {len(scores)} tickers loaded")

    print("Loading active portfolio...")
    portfolio = load_portfolio()
    print(f"  {len(portfolio)} positions loaded")

    print("Building context...")
    hot_lines, warm_lines, port_lines, dd_lines, hot_count, warm_count, total, still_on, double_dn = build_context(scores, portfolio)
    print(f"  HOT: {hot_count}, WARM: {warm_count}, Portfolio: {len(portfolio)}")

    print("Calling GitHub Models (gpt-4o)...")
    note_text = generate_note(hot_lines, warm_lines, port_lines, dd_lines, hot_count, warm_count, total, still_on, double_dn)
    print("  Note generated")

    hot  = [s for s,d in scores.items() if d.get("st",{}).get("score",0)>=90]
    warm = [s for s,d in scores.items() if 75<=d.get("st",{}).get("score",0)<90]

    output = {
        "date":            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "display_date":    datetime.now().strftime("%A, %B %d, %Y"),
        "note":            note_text,
        "hot_count":       len(hot),
        "warm_count":      len(warm),
        "portfolio_count": len(portfolio),
    }

    with open("daily_note.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"Done — daily_note.json written")
    print("\n--- PREVIEW ---")
    print(note_text[:500])

if __name__ == "__main__":
    main()
