"""
Step 3: Distress Ratio Calculator (Week 1 core deliverable)

Pulls fundamentals for every company in the watchlist and calculates a set of
financial distress / health ratios used in credit and restructuring analysis:

  - Current Ratio          : liquidity (can short-term obligations be covered?)
  - Debt-to-Equity         : leverage
  - Net Debt / EBITDA       : how many years of earnings to clear debt
  - Interest Coverage Ratio : EBIT / Interest Expense (can earnings cover debt cost?)
  - Altman Z-Score (proxy)  : composite distress score using public-company formula

Altman Z-Score formula used (original 1968 model, for public manufacturing/
general companies):
    Z = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E
    A = Working Capital / Total Assets
    B = Retained Earnings / Total Assets
    C = EBIT / Total Assets
    D = Market Value of Equity / Total Liabilities
    E = Sales / Total Assets

Z > 2.99  -> "Safe" zone
1.81-2.99 -> "Grey" zone (some distress risk)
Z < 1.81  -> "Distress" zone

NOTE: This formula was built for industrial/manufacturing firms. It's a widely
used screening heuristic, not a precise predictor for every sector (e.g. banks,
financial firms, and exchange operators like ASX Ltd don't fit its assumptions
well) — worth flagging this limitation explicitly in any write-up of results.

SETUP (one-time):
  The EODHD API key is read from an environment variable, not hardcoded, so
  this script is safe to push to GitHub later without exposing your key.

  In Terminal, run this line (replace with your real key):
      export EODHD_API_KEY="your_eodhd_key_here"

  This only lasts for your current Terminal session. To make it permanent,
  add that line to your ~/.zshrc file (open it with: nano ~/.zshrc),
  save, then run: source ~/.zshrc

HOW TO RUN:
    /usr/local/bin/python3 calculate_ratios.py
Make sure watchlist.py is in the same folder.
"""

import requests
import json
import time
import os
from watchlist import WATCHLIST

API_KEY = os.environ.get("EODHD_API_KEY")


def fetch_fundamentals(ticker):
    """Fetch raw fundamentals data for one ticker from EODHD."""
    url = f"https://eodhd.com/api/fundamentals/{ticker}"
    params = {"api_token": API_KEY, "fmt": "json"}
    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"  ERROR fetching {ticker}: status {response.status_code} — {response.text}")
        return None
    return response.json()


