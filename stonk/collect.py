"""Fetch every source, reconcile them, and write a snapshot for the renderer."""

import json
from collections import OrderedDict
from datetime import datetime, timezone

from . import config
from .api import StonkFunClient, get_token_supply


def _utc_now():
  return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _to_ui(raw, decimals):
  """Raw integer amount -> float token amount, for display only."""
  return int(raw) / (10 ** decimals)


def reconcile(chain, api_burn_totals, initial_supply=config.ASSUMED_INITIAL_SUPPLY):
  """Compare (initial supply - on-chain supply) against the platform burn ledger.

  Arithmetic stays in raw integers so the delta is exact; the gap is small enough
  that float rounding would otherwise be a meaningful share of the answer.
  """
  decimals = chain["decimals"]
  scale = 10 ** decimals

  supply_raw = int(chain["amountRaw"])
  initial_raw = initial_supply * scale
  chain_burned_raw = initial_raw - supply_raw
  api_burned_raw = int(api_burn_totals["amountRaw"])

  delta_raw = chain_burned_raw - api_burned_raw
  implied_initial_raw = supply_raw + api_burned_raw

  if delta_raw > 0:
    direction = "chain_ahead"
  elif delta_raw < 0:
    direction = "api_ahead"
  else:
    direction = "match"

  return {
    "assumedInitialSupply": initial_supply,
    "decimals": decimals,
    "supply": _to_ui(supply_raw, decimals),
    "supplyRaw": str(supply_raw),
    "chainBurned": _to_ui(chain_burned_raw, decimals),
    "chainBurnedRaw": str(chain_burned_raw),
    "apiBurned": _to_ui(api_burned_raw, decimals),
    "apiBurnedRaw": str(api_burned_raw),
    "deltaTokens": _to_ui(delta_raw, decimals),
    "deltaRaw": str(delta_raw),
    # Share of the burned amount, which is the number the delta actually threatens.
    "deltaPctOfBurned": (delta_raw / chain_burned_raw * 100) if chain_burned_raw else 0.0,
    "direction": direction,
    "burnedPctOfInitial": chain_burned_raw / initial_raw * 100,
    "impliedInitialSupply": _to_ui(implied_initial_raw, decimals),
    "impliedVsAssumed": _to_ui(implied_initial_raw - initial_raw, decimals),
    "chainObservedAt": chain["fetchedAt"],
    "apiLastBurnAt": api_burn_totals.get("lastBurnAt"),
    "slot": chain["slot"],
  }


def cross_check_usd(history, revenue, burn_totals):
  """Three independent USD figures for the same activity; agreement is the signal."""
  holders_sum = sum(day.get("dailyHoldersRevenue") or 0 for day in history["days"])
  bought_back = revenue.get("boughtBackTokens") or 0
  return {
    "historyHoldersRevenueSum": holders_sum,
    "revenueTotalBuybackUsd": revenue.get("totalBuybackUsd"),
    "revenueBoughtBackValueUsd": revenue.get("boughtBackValueUsd"),
    "tokenBurnValueUsdAtBurn": burn_totals.get("valueUsdAtBurn"),
    # Bought but not yet burned: the platform's own two counters, differenced.
    "boughtBackTokens": bought_back,
    "boughtNotYetBurnedTokens": bought_back - burn_totals["amountTokens"],
  }


def build_daily_series(history):
  """Daily rows plus a running cumulative of the buy-back-and-burn share."""
  days = []
  cumulative = 0.0
  for row in history["days"]:
    holders = row.get("dailyHoldersRevenue") or 0.0
    cumulative += holders
    days.append({
      "date": row["date"],
      "revenue": row.get("dailyRevenue") or 0.0,
      "holders": holders,
      "protocol": row.get("dailyProtocolRevenue") or 0.0,
      "cumulativeHolders": cumulative,
    })
  return days


