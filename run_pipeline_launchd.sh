#!/bin/bash
# Wrapper invoked by the launchd job (com.tomosowen.asxpipeline.plist).
#
# launchd does not source ~/.zshrc, so the API keys can't come from your
# normal shell environment. Instead they're pulled from the macOS login
# Keychain at run time — see the two `security add-generic-password`
# commands you ran to seed them. Nothing secret is ever written to disk
# here or in the plist.
set -euo pipefail

PROJECT_DIR="/Users/tomosowen/Projects/AI Project"
cd "$PROJECT_DIR"

export EODHD_API_KEY
EODHD_API_KEY="$(security find-generic-password -a "$USER" -s "asx-pipeline-eodhd-api-key" -w)"

export ANTHROPIC_API_KEY
ANTHROPIC_API_KEY="$(security find-generic-password -a "$USER" -s "asx-pipeline-anthropic-api-key" -w)"

# Test subset for now — switch to `--full` here once ready to scan all 201.
exec /usr/local/bin/python3 run_pipeline.py