def safe_float(value):
    """EODHD returns many numeric fields as strings (or null). Convert safely."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def calculate_ratios(data, ticker):
    """Given raw fundamentals JSON, calculate the distress ratio set."""
    highlights = data.get("Highlights", {})
    financials = data.get("Financials", {})

    balance_sheet_q = financials.get("Balance_Sheet", {}).get("quarterly", {})
    income_q = financials.get("Income_Statement", {}).get("quarterly", {})

    if not balance_sheet_q or not income_q:
        print(f"  WARNING: missing balance sheet or income statement data for {ticker}")
        return None

    most_recent_bs_date = sorted(balance_sheet_q.keys(), reverse=True)[0]
    most_recent_is_date = sorted(income_q.keys(), reverse=True)[0]

    bs = balance_sheet_q[most_recent_bs_date]
    inc = income_q[most_recent_is_date]

    # --- Pull raw figures ---
    total_assets = safe_float(bs.get("totalAssets"))
    total_liab = safe_float(bs.get("totalLiab"))
    total_current_assets = safe_float(bs.get("totalCurrentAssets"))
    total_current_liab = safe_float(bs.get("totalCurrentLiabilities"))
    total_equity = safe_float(bs.get("totalStockholderEquity"))
    total_debt = safe_float(bs.get("shortLongTermDebtTotal"))
    net_debt = safe_float(bs.get("netDebt"))
    retained_earnings = safe_float(bs.get("retainedEarnings"))
    net_working_capital = safe_float(bs.get("netWorkingCapital"))
    # EODHD doesn't always populate netWorkingCapital directly — fall back to
    # calculating it ourselves from current assets/liabilities, which we already have.
    if net_working_capital is None and total_current_assets is not None and total_current_liab is not None:
        net_working_capital = total_current_assets - total_current_liab

    ebit = safe_float(inc.get("ebit"))
    interest_expense = safe_float(inc.get("interestExpense"))
    total_revenue = safe_float(inc.get("totalRevenue"))

    ebitda = safe_float(highlights.get("EBITDA"))
    market_cap = safe_float(highlights.get("MarketCapitalization"))

    ratios = {
        "ticker": ticker,
        "statement_date": most_recent_bs_date,
    }

    # --- Current Ratio ---
    if total_current_assets and total_current_liab:
        ratios["current_ratio"] = round(total_current_assets / total_current_liab, 2)
    else:
        ratios["current_ratio"] = None

    # --- Debt-to-Equity ---
    if total_debt is not None and total_equity:
        ratios["debt_to_equity"] = round(total_debt / total_equity, 2)
    else:
        ratios["debt_to_equity"] = None

    # --- Net Debt / EBITDA ---
    if net_debt is not None and ebitda:
        ratios["net_debt_to_ebitda"] = round(net_debt / ebitda, 2)
    else:
        ratios["net_debt_to_ebitda"] = None

    # --- Interest Coverage Ratio ---
    if ebit is not None and interest_expense:
        ratios["interest_coverage"] = round(ebit / interest_expense, 2)
    else:
        ratios["interest_coverage"] = None

    # --- Altman Z-Score (proxy, using most recent quarter as snapshot) ---
    z_inputs = {
        "net_working_capital": net_working_capital,
        "total_assets": total_assets,
        "retained_earnings": retained_earnings,
        "ebit": ebit,
        "market_cap": market_cap,
        "total_liab": total_liab,
        "total_revenue": total_revenue,
    }
    missing_inputs = [name for name, value in z_inputs.items() if value is None]

    if missing_inputs:
        ratios["altman_z_score"] = None
        ratios["z_score_zone"] = "Unable to calculate"
        ratios["z_score_missing_inputs"] = missing_inputs
    else:
        try:
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
            ratios["z_score_missing_inputs"] = []
        except ZeroDivisionError:
            ratios["altman_z_score"] = None
            ratios["z_score_zone"] = "Unable to calculate (division by zero)"
            ratios["z_score_missing_inputs"] = []

    return ratios


def main():
    if not API_KEY:
        print("ERROR: EODHD_API_KEY environment variable is not set. See the setup instructions at the top of this file.")
        return

    print(f"Calculating distress ratios for {len(WATCHLIST)} companies...\n")
    all_results = []

    for company in WATCHLIST:
        ticker = company["ticker"]
        print(f"Fetching {ticker} ({company['name']})...")
        data = fetch_fundamentals(ticker)

        if data is None:
            continue

        ratios = calculate_ratios(data, ticker)
        if ratios:
            ratios["name"] = company["name"]
            ratios["flag_reason"] = company["flag_reason"]
            all_results.append(ratios)

        time.sleep(1)  # be polite to the API, avoid rate limit issues

    print("\n" + "=" * 90)
    print("RESULTS")
    print("=" * 90)
    for r in all_results:
        print(f"\n{r['ticker']} — {r['name']} (as of {r['statement_date']})")
        print(f"  Current Ratio:        {r['current_ratio']}")
        print(f"  Debt-to-Equity:       {r['debt_to_equity']}")
        print(f"  Net Debt / EBITDA:    {r['net_debt_to_ebitda']}")
        print(f"  Interest Coverage:    {r['interest_coverage']}")
        print(f"  Altman Z-Score:       {r['altman_z_score']}  ({r['z_score_zone']})")
        if r.get("z_score_missing_inputs"):
            print(f"    (missing data for: {', '.join(r['z_score_missing_inputs'])})")

    # Save results to a JSON file so we can use them in the next step (AI analysis)
    with open("ratio_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print("\n\nSaved full results to ratio_results.json")


if __name__ == "__main__":
    main()
