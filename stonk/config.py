"""Shared configuration.

Every value here can be overridden by an environment variable so the same code
runs against a private RPC in a cron job without editing the source.
"""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
# The ledger is append-only and irreplaceable - the API cannot backfill it. On a
# server it therefore lives outside the checkout, where redeploying (which resets
# the working tree) cannot wipe months of accumulation.
DATA_DIR = Path(os.getenv("STONK_DATA_DIR") or ROOT_DIR / "data")
DIST_DIR = ROOT_DIR / "dist"

SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
RECON_LOG_PATH = DATA_DIR / "recon_history.jsonl"
# dist/ is the Vercel deploy root, so the page has to be index.html.
DASHBOARD_PATH = DIST_DIR / "index.html"

# Intraday ledgers. The API pages at 100 records and cannot backfill, so these
# accumulate locally; coverage.json records which ranges were actually observed.
BURN_LEDGER_PATH = DATA_DIR / "burns.jsonl"
BUYBACK_LEDGER_PATH = DATA_DIR / "buybacks.jsonl"
COVERAGE_PATH = DATA_DIR / "coverage.json"

# How much of the local ledger gets embedded in the page.
INTRADAY_WINDOW_HOURS = int(os.getenv("STONK_INTRADAY_HOURS", "48"))

# Where the 24/7 collector publishes its snapshot, and where the deployed page
# reads it back from. Without this the intraday ledger only ever exists inside
# whichever browser happened to be open, so every other visitor sees "未采集".
LIVE_PATH = DATA_DIR / "live.json"
LIVE_URL = os.getenv(
  "STONK_LIVE_URL",
  "https://raw.githubusercontent.com/adolyb/stonk-burn-board/live/data/live.json",
)

# Poll interval for `main.py watch`. 100 burns is ~25 min at ordinary activity but
# only a few minutes during a burst, so the default leaves headroom.
WATCH_INTERVAL = int(os.getenv("STONK_WATCH_INTERVAL", "180"))

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

# Hourly burn aggregates. The snapshot's intraday block only carries 48h of raw
# events; this is the long-history product the "分时" view reads, small enough to
# republish every cycle for months.
HOURLY_PATH = DATA_DIR / "hourly.json"
HOURLY_WINDOW_DAYS = int(os.getenv("STONK_HOURLY_DAYS", "30"))
HOURLY_URL = os.getenv(
  "STONK_HOURLY_URL",
  "https://raw.githubusercontent.com/adolyb/stonk-burn-board/live/data/hourly.json",
)
