"""
Week 3, Step 1: Test whether EODHD's index constituents endpoint is available
on Tom's plan, and what shape the data comes back in.

EODHD's documented endpoint for index constituents is:
    https://eodhd.com/api/fundamentals/{INDEX_TICKER}

...where common ASX 200 index tickers people use are "GSPTSE" (wrong, that's
TSX) -- for ASX the usual EODHD ticker is "AXJO.INDX" (S&P/ASX 200).
This script just tries it and shows us exactly what comes back so we know
whether to build around it or fall back to a static list.

HOW TO RUN (same as before):
    /usr/local/bin/python3 test_index_endpoint.py
"""

import requests
import json
import os

API_KEY = os.environ.get("EODHD_API_KEY")
if not API_KEY:
    print("ERROR: EODHD_API_KEY environment variable is not set.")
    raise SystemExit(1)

# Try the S&P/ASX 200 index ticker
INDEX_TICKER = "AXJO.INDX"

url = f"https://eodhd.com/api/fundamentals/{INDEX_TICKER}"
params = {"api_token": API_KEY, "fmt": "json"}

print(f"Requesting index fundamentals for {INDEX_TICKER}...")
response = requests.get(url, params=params)
print(f"Status code: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    print("\nTop-level sections returned:")
    for key in data.keys():
        print(f"  - {key}")

    # Index endpoints from EODHD usually return constituents under a
    # "Components" key — check for it specifically.
    components = data.get("Components")
    if components:
        print(f"\nFound 'Components' section with {len(components)} entries.")
        # Print first 5 as a sample
        sample_keys = list(components.keys())[:5]
        for k in sample_keys:
            print(f"  {k}: {json.dumps(components[k], indent=2)}")
    else:
        print("\nNo 'Components' key found. Full top-level keys shown above —")
        print("inspect those manually to see if constituents are listed elsewhere.")
else:
    print("Request failed. Response text:")
    print(response.text[:1000])
