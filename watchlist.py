"""
Week 1 — Watchlist definition.

This is the initial universe of ASX-listed companies for the distress screener.
Tom chose to focus on companies already showing some stress signals (e.g. recent
profit downgrades) rather than a broad scan.

Real, sourced entries (verified via news search, June 2026) plus two large stable
"control" companies — the screener should score the controls as LOW distress and
the flagged companies as MEDIUM/HIGH distress. That contrast is the actual demo.

NOTE: Tickers use the EODHD convention of <CODE>.AU (e.g. "BHP.AU").
Reasons below are summarised from public news reporting, not verbatim quotes —
re-check against the company's actual ASX announcements before citing externally.
"""

WATCHLIST = [
    # --- Flagged: real, recent stress signals ---
    {
        "ticker": "FLT.AU",
        "name": "Flight Centre Travel Group",
        "flag_reason": "Cut FY26 underlying PBT guidance to $275-295m from prior $310-345m range "
                        "(~7% miss at midpoint), driven by a Middle East-related Q4 leisure travel hit.",
    },
    {
        "ticker": "COH.AU",
        "name": "Cochlear Limited",
        "flag_reason": "Cut FY26 underlying net profit guidance to $290-330m, a ~30% downgrade at "
                        "midpoint from the $435-460m range issued just two months earlier. "
                        "Triggered the company's worst one-day selloff on record.",
    },
    {
        "ticker": "AX1.AU",
        "name": "Accent Group",
        "flag_reason": "Significant downgrade to second-half FY26 EBIT guidance, deteriorating trading "
                        "conditions, plus an ongoing ASIC investigation into executive share trading. "
                        "Good test case for qualitative/governance red flags, not just ratios.",
    },
    {
        "ticker": "ASX.AU",
        "name": "ASX Limited",
        "flag_reason": "Shares hit lowest level in ~decade after a larger-than-expected step-up in "
                        "technology-related expenses; several brokers (Barrenjoey, UBS, Macquarie) cut "
                        "earnings forecasts. Cost-blowout case rather than revenue miss.",
    },
    # --- Controls: large, stable companies, expected to score LOW distress ---
    {
        "ticker": "BHP.AU",
        "name": "BHP Group",
        "flag_reason": "Control case — large, stable, should score LOW distress.",
    },
    {
        "ticker": "CSL.AU",
        "name": "CSL Limited",
        "flag_reason": "Control case — large, stable. Note: CSL did miss earnings expectations in "
                        "Feb 2026 reporting season per Morningstar reporting, so may show some "
                        "short-term price volatility — still expected to score LOW on balance-sheet "
                        "distress given its scale.",
    },
]

if __name__ == "__main__":
    for company in WATCHLIST:
        print(f"{company['ticker']:>10}  {company['name']:<25}  {company['flag_reason']}")
