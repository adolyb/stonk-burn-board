"""Shared configuration.

Every value here can be overridden by an environment variable so the same code
runs against a private RPC in a cron job without editing the source.
"""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DIST_DIR = ROOT_DIR / "dist"

SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
RECON_LOG_PATH = DATA_DIR / "recon_history.jsonl"
DASHBOARD_PATH = DIST_DIR / "dashboard.html"

MINT = os.getenv("STONK_MINT", "6GmAFSYs4gk3FDao5FzzySQpPZaWsa4rUJHacpMpUNgx")
API_BASE = os.getenv("STONK_API_BASE", "https://www.stonkfun.xyz/api/public/v1")

# Public RPC is rate limited hard; point this at Helius/QuickNode for cron use.
RPC_URL = os.getenv("STONK_RPC_URL", "https://api.mainnet-beta.solana.com")

# The launch mint supply. Not readable from the chain after the fact, so it is an
# assumption the board states out loud and cross-checks via impliedInitialSupply.
ASSUMED_INITIAL_SUPPLY = int(os.getenv("STONK_INITIAL_SUPPLY", "1000000000"))

# API caps both list endpoints at 100.
LIST_LIMIT = 100

HTTP_TIMEOUT = 30
USER_AGENT = "stonk-burn-board/1.0 (+local dashboard)"
