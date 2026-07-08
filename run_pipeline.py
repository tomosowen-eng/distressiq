"""
Pipeline Orchestrator — runs the full screener pipeline end-to-end over a
slice of the ASX 200 universe (asx200_watchlist.py) instead of the small
hand-curated WATCHLIST used by calculate_ratios.py / ai_risk_analysis.py.

For each company this:
  1. Fetches fundamentals from EODHD (one fetch per company, reused for both
     steps below — calculate_ratios.py and ai_risk_analysis.py each fetch
     separately today, but there's no need to hit EODHD twice per company
     here).
  2. Calculates the same distress ratio set as calculate_ratios.py.
  3. Runs the same Claude risk write-up as ai_risk_analysis.py, then parses
     the fixed-structure response into separate fields (risk rating,
     confidence, primary driver, trend, watch trigger) so a web front end
     doesn't have to re-parse free text.

Results are written to results.json as a single JSON object (run metadata +
a list of per-company results) rather than a bare list, so a front end can
tell a completed run from its results.

Every company is wrapped in its own try/except — one company's failure
(bad ticker, missing statements, EODHD outage, Claude API error) is logged
and skipped; the run continues with the rest.

SETUP (one-time): both API keys are read from environment variables, never
hardcoded:
    export EODHD_API_KEY="your_eodhd_key_here"
    export ANTHROPIC_API_KEY="your_anthropic_key_here"

HOW TO RUN:
    python3 run_pipeline.py            # test subset (first SUBSET_SIZE companies)
    python3 run_pipeline.py --full     # entire ASX_200_WATCHLIST
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

from asx200_watchlist import ASX_200_WATCHLIST

EODHD_API_KEY = os.environ.get("EODHD_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

CLAUDE_MODEL = "claude-sonnet-4-5"  # matches ai_risk_analysis.py
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# Test subset size — change this (or pass --full) to scan more of the ASX 200.
SUBSET_SIZE = 15

# How many historical quarterly periods to pull for trend context, mirroring
# ai_risk_analysis.py.
MAX_HISTORY_PERIODS = 12

# The Altman Z-Score formula (see calculate_ratios docstring in CLAUDE.md) is
# calibrated for industrial/manufacturing firms and isn't meaningful for
# these sectors — the zone label is suppressed for them in results.json
# (the raw score is kept; the AI risk rating is the headline signal instead).
Z_SCORE_NOT_APPLICABLE_SECTORS = {"Financials", "Real Estate"}
Z_SCORE_NOT_APPLICABLE_LABEL = "N/A — Z-score not applicable to financials"

RESULTS_FILE = "results.json"
DOCS_RESULTS_FILE = "docs/results.json"  # served by the GitHub Pages front end
LOG_FILE = "pipeline_log.txt"


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
    response = requests.get(url, params=params, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(
            f"EODHD returned status {response.status_code}: {response.text[:200]}"
        )
    return response.json()


def calculate_ratios(data, ticker):
    """
    Calculate the distress ratio set for the most recent quarter. Logic
    mirrors calculate_ratios.py / ai_risk_analysis.py — keep in sync if the
    ratio formulas change there.
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
    net_working_capital = safe_float(bs.get("netWorkingCapital"))
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

    ratios["current_ratio"] = (
        round(total_current_assets / total_current_liab, 2)
        if total_current_assets and total_current_liab
        else None
    )
    ratios["debt_to_equity"] = (
        round(total_debt / total_equity, 2)
        if total_debt is not None and total_equity
        else None
    )
    ratios["net_debt_to_ebitda"] = (
        round(net_debt / ebitda, 2) if net_debt is not None and ebitda else None
    )
    ratios["interest_coverage"] = (
        round(ebit / interest_expense, 2)
        if ebit is not None and interest_expense
        else None
    )

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

    if missing_inputs or total_assets == 0 or total_liab == 0:
        ratios["altman_z_score"] = None
        ratios["z_score_zone"] = "Unable to calculate"
        ratios["z_score_missing_inputs"] = missing_inputs
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
        ratios["z_score_missing_inputs"] = []

    return ratios


