"""
Week 2: AI Risk Analysis Layer

Takes the financial distress ratios from Week 1 (calculate_ratios.py) and feeds
them — along with several years of raw underlying fundamentals (revenue, EBITDA,
debt, cash) — to Claude, which writes a structured risk assessment per company:

    - Risk Rating       (Low / Moderate / Elevated / High)
    - Confidence Level  (Low / Medium / High, with a one-line reason)
    - Primary Driver    (what's actually causing the risk — balance sheet vs.
                          earnings vs. liquidity vs. governance)
    - Trend Context     (is it getting better or worse, and how fast)
    - Watch Trigger      (what specific event/metric would change this view —
                          this is the subscription "hook": something a paying
                          reader would want to be notified about)

This script is self-contained: it re-fetches fundamentals from EODHD itself
(rather than reading ratio_results.json), because we need several years of
history for the trend analysis, not just the latest quarter that Week 1 saved.

SETUP (one-time):
  Both API keys are read from environment variables, not hardcoded, so this
  script is safe to push to GitHub later without exposing your keys.

  In Terminal, run these two lines (replace with your real keys):
      export EODHD_API_KEY="your_eodhd_key_here"
      export ANTHROPIC_API_KEY="your_anthropic_key_here"

  These only last for your current Terminal session. To make them permanent,
  add those two lines to your ~/.zshrc file (open it with: nano ~/.zshrc),
  save, then run: source ~/.zshrc

HOW TO RUN:
    /usr/local/bin/python3 ai_risk_analysis.py
Make sure watchlist.py is in the same folder.
"""

import requests
import json
import time
import os
from watchlist import WATCHLIST