def summarise_coverage(history):
  """The unpriced-row block: it bounds how far the USD figures are understated."""
  coverage = dict(history.get("coverage") or {})
  revenue_rows = coverage.get("revenueRows") or 0
  buyback_rows = coverage.get("buybackRows") or 0
  coverage["revenueUnpricedPct"] = (
    (coverage.get("revenueRowsUnpriced") or 0) / revenue_rows * 100 if revenue_rows else 0.0
  )
  coverage["buybackUnpricedPct"] = (
    (coverage.get("buybackRowsUnpriced") or 0) / buyback_rows * 100 if buyback_rows else 0.0
  )
  return coverage


def source_mix(burns):
  """Burn count and size by source across the most recent page of burns."""
  mix = OrderedDict()
  for burn in burns:
    key = burn.get("source") or "unknown"
    bucket = mix.setdefault(key, {"source": key, "count": 0, "amountTokens": 0.0, "valueUsd": 0.0})
    bucket["count"] += 1
    bucket["amountTokens"] += burn.get("amountTokens") or 0.0
    bucket["valueUsd"] += burn.get("valueUsdAtBurn") or 0.0
  return sorted(mix.values(), key=lambda item: item["amountTokens"], reverse=True)


def append_recon_log(recon, path=config.RECON_LOG_PATH):
  """One line per run.

  Drift of the delta over time is what separates a timing artefact (oscillates
  around zero) from a real ledger gap (trends in one direction).
  """
  path.parent.mkdir(parents=True, exist_ok=True)
  entry = {
    "observedAt": recon["chainObservedAt"],
    "slot": recon["slot"],
    "supply": recon["supply"],
    "chainBurned": recon["chainBurned"],
    "apiBurned": recon["apiBurned"],
    "deltaTokens": recon["deltaTokens"],
    "direction": recon["direction"],
  }
  with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
  return entry


def read_recon_log(path=config.RECON_LOG_PATH, limit=200):
  if not path.exists():
    return []
  rows = []
  with path.open(encoding="utf-8") as handle:
    for line in handle:
      line = line.strip()
      if line:
        rows.append(json.loads(line))
  return rows[-limit:]


def collect(mint=config.MINT, rpc_url=config.RPC_URL):
  """Pull every endpoint plus the chain, and fold them into one snapshot."""
  client = StonkFunClient()

  burns_payload = client.burns(mint)["data"]
  # Read the chain right after the burn ledger so the two are as close together
  # in time as the network allows; residual skew shows up as the delta below.
  chain = get_token_supply(mint, rpc_url=rpc_url)
  chain["fetchedAt"] = _utc_now()

  token_payload = client.token(mint)["data"]
  revenue_payload = client.revenue()["data"]
  history_payload = client.revenue_history()["data"]
  stats_payload = client.stats()["data"]

  recon = reconcile(chain, burns_payload["totals"])
  append_recon_log(recon)

  return {
    "generatedAt": _utc_now(),
    "mint": mint,
    "network": token_payload.get("network"),
    "rpcUrl": chain["rpcUrl"],
    "rateLimitRemaining": client.rate_limit_remaining,
    "token": token_payload["token"],
    "recon": recon,
    "reconHistory": read_recon_log(),
    "burnTotals": burns_payload["totals"],
    "recentBurns": burns_payload["burns"],
    "sourceMix": source_mix(burns_payload["burns"]),
    "daily": build_daily_series(history_payload),
    "historyMeta": {
      "start": history_payload.get("start"),
      "source": history_payload.get("source"),
      "unit": history_payload.get("unit"),
    },
    "coverage": summarise_coverage(history_payload),
    "usdCrossCheck": cross_check_usd(
      history_payload, revenue_payload["revenue"], burns_payload["totals"]
    ),
    "platformRevenue": revenue_payload["revenue"],
    "platformBurns": revenue_payload["burns"],
    "platformStats": stats_payload,
  }


def save_snapshot(snapshot, path=config.SNAPSHOT_PATH):
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
  return path


def load_snapshot(path=config.SNAPSHOT_PATH):
  return json.loads(path.read_text(encoding="utf-8"))
