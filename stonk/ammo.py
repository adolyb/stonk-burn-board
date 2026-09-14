"""How much buyback money is loaded and waiting.

Fees on stonkfun accrue inside Raydium LaunchLab pool vaults, get claimed into one
buyback wallet in the platform's quote tokens, and are swapped to STONK from
there. The claimed-but-unswapped balance is the only part of that pipeline that
is both public and attributable, so that is what this module measures: the
wallet's quote-token holdings, priced in USD.

Two things it deliberately leaves out:

  * the vault side - LaunchLab vault accounts are shared by every launchpad on
    the program and mix fees with live bonding-curve liquidity, so a sum over
    them is not stonkfun's backlog;
  * the wallet's dead launch tokens - thousands of never-graduated mints that
    are burned as "auto"/"reward", not bought back. Only mints seen as a buyback
    quote (plus the stables) count.

Every fetch appends one row to a history file so the page can show whether the
pile is growing or being worked down.
"""

import json
from datetime import datetime, timezone

import requests

from . import config
from .api import ApiError

TOKEN_PROGRAMS = (
  "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
  "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
)
WSOL_MINT = "So11111111111111111111111111111111111111112"
# Quotes that are always valid even if no buyback happened to use them lately.
ALWAYS_QUOTES = {
  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
  "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
  WSOL_MINT: "SOL",
}
LAMPORTS = 1_000_000_000
PRICE_BATCH = 30


def _utc_now_ms():
  return int(datetime.now(timezone.utc).timestamp() * 1000)


