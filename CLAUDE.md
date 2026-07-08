# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal, in-progress ASX (Australian Securities Exchange) financial distress
screener, built incrementally week by week. It pulls company fundamentals from
EODHD, computes credit/distress ratios, and uses the Claude API to turn those
ratios into subscriber-style risk write-ups. There is no build system, package
manifest, or test framework — this is a set of standalone scripts run directly
with `python3`, not an installable package.

## Running scripts

There's no virtualenv or requirements file; scripts just need `requests`
installed. Run any script directly, e.g.:

```
python3 calculate_ratios.py
python3 ai_risk_analysis.py
```

`ai_risk_analysis.py` requires two environment variables to be set first
(it will print an error and exit if either is missing):

```
export EODHD_API_KEY="..."
export ANTHROPIC_API_KEY="..."
```

The `test_*.py` and `inspect_*.py` scripts are one-off manual exploration
scripts (not a pytest suite) used to probe the EODHD API shape before writing
the real logic — run them directly the same way when you need to check what a
new EODHD endpoint/field looks like.

## Pipeline architecture

The scripts form a linear pipeline, each stage re-fetching from EODHD rather
than strictly depending on the previous stage's output file:

1. **`watchlist.py`** — defines `WATCHLIST`, a small hand-curated list of ~6
   companies: 4 with real, sourced recent distress signals (earnings
   downgrades, governance issues, cost blowouts) plus 2 large stable
   "control" companies expected to score LOW distress. This contrast (flagged
   vs. control) is the core demo of the screener. This is the list actually
   consumed by `calculate_ratios.py` and `ai_risk_analysis.py`.

2. **`calculate_ratios.py`** — for each ticker in `WATCHLIST`, fetches
   fundamentals from EODHD (`GET /api/fundamentals/{ticker}`) and computes:
   Current Ratio, Debt-to-Equity, Net Debt/EBITDA, Interest Coverage, and an
   Altman Z-Score proxy (1968 formula, calibrated for industrial/manufacturing
   firms — explicitly unreliable for banks, insurers, and exchanges like
   ASX.AU). Writes `ratio_results.json`.

3. **`ai_risk_analysis.py`** — the AI layer. Re-fetches fundamentals itself
   (does *not* read `ratio_results.json`) because it also needs several
   quarters of history for trend context, not just the latest snapshot. It
   recomputes the same current-period ratios (logic mirrors
   `calculate_ratios.py` — keep the two in sync if the ratio formulas change),
   builds a table of historical revenue/EBIT/debt/cash, and sends both to
   Claude with a strict prompt template (`build_prompt`) that forces a fixed
   output structure: RISK RATING / CONFIDENCE / PRIMARY DRIVER / TREND / WATCH
   TRIGGER, capped at 180 words. Writes `ai_risk_results.json`.

**`asx200_watchlist.py`** is a separate, larger data source: the full ~201
current ASX 200 constituents (sourced from STW ETF holdings), keyed as
`ASX_200_WATCHLIST` with a different shape (`ticker`/`name`/`sector`/
`weight_pct`, no `flag_reason`). It is **not yet wired into** `calculate_ratios.py`
or `ai_risk_analysis.py` (both still import the small `WATCHLIST` from
`watchlist.py`) — treat it as the eventual universe to scan once the pipeline
is extended beyond the hand-picked demo list. It will drift out of date each
quarterly ASX 200 rebalance (Mar/Jun/Sep/Dec) and needs re-sourcing from
ssga.com when that happens.

## EODHD data shape notes (from the `inspect_*.py` exploration scripts)

- Fundamentals endpoint: `https://eodhd.com/api/fundamentals/{ticker}`, where
  ticker uses the `<CODE>.AU` convention (e.g. `BHP.AU`).
  Quarterly statements live at
  `data["Financials"]["Balance_Sheet"]["quarterly"]` and
  `data["Financials"]["Income_Statement"]["quarterly"]`, keyed by date string
  (most recent = `sorted(keys, reverse=True)[0]`).
- Numeric fields often arrive as strings or `null` — always pass through
  `safe_float()` rather than casting directly.
- EBITDA is not broken out per-quarter in the income statement; `ebit` is used
  as the quarterly proxy where EBITDA history is needed.
- The dedicated ASX 200 index-constituents endpoint was probed
  (`test_index_endpoint.py`) and found not reliable/available on the current
  plan — that's why `asx200_watchlist.py` exists as a static, manually
  re-downloaded list instead of a live API call.

## Security note

`calculate_ratios.py`, `test_connection.py`, `inspect_fields.py`, and
`inspect_income_statement.py` currently have the EODHD API key hardcoded
in-file. `ai_risk_analysis.py` is the only script following the intended
pattern of reading both API keys from environment variables
(`EODHD_API_KEY`, `ANTHROPIC_API_KEY`). If bringing this repo under version
control, rotate/remove the hardcoded key and bring the older scripts in line
with the env-var pattern first.
