"""
generate_daily_note.py
Runs at 9:00am ET Mon-Fri via GitHub Actions.
Reads scores.json + active portfolio from Google Sheet.
Generates daily note in Strazza's voice — no API key needed.
"""

import json, os, requests, csv, io, random
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────
SCORES_FILE = "scores.json"
PUB_BASE    = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRnBssDB2zK9HpOp9kb0zYGWAjlhR-GWxSKpqag06rzDm9myu_rN_-wXmGhcFxVchwqXr-jatRToc2b/pub"
OPEN_CSV    = f"{PUB_BASE}?gid=975618056&single=true&output=csv"

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
            theme = (row[5] if len(row) > 5 else "").strip()
            contract = (row[7] if len(row) > 7 else "").strip()
            doubled = (row[11] if len(row) > 11 else "").strip().upper() == "YES"
            positions.append({
                "ticker": ticker,
                "name": (row[2] or ticker).strip(),
                "theme": theme,
                "entry": entry,
                "max_pct": max_pct,
                "contract": contract,
                "entry_date": entry_date,
                "doubled": doubled,
            })
        return positions
    except Exception as e:
        print(f"Error loading portfolio: {e}")
        return []

# ── Regime helper ───────────────────────────────────────────────────────────
def get_regime(score_data):
    rsi = score_data.get("rsi")
    sig = score_data.get("lastSignal", {})
    if not sig or rsi is None: return "Neutral"
    if sig.get("signal") == "OB" and rsi >= 50: return "Bullish"
    if sig.get("signal") == "OS" and rsi < 50:  return "Bearish"
    return "Neutral"

def bars_ago_str(sig):
    if not sig: return ""
    b = sig.get("barsAgo", 0)
    return "today" if b == 0 else f"{b}d ago"