def _iso(ms):
  return (datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
          .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


def _epoch_ms(iso):
  return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


# ---------- quote whitelist ----------

def merge_quotes(existing, recent_buybacks):
  """Fold the quote mints seen on a buyback page into the persisted whitelist.

  Never drops a mint: a quote that stops appearing on the 100-row page is still
  a quote, and its leftover balance is still ammo.
  """
  quotes = dict(existing)
  for row in recent_buybacks or []:
    quote = row.get("quote") or {}
    mint = quote.get("mint")
    if not mint:
      continue
    quotes.setdefault(mint, quote.get("symbol") or mint[:6])
  for mint, symbol in ALWAYS_QUOTES.items():
    quotes.setdefault(mint, symbol)
  return quotes


def load_quotes(path=None):
  path = path or config.QUOTES_PATH
  if not path.exists():
    return {}
  return json.loads(path.read_text(encoding="utf-8"))


def save_quotes(quotes, path=None):
  path = path or config.QUOTES_PATH
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(quotes, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
  return path


# ---------- chain ----------

def balances_from_accounts(values):
  """{mint: ui amount} from a jsonParsed getTokenAccountsByOwner result.

  One wallet can hold several accounts of the same mint (an ATA plus stray
  auxiliaries), so amounts are summed rather than overwritten.
  """
  balances = {}
  for entry in values or []:
    info = entry["account"]["data"]["parsed"]["info"]
    amount = float(info["tokenAmount"].get("uiAmountString") or 0)
    if amount > 0:
      balances[info["mint"]] = balances.get(info["mint"], 0.0) + amount
  return balances


def _rpc(method, params, rpc_url, timeout):
  response = requests.post(
    rpc_url,
    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    timeout=timeout,
    headers={"User-Agent": config.USER_AGENT},
  )
  response.raise_for_status()
  payload = response.json()
  if "error" in payload:
    raise ApiError(f"RPC {method} -> {payload['error']}")
  return payload["result"]


def fetch_wallet(wallet=None, rpc_url=None, timeout=90):
  """Every token balance in the buyback wallet, plus its native SOL.

  The response is large (the wallet has >10k accounts), which is why the
  timeout is generous and why this runs after the cheap API calls in a fetch.
  """
  wallet = wallet or config.TREASURY_WALLET
  rpc_url = rpc_url or config.RPC_URL
  balances = {}
  slot = None
  for program in TOKEN_PROGRAMS:
    result = _rpc(
      "getTokenAccountsByOwner",
      [wallet, {"programId": program}, {"encoding": "jsonParsed"}],
      rpc_url, timeout,
    )
    slot = result["context"]["slot"]
    for mint, amount in balances_from_accounts(result["value"]).items():
      balances[mint] = balances.get(mint, 0.0) + amount
  lamports = _rpc("getBalance", [wallet], rpc_url, timeout)["value"]
  return {"wallet": wallet, "balances": balances, "solLamports": lamports, "slot": slot}


# ---------- prices ----------

def pick_prices(pairs, mints):
  """Deepest pool per requested mint. Thin pools quote fantasy prices."""
  wanted = set(mints)
  best = {}
  for pair in pairs or []:
    mint = (pair.get("baseToken") or {}).get("address")
    price = pair.get("priceUsd")
    if mint not in wanted or not price:
      continue
    liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
    if mint not in best or liquidity > best[mint]["liquidityUsd"]:
      best[mint] = {"usd": float(price), "liquidityUsd": liquidity}
  return best


def fetch_prices(mints, price_api=None, timeout=30):
  price_api = price_api or config.PRICE_API
  mints = list(dict.fromkeys(mints))
  prices = {}
  for start in range(0, len(mints), PRICE_BATCH):
    chunk = mints[start:start + PRICE_BATCH]
    response = requests.get(
      price_api + ",".join(chunk), timeout=timeout, headers={"User-Agent": config.USER_AGENT}
    )
    response.raise_for_status()
    prices.update(pick_prices(response.json(), chunk))
  return prices


# ---------- the gauge ----------

def build_ammo(balances, quotes, prices, sol_lamports, stonk_mint, observed_at):
  rows = []
  quote_usd = 0.0
  unpriced = []
  ignored = 0
  for mint, amount in balances.items():
    if mint == stonk_mint:
      continue
    if mint not in quotes:
      ignored += 1
      continue
    price = prices.get(mint)
    usd = amount * price["usd"] if price else None
    if usd is None:
      unpriced.append(quotes[mint])
    else:
      quote_usd += usd
    rows.append({"mint": mint, "symbol": quotes[mint], "amount": amount, "usd": usd})

  rows.sort(key=lambda r: (r["usd"] is None, -(r["usd"] or 0)))

  def _usd(amount, mint):
    price = prices.get(mint)
    return amount * price["usd"] if price else None

  sol_amount = sol_lamports / LAMPORTS
  stonk_amount = balances.get(stonk_mint, 0.0)
  return {
    "observedAt": observed_at,
    "quoteUsd": quote_usd,
    "quoteCount": len(rows),
    "unpricedCount": len(unpriced),
    "unpricedSymbols": sorted(unpriced),
    "ignoredMints": ignored,
    "quoteRows": rows,
    "sol": {"amount": sol_amount, "usd": _usd(sol_amount, WSOL_MINT)},
    "stonkPending": {"amount": stonk_amount, "usd": _usd(stonk_amount, stonk_mint)},
  }


# ---------- history ----------

def append_history(entry, path=None):
  path = path or config.AMMO_HISTORY_PATH
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
  return entry


def load_history(path=None, since_ms=None):
  path = path or config.AMMO_HISTORY_PATH
  if not path.exists():
    return []
  rows = []
  with path.open(encoding="utf-8") as handle:
    for line in handle:
      line = line.strip()
      if not line:
        continue
      row = json.loads(line)
      if since_ms is None or _epoch_ms(row["t"]) >= since_ms:
        rows.append(row)
  rows.sort(key=lambda r: r["t"])
  return rows


def downsample(rows, bucket_ms):
  """Last sample per bucket, as compact [t, quoteUsd, solUsd, stonkUsd] arrays.

  A 3-minute cadence over a week is too many points to ship; the last sample in
  each bucket is the state of the pile at that moment, which is what a level
  gauge should show (a mean would smear the flushes).
  """
  buckets = {}
  for row in rows:
    key = _epoch_ms(row["t"]) // bucket_ms * bucket_ms
    buckets[key] = [key, row.get("q") or 0.0, row.get("s") or 0.0, row.get("k") or 0.0]
  return [buckets[k] for k in sorted(buckets)]


def history_entry(ammo):
  return {
    "t": ammo["observedAt"],
    "q": round(ammo["quoteUsd"], 2),
    "s": round(ammo["sol"]["usd"] or 0.0, 2),
    "k": round(ammo["stonkPending"]["usd"] or 0.0, 2),
    "n": ammo["quoteCount"],
    "u": ammo["unpricedCount"],
  }


def build_payload(latest, history_path=None, window_days=None, now_ms=None, max_rows=None,
                  bucket_ms=10 * 60 * 1000):
  window_days = window_days or config.AMMO_WINDOW_DAYS
  max_rows = max_rows or config.AMMO_ROWS
  if now_ms is None:
    now_ms = _utc_now_ms()
  since_ms = now_ms - window_days * 86400000
  trimmed = dict(latest)
  trimmed["quoteRows"] = list(latest.get("quoteRows") or [])[:max_rows]
  return {
    "generatedAt": _iso(now_ms),
    "wallet": config.TREASURY_WALLET,
    "windowDays": window_days,
    "bucketMs": bucket_ms,
    "latest": trimmed,
    "history": downsample(load_history(history_path, since_ms), bucket_ms),
  }


def save_ammo(payload, path=None):
  path = path or config.AMMO_PATH
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
  return path


# ---------- one fetch cycle ----------

def collect_ammo(recent_buybacks, stonk_mint=None, wallet=None, rpc_url=None):
  """Learn quotes, read the wallet, price it, log a history row, return the gauge."""
  stonk_mint = stonk_mint or config.MINT
  quotes = merge_quotes(load_quotes(), recent_buybacks)
  save_quotes(quotes)

  chain = fetch_wallet(wallet, rpc_url)
  observed_at = _iso(_utc_now_ms())
  held_quotes = [m for m in chain["balances"] if m in quotes]
  prices = fetch_prices(held_quotes + [stonk_mint, WSOL_MINT])

  ammo = build_ammo(chain["balances"], quotes, prices, chain["solLamports"], stonk_mint, observed_at)
  ammo["wallet"] = chain["wallet"]
  ammo["slot"] = chain["slot"]
  ammo["knownQuotes"] = len(quotes)
  append_history(history_entry(ammo))
  return ammo
