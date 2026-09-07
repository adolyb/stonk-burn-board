#!/usr/bin/env bash
# Enter the virtual environment: source activate.sh
cd "$(dirname "${BASH_SOURCE[0]}")"
if [ ! -d .venv ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    return 1 2>/dev/null || exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