# ── Build note ──────────────────────────────────────────────────────────────
def build_note(scores, portfolio):
    today = datetime.now().strftime("%A, %B %d, %Y")
    dow   = datetime.now().strftime("%A")

    # Categorize squeeze tickers
    hot  = [(s, d) for s, d in scores.items() if d.get("st", {}).get("score", 0) >= 90]
    warm = [(s, d) for s, d in scores.items() if 75 <= d.get("st", {}).get("score", 0) < 90]
    hot.sort(key=lambda x: x[1]["st"]["score"], reverse=True)
    warm.sort(key=lambda x: x[1]["st"]["score"], reverse=True)

    bullish_hot = [(s, d) for s, d in hot if get_regime(d) == "Bullish"]
    total = len(scores)
    hot_pct = round(len(hot) / total * 100) if total else 0
    warm_pct = round(len(warm) / total * 100) if total else 0

    # Portfolio enriched with squeeze data
    port_enriched = []
    for p in portfolio:
        sq = scores.get(p["ticker"], {})
        st_score = sq.get("st", {}).get("score")
        lt_score = sq.get("lt", {}).get("score")
        rsi = sq.get("rsi")
        regime = get_regime(sq)
        port_enriched.append({**p, "st": st_score, "lt": lt_score, "rsi": rsi, "regime": regime})

    # Actionable: still HOT or WARM + regime Bullish + not yet sold 50%
    still_on  = [p for p in port_enriched if p["st"] and p["st"] >= 75 and p["regime"] == "Bullish" and not p["doubled"]]
    double_dn = [p for p in port_enriched if p["st"] and p["st"] >= 90 and p["regime"] == "Bullish" and p["doubled"]]
    
    # Pick top HOT setups for the note (top 5 bullish regime)
    featured = bullish_hot[:5] if bullish_hot else hot[:5]

    # ── Market overview ─────────────────────────────────────────────────────
    if hot_pct >= 40:
        market_tone = "compression is building everywhere you look"
        risk_tone   = "Risk is on. Full stop."
    elif hot_pct >= 25:
        market_tone = "the squeeze is building in pockets — not everywhere, but in the right places"
        risk_tone   = "The market is telling us something. Are we listening?"
    else:
        market_tone = "the squeeze setups are thinning out — this is a market that wants to see more before it commits"
        risk_tone   = "Patience here. Let the setups come to you."

    # ── Write the note ──────────────────────────────────────────────────────
    lines = []

    # Hook
    hook_options = [
        f"{len(hot)} tickers sitting in a HOT squeeze right now. That's {hot_pct}% of everything we track. You gotta be kidding me.",
        f"Happy {dow}. Let's get into it — because the squeeze data this morning is hard to ignore.",
        f"Here's what the data is saying this morning: {hot_pct}% of our universe is in a HOT squeeze. That's not noise. That's a signal.",
        f"The market doesn't care what you think. It only cares what it's doing. And right now, it's squeezing — hard.",
    ]
    lines.append(random.choice(hook_options))
    lines.append("")

    # Market overview
    lines.append(f"Across the {total} names we track, {market_tone}. **{len(hot)} are HOT (squeeze score ≥90) and {len(warm)} are WARM (75–90) — that's {hot_pct + warm_pct}% of the universe building compression right now.** {risk_tone} When this many setups are coiling at the same time, the question isn't whether something moves — it's which ones you're positioned in when they do.")
    lines.append("")

    # Featured HOT setups
    if featured:
        lines.append("Here's what's standing out on the HOT list this morning.")
        lines.append("")
        for sym, d in featured[:3]:
            st  = d.get("st", {}).get("score", 0)
            lt  = d.get("lt", {}).get("score", 0)
            rsi = d.get("rsi", 0)
            reg = get_regime(d)
            sig = d.get("lastSignal", {})
            ago = bars_ago_str(sig)
            regime_str = f"regime is {reg}" + (f" ({ago})" if ago else "")

            setup_comments = [
                f"$**{sym}** is printing a daily squeeze score of {st:.1f} with the weekly at {lt:.1f}. RSI sitting at {rsi:.1f}, {regime_str}. The compression here is real — this is the kind of coil that precedes a move.",
                f"$**{sym}** — daily squeeze at {st:.1f}, weekly at {lt:.1f}, RSI {rsi:.1f}. {regime_str.capitalize()}. It doesn't get cleaner than this.",
                f"Look at $**{sym}**. Daily squeeze {st:.1f}, weekly {lt:.1f}. RSI at {rsi:.1f} and the {regime_str}. That's leadership. That's what you want to see.",
            ]
            lines.append(random.choice(setup_comments))
            lines.append("")

    # Actionable positions
    if still_on:
        lines.append("Now let's talk portfolio — specifically, who still has gas in the tank for members who haven't pulled the trigger yet.")
        lines.append("")
        for p in still_on[:3]:
            st_str  = f"{p['st']:.1f}" if p['st'] else "N/A"
            rsi_str = f"{p['rsi']:.1f}" if p['rsi'] else "N/A"
            actionable_comments = [
                f"$**{p['ticker']}** ({p['theme']}) entered at ${p['entry']:.2f} — still HOT with a squeeze score of {st_str} and RSI at {rsi_str}. Regime is {p['regime']}. If you missed the initial entry this one is still actionable. The setup hasn't broken down.",
                f"$**{p['ticker']}** is still in play. Squeeze at {st_str}, RSI {rsi_str}, {p['regime']} regime. Entry was ${p['entry']:.2f} — the compression is still building. Not too late.",
                f"Members who passed on $**{p['ticker']}** — the squeeze score is {st_str} and regime is still {p['regime']}. The original thesis is intact. ${p['entry']:.2f} entry, and the setup is tighter now than when we flagged it.",
            ]
            lines.append(random.choice(actionable_comments))
            lines.append("")
    else:
        lines.append("The active positions that are still squeezing have already moved — respect those stops and let them run. No chasing here.")
        lines.append("")

    # Double-down alerts
    if double_dn:
        lines.append("Here's your cheat code for today — the names where we've already banked half at 2x and the squeeze is still screaming HOT. Those are your double-down candidates.")
        lines.append("")
        for p in double_dn[:2]:
            st_str = f"{p['st']:.1f}" if p['st'] else "N/A"
            lines.append(f"$**{p['ticker']}** — already sold 50% at 2x, squeeze score is {st_str}, regime {p['regime']}. The remaining position has room. This is the kind of setup where you add, not reduce.")
            lines.append("")

    # So-what close
    close_options = [
        f"Watch how the HOT names react at the open. A squeeze coiling this tight either breaks out hard or resolves with a flush. Either way — know your levels before the bell.",
        f"Let the market show its hand at the open. The squeeze is wound up. Stay with the names that are leading. Cut what's lagging. That's the game today.",
        f"The setups are there. The compression is real. Now we let price do the talking. Watch the breakouts — and more importantly, watch what holds.",
    ]
    lines.append(random.choice(close_options))

    return "\n".join(lines)

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print("Loading scores.json...")
    scores = load_scores()
    print(f"  {len(scores)} tickers loaded")

    print("Loading active portfolio...")
    portfolio = load_portfolio()
    print(f"  {len(portfolio)} positions loaded")

    hot  = [(s, d) for s, d in scores.items() if d.get("st", {}).get("score", 0) >= 90]
    warm = [(s, d) for s, d in scores.items() if 75 <= d.get("st", {}).get("score", 0) < 90]

    print("Generating note...")
    note_text = build_note(scores, portfolio)

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

    print(f"Done — daily_note.json written ({len(note_text)} chars)")
    print("\n--- PREVIEW ---")
    print(note_text[:600])

if __name__ == "__main__":
    main()
