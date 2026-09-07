#!/usr/bin/env bash
# Create the virtual environment and install dependencies.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo
echo "Setup complete. Run 'source activate.sh' to enter the environment."
