#!/usr/bin/env bash
# Wrapper to run the digest sender with environment loaded
set -euo pipefail

# Change to project directory
cd "$(dirname "$0")"

# Load .env if present (simple key=val parser)
if [ -f .env ]; then
  # export each non-comment line
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# If you use a Python venv, set PYTHON_BIN accordingly (edit if needed)
PYTHON_BIN=${PYTHON_BIN:-/usr/bin/env python3}

$PYTHON_BIN run.py --send-email
