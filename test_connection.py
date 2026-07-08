"""
Step 1: Test EODHD API connection.

This just confirms the API key works and shows us what the raw fundamentals
data looks like for one company (BHP), before we build anything more complex.

SETUP (one-time):
  The EODHD API key is read from an environment variable, not hardcoded, so
  this script is safe to push to GitHub later without exposing your key.

  In Terminal, run this line (replace with your real key):
      export EODHD_API_KEY="your_eodhd_key_here"

  This only lasts for your current Terminal session. To make it permanent,
  add that line to your ~/.zshrc file (open it with: nano ~/.zshrc),
  save, then run: source ~/.zshrc

HOW TO RUN:
1. Save this file as test_connection.py on your Desktop (or anywhere you like)
2. In Terminal, navigate to that folder, e.g.:
       cd ~/Desktop
3. Run it:
       /usr/local/bin/python3 test_connection.py
"""

import requests
import os

API_KEY = os.environ.get("EODHD_API_KEY")
if not API_KEY:
    print("ERROR: EODHD_API_KEY environment variable is not set. See the setup instructions at the top of this file.")
    raise SystemExit(1)

TICKER = "BHP.AU"

url = f"https://eodhd.com/api/fundamentals/{TICKER}"
params = {
    "api_token": API_KEY,
    "fmt": "json"
}

print(f"Requesting fundamentals for {TICKER}...")
response = requests.get(url, params=params)

print(f"Status code: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    # Just print the top-level sections so we can see the shape of the data,
    # not the whole (very large) response.
    print("\nTop-level sections returned:")
    for key in data.keys():
        print(f"  - {key}")

    # Print a small, useful chunk: the General company info
    print("\nGeneral company info:")
    general = data.get("General", {})
    for field in ["Code", "Name", "Exchange", "Sector", "Industry"]:
        print(f"  {field}: {general.get(field)}")
else:
    print("Something went wrong. Response text:")
    print(response.text)
