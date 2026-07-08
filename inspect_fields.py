"""
Step 2: Inspect the data structure.

Before building the actual ratio calculator, we need to see the EXACT field
names EODHD uses inside the "Financials" and "Highlights" sections — these
vary slightly between data providers, so it's safer to check than guess.

SETUP (one-time):
  The EODHD API key is read from an environment variable, not hardcoded, so
  this script is safe to push to GitHub later without exposing your key.

  In Terminal, run this line (replace with your real key):
      export EODHD_API_KEY="your_eodhd_key_here"

  This only lasts for your current Terminal session. To make it permanent,
  add that line to your ~/.zshrc file (open it with: nano ~/.zshrc),
  save, then run: source ~/.zshrc

HOW TO RUN:
Same as before — make sure this file is in the same folder as test_connection.py
(or anywhere you like), then:
    /usr/local/bin/python3 inspect_fields.py
"""

import requests
import json
import os

API_KEY = os.environ.get("EODHD_API_KEY")
if not API_KEY:
    print("ERROR: EODHD_API_KEY environment variable is not set. See the setup instructions at the top of this file.")
    raise SystemExit(1)

TICKER = "BHP.AU"

url = f"https://eodhd.com/api/fundamentals/{TICKER}"
params = {"api_token": API_KEY, "fmt": "json"}

response = requests.get(url, params=params)
data = response.json()

print("=" * 60)
print("HIGHLIGHTS section (pre-computed ratios):")
print("=" * 60)
print(json.dumps(data.get("Highlights", {}), indent=2))

print()
print("=" * 60)
print("FINANCIALS section - structure only (top 2 levels):")
print("=" * 60)
financials = data.get("Financials", {})
for statement_type, statement_data in financials.items():
    print(f"\n{statement_type}:")
    if isinstance(statement_data, dict):
        for sub_key in statement_data.keys():
            print(f"  - {sub_key}")

print()
print("=" * 60)
print("FINANCIALS - most recent quarterly balance sheet (full detail):")
print("=" * 60)
try:
    balance_sheet_quarterly = financials.get("Balance_Sheet", {}).get("quarterly", {})
    most_recent_date = sorted(balance_sheet_quarterly.keys(), reverse=True)[0]
    print(f"Date: {most_recent_date}")
    print(json.dumps(balance_sheet_quarterly[most_recent_date], indent=2))
except Exception as e:
    print(f"Could not extract — error: {e}")
    print("Available keys in Financials:", list(financials.keys()))
