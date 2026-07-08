"""
Step 2b: Inspect Income Statement fields.

We have Balance Sheet and Highlights already. This checks the Income Statement
for fields needed to calculate interest coverage and the Altman Z-score
(EBIT, interest expense, revenue, etc.)

SETUP (one-time):
  The EODHD API key is read from an environment variable, not hardcoded, so
  this script is safe to push to GitHub later without exposing your key.

  In Terminal, run this line (replace with your real key):
      export EODHD_API_KEY="your_eodhd_key_here"

  This only lasts for your current Terminal session. To make it permanent,
  add that line to your ~/.zshrc file (open it with: nano ~/.zshrc),
  save, then run: source ~/.zshrc

HOW TO RUN: same as before.
    /usr/local/bin/python3 inspect_income_statement.py
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

financials = data.get("Financials", {})
income_quarterly = financials.get("Income_Statement", {}).get("quarterly", {})

most_recent_date = sorted(income_quarterly.keys(), reverse=True)[0]
print(f"Most recent quarterly Income Statement — date: {most_recent_date}")
print(json.dumps(income_quarterly[most_recent_date], indent=2))