EODHD_API_KEY = os.environ.get("EODHD_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

CLAUDE_MODEL = "claude-sonnet-4-5"  # balanced cost/quality
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# How many historical quarterly periods to pull for trend context.
# EODHD typically returns several years of quarterly data; we just take
# however many periods actually exist, up to this cap, so one company having
# more history than another doesn't break anything.
MAX_HISTORY_PERIODS = 12  # roughly 3 years of quarters, if available


def safe_float(value):
    """EODHD returns many numeric fields as strings (or null). Convert safely."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def fetch_fundamentals(ticker):
    """Fetch raw fundamentals data for one ticker from EODHD."""
    url = f"https://eodhd.com/api/fundamentals/{ticker}"
    params = {"api_token": EODHD_API_KEY, "fmt": "json"}
    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"  ERROR fetching {ticker}: status {response.status_code} — {response.text}")
        return None
    return response.json()


def extract_history(data, ticker):
    """
    Build a list of historical snapshots (most recent first) covering revenue,
    EBITDA, total debt, cash, and net debt for as many quarters as are
    available, up to MAX_HISTORY_PERIODS.

    This is what lets Claude say something like "Net Debt/EBITDA has risen
    from 1.2x to 3.8x over the last 6 quarters" instead of just restating a
    single current ratio.
    """
    financials = data.get("Financials", {})
    highlights = data.get("Highlights", {})

    balance_sheet_q = financials.get("Balance_Sheet", {}).get("quarterly", {})
    income_q = financials.get("Income_Statement", {}).get("quarterly", {})

    if not balance_sheet_q or not income_q:
        print(f"  WARNING: missing balance sheet or income statement history for {ticker}")
        return []

    # Dates present in both statements, most recent first
    dates = sorted(set(balance_sheet_q.keys()) & set(income_q.keys()), reverse=True)
    dates = dates[:MAX_HISTORY_PERIODS]

    history = []
    for date in dates:
        bs = balance_sheet_q.get(date, {})
        inc = income_q.get(date, {})

        total_debt = safe_float(bs.get("shortLongTermDebtTotal"))
        cash = safe_float(bs.get("cash"))
        net_debt = safe_float(bs.get("netDebt"))
        total_revenue = safe_float(inc.get("totalRevenue"))
        ebit = safe_float(inc.get("ebit"))

        # EBITDA isn't usually broken out per-quarter in the income statement;
        # EBIT is the best quarterly proxy we have available without it.
        history.append({
            "period": date,
            "revenue": total_revenue,
            "ebit": ebit,
            "total_debt": total_debt,
            "cash": cash,
            "net_debt": net_debt,
        })

    return history


def format_history_for_prompt(history):
    """Turn the history list into a compact, readable table for the prompt."""
    if not history:
        return "No historical data available."

    def fmt(v):
        if v is None:
            return "N/A".rjust(12)
        return f"{v / 1_000_000:,.1f}".rjust(12)

    header = f"{'period':<12} | {'revenue (m)':>12} | {'EBIT (m)':>12} | {'total debt (m)':>12} | {'cash (m)':>12} | {'net debt (m)':>12}"
    lines = [header]
    for h in history:
        lines.append(
            f"{h['period']:<12} | {fmt(h['revenue'])} | {fmt(h['ebit'])} | "
            f"{fmt(h['total_debt'])} | {fmt(h['cash'])} | {fmt(h['net_debt'])}"
        )
    return "\n".join(lines)


def calculate_current_ratios(data, ticker):
    """
    Recreate the Week 1 ratio set for the most recent period, so this script
    is fully self-contained and doesn't depend on ratio_results.json existing.
    Logic mirrors calculate_ratios.py.
    """
    highlights = data.get("Highlights", {})
    financials = data.get("Financials", {})

    balance_sheet_q = financials.get("Balance_Sheet", {}).get("quarterly", {})
    income_q = financials.get("Income_Statement", {}).get("quarterly", {})

    if not balance_sheet_q or not income_q:
        return None

    most_recent_bs_date = sorted(balance_sheet_q.keys(), reverse=True)[0]
    most_recent_is_date = sorted(income_q.keys(), reverse=True)[0]

    bs = balance_sheet_q[most_recent_bs_date]
    inc = income_q[most_recent_is_date]

    total_assets = safe_float(bs.get("totalAssets"))
    total_liab = safe_float(bs.get("totalLiab"))
    total_current_assets = safe_float(bs.get("totalCurrentAssets"))
    total_current_liab = safe_float(bs.get("totalCurrentLiabilities"))
    total_equity = safe_float(bs.get("totalStockholderEquity"))
    total_debt = safe_float(bs.get("shortLongTermDebtTotal"))
    net_debt = safe_float(bs.get("netDebt"))
    retained_earnings = safe_float(bs.get("retainedEarnings"))
    total_current_assets_v = total_current_assets
    net_working_capital = None
    if total_current_assets is not None and total_current_liab is not None:
        net_working_capital = total_current_assets - total_current_liab

    ebit = safe_float(inc.get("ebit"))
    interest_expense = safe_float(inc.get("interestExpense"))
    total_revenue = safe_float(inc.get("totalRevenue"))

    ebitda = safe_float(highlights.get("EBITDA"))
    market_cap = safe_float(highlights.get("MarketCapitalization"))

    ratios = {"statement_date": most_recent_bs_date}

    ratios["current_ratio"] = round(total_current_assets / total_current_liab, 2) \
        if total_current_assets and total_current_liab else None
    ratios["debt_to_equity"] = round(total_debt / total_equity, 2) \
        if total_debt is not None and total_equity else None
    ratios["net_debt_to_ebitda"] = round(net_debt / ebitda, 2) \
        if net_debt is not None and ebitda else None
    ratios["interest_coverage"] = round(ebit / interest_expense, 2) \
        if ebit is not None and interest_expense else None

    z_inputs = [net_working_capital, total_assets, retained_earnings, ebit,
                market_cap, total_liab, total_revenue]
    if any(v is None for v in z_inputs) or total_assets == 0 or total_liab == 0:
        ratios["altman_z_score"] = None
        ratios["z_score_zone"] = "Unable to calculate"
    else:
        A = net_working_capital / total_assets
        B = retained_earnings / total_assets
        C = ebit / total_assets
        D = market_cap / total_liab
        E = total_revenue / total_assets
        z_score = 1.2 * A + 1.4 * B + 3.3 * C + 0.6 * D + 1.0 * E
        ratios["altman_z_score"] = round(z_score, 2)
        if z_score > 2.99:
            ratios["z_score_zone"] = "Safe"
        elif z_score > 1.81:
            ratios["z_score_zone"] = "Grey"
        else:
            ratios["z_score_zone"] = "Distress"

    return ratios


def build_prompt(company, ratios, history):
    """
    Construct the prompt sent to Claude. Designed for subscription-grade
    output: decisive rating, calibrated confidence, a named causal driver
    (not just a restated ratio), explicit trend direction, and a forward-
    looking trigger a paying reader would want to be alerted on.
    """
    history_table = format_history_for_prompt(history)

    prompt = f"""You are a credit/restructuring analyst writing a subscriber-facing financial distress note. Be decisive and specific — avoid vague hedging. Do not just restate the ratios; explain what is driving them and what it means.

COMPANY: {company['name']} ({company['ticker']})
CONTEXT: {company['flag_reason']}

CURRENT RATIOS (as of {ratios.get('statement_date', 'N/A')}):
- Current Ratio: {ratios.get('current_ratio')}
- Debt-to-Equity: {ratios.get('debt_to_equity')}
- Net Debt / EBITDA: {ratios.get('net_debt_to_ebitda')}
- Interest Coverage: {ratios.get('interest_coverage')}
- Altman Z-Score: {ratios.get('altman_z_score')} ({ratios.get('z_score_zone')})

HISTORICAL FUNDAMENTALS (most recent first, figures in millions, local currency):
{history_table}

NOTE ON THE ALTMAN Z-SCORE: this formula was built for industrial/manufacturing firms and does not fit banks, financial exchanges, or other firms with unusual balance sheet structures well. If this company is in such a sector, factor that into your confidence level rather than taking the Z-score at face value.

DATA QUALITY CHECK: Before writing your assessment, scan the historical fundamentals table above for any single-period move greater than 50% in a line item (total debt, cash, net debt, revenue, or EBIT) that has no clear explanation elsewhere in the data provided (e.g. no offsetting change in a related line, nothing in the company context that would account for it). If you find one:
- Do not invent a specific cause (e.g. "likely a major acquisition" or "likely a refinancing") unless the data actually supports it — an unexplained jump is exactly that, unexplained.
- Explicitly name the possibility that this is a data-quality or reporting artifact (a reclassification, restatement, or extraction error) rather than assuming it reflects a real financial event.
- Cap CONFIDENCE at Medium, and state the unexplained move itself as the reason for the lower confidence.
- Make WATCH TRIGGER about confirming or clarifying that specific figure in the next disclosure, not about a threshold that assumes the figure is already accurate.

Write your assessment in EXACTLY this structure, with these exact headers:

RISK RATING: [Low / Moderate / Elevated / High]

CONFIDENCE: [Low / Medium / High] — [one sentence explaining why, e.g. what corroborates or undermines the rating]

PRIMARY DRIVER: [1-2 sentences naming the specific causal mechanism — is this a balance sheet/solvency problem, an earnings/demand shock, a liquidity timing issue, a governance red flag, or a cost blowout? Be specific to this company's situation, not generic.]

TREND: [1-2 sentences on the direction of travel over the historical periods shown — is leverage rising or falling, is the cash position eroding, is this acute or gradual?]

WATCH TRIGGER: [1 sentence naming a specific, concrete event or metric threshold that would change this assessment — e.g. a particular ratio crossing a level, an upcoming refinancing date, a guidance update. This should be something a subscriber would want to be alerted on.]

Keep the entire response under 180 words. Do not add any other sections, preamble, or sign-off."""

    return prompt


def call_claude(prompt):
    """Send the prompt to the Claude API and return the text response."""
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = requests.post(ANTHROPIC_API_URL, headers=headers, json=body)
    if response.status_code != 200:
        print(f"  ERROR calling Claude API: status {response.status_code} — {response.text}")
        return None

    data = response.json()
    # data["content"] is a list of blocks; for a plain text reply there's one
    # block of type "text"
    text_blocks = [block["text"] for block in data.get("content", []) if block.get("type") == "text"]
    return "\n".join(text_blocks)


def main():
    if not EODHD_API_KEY:
        print("ERROR: EODHD_API_KEY environment variable is not set. See the setup instructions at the top of this file.")
        return
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set. See the setup instructions at the top of this file.")
        return

    print(f"Running AI risk analysis for {len(WATCHLIST)} companies...\n")
    all_results = []

    for company in WATCHLIST:
        ticker = company["ticker"]
        print(f"Processing {ticker} ({company['name']})...")

        data = fetch_fundamentals(ticker)
        if data is None:
            continue

        ratios = calculate_current_ratios(data, ticker)
        if ratios is None:
            print(f"  WARNING: could not calculate ratios for {ticker}, skipping AI analysis")
            continue

        history = extract_history(data, ticker)
        prompt = build_prompt(company, ratios, history)

        print("  Calling Claude API for risk write-up...")
        analysis_text = call_claude(prompt)

        result = {
            "ticker": ticker,
            "name": company["name"],
            "flag_reason": company["flag_reason"],
            "ratios": ratios,
            "history_periods_used": len(history),
            "ai_analysis": analysis_text,
        }
        all_results.append(result)

        time.sleep(1)  # be polite to both APIs

    print("\n" + "=" * 90)
    print("AI RISK ANALYSIS RESULTS")
    print("=" * 90)
    for r in all_results:
        print(f"\n{r['ticker']} — {r['name']}")
        print(f"({r['history_periods_used']} historical periods used)")
        print("-" * 90)
        if r["ai_analysis"]:
            print(r["ai_analysis"])
        else:
            print("  (no analysis returned — check error above)")

    with open("ai_risk_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print("\n\nSaved full results to ai_risk_results.json")


if __name__ == "__main__":
    main()
