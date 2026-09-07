#!/usr/bin/env bash
# Rebuild the page from fresh data, then deploy dist/ to Vercel production.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python main.py
vercel deploy dist --prod
