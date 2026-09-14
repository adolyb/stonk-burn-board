"""ammo.py answers one question: how much already-claimed fee money is sitting in
the buyback wallet, waiting to become STONK buys. The wallet also holds thousands
of dead launch tokens, so most of these tests are about *what gets excluded*.
"""

import json
from datetime import datetime, timezone

from stonk import ammo

STONK = "6GmAFSYs4gk3FDao5FzzySQpPZaWsa4rUJHacpMpUNgx"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL = "So11111111111111111111111111111111111111112"
WBTC = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"
DUST = "DeadLaunchTokenMint1111111111111111111111111"


def at(hour, minute=0):
  return int(datetime(2026, 9, 14, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def iso(ms):
  return (datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
          .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


# ---------- quote whitelist ----------

def test_merge_quotes_learns_new_mints_and_keeps_stables():
  buybacks = [
    {"quote": {"mint": WBTC, "symbol": "WBTC"}},
    {"quote": {"mint": WBTC, "symbol": "WBTC"}},
    {"quote": {"mint": "PENGUmint", "symbol": "PENGU"}},
  ]
  merged = ammo.merge_quotes({}, buybacks)
  assert merged[WBTC] == "WBTC"
  assert merged["PENGUmint"] == "PENGU"
  # Always-on quotes the API page may not happen to show this cycle.
  assert merged[USDC] == "USDC"
  assert merged[WSOL] == "SOL"


def test_merge_quotes_never_forgets():
  existing = {"OLDmint": "OLD"}
  merged = ammo.merge_quotes(existing, [{"quote": {"mint": WBTC, "symbol": "WBTC"}}])
  assert merged["OLDmint"] == "OLD"
  assert merged[WBTC] == "WBTC"


def test_merge_quotes_tolerates_missing_symbol():
  merged = ammo.merge_quotes({}, [{"quote": {"mint": "NoSymbolMint111"}}])
  assert merged["NoSymbolMint111"] == "NoSymbolMint111"[:6]


def test_quotes_roundtrip(tmp_path):
  path = tmp_path / "quotes.json"
  assert ammo.load_quotes(path) == {}
  ammo.save_quotes({WBTC: "WBTC"}, path)
  assert ammo.load_quotes(path) == {WBTC: "WBTC"}


# ---------- RPC response parsing ----------

def _account(mint, ui_amount):
  return {"account": {"data": {"parsed": {"info": {
    "mint": mint, "tokenAmount": {"uiAmountString": ui_amount},
  }}}}}


def test_balances_sum_duplicates_and_drop_zeros():
  values = [_account(WBTC, "0.01"), _account(WBTC, "0.02"), _account(DUST, "0"), _account(USDC, "5")]
  out = ammo.balances_from_accounts(values)
  assert out == {WBTC: 0.03, USDC: 5.0}


# ---------- price selection ----------

def _pair(mint, price, liquidity):
  return {"baseToken": {"address": mint}, "priceUsd": str(price), "liquidity": {"usd": liquidity}}


def test_pick_prices_prefers_deepest_pool_and_ignores_strangers():
  pairs = [
    _pair(WBTC, 70000, 1_000),
    _pair(WBTC, 77000, 900_000),   # deeper pool wins even though it is listed second
    _pair("Stranger", 1, 10),
    {"baseToken": {"address": USDC}, "priceUsd": None, "liquidity": {"usd": 5}},
  ]
  out = ammo.pick_prices(pairs, [WBTC, USDC])
  assert out[WBTC]["usd"] == 77000
  assert out[WBTC]["liquidityUsd"] == 900_000
  assert USDC not in out
  assert "Stranger" not in out


# ---------- the gauge itself ----------

def test_build_ammo_counts_only_quotes_and_prices_what_it_can():
  balances = {WBTC: 0.5, USDC: 100.0, DUST: 5e8, STONK: 1000.0, "UnpricedQuote": 3.0}
  quotes = {WBTC: "WBTC", USDC: "USDC", "UnpricedQuote": "UNP"}
  prices = {WBTC: {"usd": 100_000.0}, USDC: {"usd": 1.0}, STONK: {"usd": 0.2}, WSOL: {"usd": 100.0}}
  out = ammo.build_ammo(balances, quotes, prices, sol_lamports=2_000_000_000,
                        stonk_mint=STONK, observed_at="2026-09-14T05:00:00.000Z")

  assert out["quoteUsd"] == 50_100.0
  assert out["quoteCount"] == 3
  assert out["unpricedCount"] == 1
  assert out["unpricedSymbols"] == ["UNP"]
  # The dead launch token is neither counted nor listed, only tallied.
  assert out["ignoredMints"] == 1
  assert all(r["mint"] != DUST for r in out["quoteRows"])
  # STONK bought but not yet burned is its own line, never part of the ammo.
  assert out["stonkPending"] == {"amount": 1000.0, "usd": 200.0}
  assert out["sol"] == {"amount": 2.0, "usd": 200.0}
  # Priced rows first, largest first, unpriced trailing.
  assert [r["symbol"] for r in out["quoteRows"]] == ["WBTC", "USDC", "UNP"]
  assert out["quoteRows"][-1]["usd"] is None


def test_build_ammo_empty_wallet():
  out = ammo.build_ammo({}, {}, {}, sol_lamports=0, stonk_mint=STONK, observed_at="2026-09-14T05:00:00.000Z")
  assert out["quoteUsd"] == 0.0
  assert out["quoteRows"] == []
  assert out["stonkPending"]["amount"] == 0.0


def test_build_ammo_without_sol_price_leaves_usd_none():
  out = ammo.build_ammo({}, {}, {}, sol_lamports=10 ** 9, stonk_mint=STONK, observed_at="x")
  assert out["sol"] == {"amount": 1.0, "usd": None}


# ---------- history ----------

def test_history_append_load_window(tmp_path):
  path = tmp_path / "ammo_history.jsonl"
  for h in (1, 2, 3):
    ammo.append_history({"t": iso(at(h)), "q": h * 10.0, "s": 1.0, "k": 0.0, "n": 1, "u": 0}, path)
  rows = ammo.load_history(path, since_ms=at(2))
  assert [r["q"] for r in rows] == [20.0, 30.0]
  assert ammo.load_history(tmp_path / "missing.jsonl") == []


def test_downsample_keeps_last_sample_per_bucket():
  rows = [
    {"t": iso(at(1, 0)), "q": 1.0, "s": 0.0, "k": 0.0},
    {"t": iso(at(1, 4)), "q": 2.0, "s": 0.0, "k": 0.0},
    {"t": iso(at(1, 12)), "q": 3.0, "s": 0.0, "k": 0.0},
  ]
  out = ammo.downsample(rows, bucket_ms=10 * 60 * 1000)
  assert out == [[at(1, 0), 2.0, 0.0, 0.0], [at(1, 10), 3.0, 0.0, 0.0]]


def test_build_payload_trims_rows_and_windows_history(tmp_path):
  path = tmp_path / "ammo_history.jsonl"
  for d in range(10):
    ammo.append_history({"t": iso(at(0) - d * 86400000), "q": float(d), "s": 0.0, "k": 0.0, "n": 1, "u": 0}, path)
  latest = {"quoteRows": [{"mint": str(i), "symbol": str(i), "amount": 1.0, "usd": float(i)} for i in range(30)],
            "quoteUsd": 1.0}
  payload = ammo.build_payload(latest, history_path=path, window_days=7, now_ms=at(0), max_rows=20)
  assert len(payload["latest"]["quoteRows"]) == 20
  assert payload["windowDays"] == 7
  # 7-day window keeps today plus the previous 7 days' samples, not all 10.
  assert len(payload["history"]) == 8
  assert payload["history"][0][0] < payload["history"][-1][0]
  assert payload["generatedAt"] == iso(at(0))


def test_save_ammo_is_minified(tmp_path):
  path = ammo.save_ammo({"a": [1, 2]}, tmp_path / "ammo.json")
  assert path.read_text(encoding="utf-8") == '{"a":[1,2]}'
  assert json.loads(path.read_text(encoding="utf-8")) == {"a": [1, 2]}