def extract_history(data):
    """
    Build a list of historical snapshots (most recent first) covering
    revenue, EBIT, total debt, cash, and net debt, mirroring
    ai_risk_analysis.py's extract_history.
    """
    financials = data.get("Financials", {})

    balance_sheet_q = financials.get("Balance_Sheet", {}).get("quarterly", {})
    income_q = financials.get("Income_Statement", {}).get("quarterly", {})

    if not balance_sheet_q or not income_q:
        return []

    dates = sorted(set(balance_sheet_q.keys()) & set(income_q.keys()), reverse=True)
    dates = dates[:MAX_HISTORY_PERIODS]

    history = []
    for date in dates:
        bs = balance_sheet_q.get(date, {})
        inc = income_q.get(date, {})
        history.append({
            "period": date,
            "revenue": safe_float(inc.get("totalRevenue")),
            "ebit": safe_float(inc.get("ebit")),
            "total_debt": safe_float(bs.get("shortLongTermDebtTotal")),
            "cash": safe_float(bs.get("cash")),
            "net_debt": safe_float(bs.get("netDebt")),
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


def build_prompt(company, ratios, history):
    """
    Construct the Claude prompt. Same fixed-structure template as
    ai_risk_analysis.py's build_prompt, but the CONTEXT line describes an
    ASX 200 constituent (sector + index weight) rather than a pre-flagged
    distress reason, since asx200_watchlist.py entries carry no flag_reason.
    """
    history_table = format_history_for_prompt(history)
    context = (
        f"ASX 200 constituent — sector: {company.get('sector', 'Unknown')}, "
        f"index weight: {company.get('weight_pct', 'N/A')}%. This is a "
        f"broad-universe scan, not a pre-flagged distress case — assess risk "
        f"purely from the fundamentals below."
    )

    prompt = f"""You are a credit/restructuring analyst writing a subscriber-facing financial distress note. Be decisive and specific — avoid vague hedging. Do not just restate the ratios; explain what is driving them and what it means.

COMPANY: {company['name']} ({company['ticker']})
CONTEXT: {context}

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
    response = requests.post(ANTHROPIC_API_URL, headers=headers, json=body, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(
            f"Claude API returned status {response.status_code}: {response.text[:200]}"
        )

    data = response.json()
    text_blocks = [block["text"] for block in data.get("content", []) if block.get("type") == "text"]
    return "\n".join(text_blocks)


HEADERS_IN_ORDER = ["RISK RATING", "CONFIDENCE", "PRIMARY DRIVER", "TREND", "WATCH TRIGGER"]
_HEADER_PATTERN = re.compile(
    r"(" + "|".join(HEADERS_IN_ORDER) + r"):\s*(.*?)(?=\n(?:" + "|".join(HEADERS_IN_ORDER) + r"):|\Z)",
    re.DOTALL,
)


def parse_ai_response(text):
    """
    Parse Claude's fixed-structure response into separate fields, so a web
    front end can render risk_rating / confidence / etc. directly instead of
    re-parsing free text.
    """
    fields = {
        "risk_rating": None,
        "confidence_level": None,
        "confidence_reason": None,
        "primary_driver": None,
        "trend": None,
        "watch_trigger": None,
    }
    if not text:
        return fields

    raw = {header: content.strip() for header, content in _HEADER_PATTERN.findall(text)}

    fields["risk_rating"] = raw.get("RISK RATING")
    fields["primary_driver"] = raw.get("PRIMARY DRIVER")
    fields["trend"] = raw.get("TREND")
    fields["watch_trigger"] = raw.get("WATCH TRIGGER")

    confidence_raw = raw.get("CONFIDENCE")
    if confidence_raw:
        parts = re.split(r"\s+—\s+|\s+-\s+", confidence_raw, maxsplit=1)
        fields["confidence_level"] = parts[0].strip()
        fields["confidence_reason"] = parts[1].strip() if len(parts) > 1 else None

    return fields


def log(log_lines, message):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{timestamp}] {message}"
    print(line)
    log_lines.append(line)


def process_company(company):
    """Run the full per-company pipeline. Raises on any failure."""
    ticker = company["ticker"]
    data = fetch_fundamentals(ticker)

    # asx200_watchlist.py names come from the STW holdings file and are
    # truncated (e.g. "Cmnwlth Bk Of Aust") — EODHD's fundamentals response
    # carries the proper company name at no extra API cost since we already
    # fetch this response for the ratios below.
    display_name = data.get("General", {}).get("Name") or company["name"]

    ratios = calculate_ratios(data, ticker)
    if ratios is None:
        raise MissingDataError(f"missing balance sheet/income statement data for {ticker}")

    history = extract_history(data)
    prompt = build_prompt(company, ratios, history)
    ai_text = call_claude(prompt)
    if not ai_text:
        raise RuntimeError(f"Claude returned no analysis for {ticker}")

    parsed = parse_ai_response(ai_text)

    sector = company.get("sector")
    z_score_zone = (
        Z_SCORE_NOT_APPLICABLE_LABEL
        if sector in Z_SCORE_NOT_APPLICABLE_SECTORS
        else ratios.get("z_score_zone")
    )

    return {
        "ticker": ticker,
        "name": display_name,
        "sector": sector,
        "index_weight_pct": company.get("weight_pct"),
        "statement_date": ratios.get("statement_date"),
        "ratios": {
            "current_ratio": ratios.get("current_ratio"),
            "debt_to_equity": ratios.get("debt_to_equity"),
            "net_debt_to_ebitda": ratios.get("net_debt_to_ebitda"),
            "interest_coverage": ratios.get("interest_coverage"),
        },
        "altman_z_score": ratios.get("altman_z_score"),
        "z_score_zone": z_score_zone,
        "risk_rating": parsed["risk_rating"],
        "confidence_level": parsed["confidence_level"],
        "confidence_reason": parsed["confidence_reason"],
        "primary_driver": parsed["primary_driver"],
        "trend": parsed["trend"],
        "watch_trigger": parsed["watch_trigger"],
        "history_periods_used": len(history),
        "raw_ai_analysis": ai_text,
    }


class MissingDataError(Exception):
    """Raised when EODHD returned data but it's missing the statements we need."""


def parse_args():
    parser = argparse.ArgumentParser(description="ASX distress screener pipeline orchestrator")
    parser.add_argument(
        "--full",
        action="store_true",
        help=f"Run the entire ASX 200 watchlist ({len(ASX_200_WATCHLIST)} companies) "
        f"instead of the {SUBSET_SIZE}-company test subset",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not EODHD_API_KEY:
        print("ERROR: EODHD_API_KEY environment variable is not set.")
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)

    companies = ASX_200_WATCHLIST if args.full else ASX_200_WATCHLIST[:SUBSET_SIZE]

    run_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_lines = []
    log(
        log_lines,
        f"Pipeline run started — {len(companies)} companies "
        f"({'full ASX 200' if args.full else f'test subset of {SUBSET_SIZE}'})",
    )

    results = []
    failures = []
    missing_data = []

    for company in companies:
        ticker = company["ticker"]
        try:
            result = process_company(company)
            results.append(result)
            log(log_lines, f"OK   {ticker} — risk rating: {result['risk_rating']}")
        except MissingDataError as exc:
            missing_data.append(ticker)
            failures.append({"ticker": ticker, "error": str(exc)})
            log(log_lines, f"FAIL {ticker} — {exc}")
        except Exception as exc:
            failures.append({"ticker": ticker, "error": str(exc)})
            log(log_lines, f"FAIL {ticker} — {exc}")
        time.sleep(1)  # be polite to both APIs

    run_completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    output = {
        "run_timestamp": run_timestamp,
        "run_completed_at": run_completed_at,
        "subset": "full" if args.full else f"test_subset_{SUBSET_SIZE}",
        "companies_requested": len(companies),
        "companies_succeeded": len(results),
        "companies_failed": len(failures),
        "failures": failures,
        "missing_data": missing_data,
        "results": results,
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(output, f, indent=2)

    os.makedirs(os.path.dirname(DOCS_RESULTS_FILE), exist_ok=True)
    with open(DOCS_RESULTS_FILE, "w") as f:
        json.dump(output, f, indent=2)

    log(
        log_lines,
        f"Pipeline run finished — {len(results)} succeeded, {len(failures)} failed, "
        f"{len(missing_data)} missing data. Results written to {RESULTS_FILE} and {DOCS_RESULTS_FILE}",
    )

    with open(LOG_FILE, "a") as f:
        f.write("\n".join(log_lines) + "\n" + ("=" * 90) + "\n")


if __name__ == "__main__":
    main()
