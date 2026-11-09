"""ammo.py answers one question: how much already-claimed fee money is sitting in
the buyback wallet, waiting to become STONK buys. The wallet also holds thousands
of dead launch tokens, so most of these tests are about *what gets excluded*.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from stonk import ammo
from stonk.api import ApiError

STONK = "6GmAFSYs4gk3FDao5FzzySQpPZaWsa4rUJHacpMpUNgx"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL = "So11111111111111111111111111111111111111112"
WBTC = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"
ZEC = "A7bdiYdS5GjqGFtxf17ppRHtDKPkkRqbKtR27dxvQXaS"
PYTH = "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3"
JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
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

def _pair(mint, quote, price_usd, price_native, quote_reserve, liquidity_usd):
  return {
    "baseToken": {"address": mint},
    "quoteToken": {"address": quote},
    "priceUsd": str(price_usd),
    "priceNative": str(price_native),
    "liquidity": {"usd": liquidity_usd, "quote": quote_reserve},
  }


# What DexScreener's batch endpoint served for ZEC and PYTH on 2026-11-09, the
# numbers as returned. Both pools are quoted in a token DexScreener converts to
# USD by its own estimate, and the estimate was wrong: AVEN made 0.24 ZEC read
# as $2.76M of liquidity at $5.77M a coin, and JUP came out at $1,102.
ZEC_AVEN = _pair(ZEC, "AVENmint", 5765918.24, 9384078.9204, 2227707, 2762327.6)
PYTH_JUP = _pair(PYTH, JUP, 286.75, 0.2601, 40988, 209838321.55)
# The same tokens' real pools from their full pool lists.
ZEC_SOL = _pair(ZEC, WSOL, 1234.61, 14.1406, 34653, 3946765.71)
ZEC_USDC = _pair(ZEC, USDC, 1233.48, 1233.4836, 1610600, 3971595.25)
PYTH_SOL = _pair(PYTH, WSOL, 0.06123, 0.0007013, 2264.2326, 362052.77)


def test_pick_prices_ignores_pools_not_quoted_in_sol_usdc_usdt():
  assert ammo.pick_prices([ZEC_AVEN, PYTH_JUP], [ZEC, PYTH]) == {}


def test_pick_prices_ranks_by_the_reference_side_not_liquidity_usd():
  # A thin SOL pool quoting a fantasy price. liquidity.usd values the ZEC side at
  # that price and claims $5M; only 0.5 SOL is really in it.
  thin = _pair(ZEC, WSOL, 5765918.24, 66037.0, 0.5, 5_000_000)
  out = ammo.pick_prices([thin, ZEC_USDC, ZEC_SOL], [ZEC])
  assert out[ZEC]["usd"] == 1234.61
  # 34,653 SOL at the pool's implied ~$87.31 beats 1.61M USDC.
  assert round(out[ZEC]["depthUsd"]) == round(34653 * 1234.61 / 14.1406)


def test_pick_prices_skips_strangers_and_pools_it_cannot_size():
  no_reserve = _pair(WBTC, WSOL, 75000, 859.5, None, 1_696_822)
  pairs = [
    _pair("Stranger", USDC, 1, 1, 10, 20),
    {"baseToken": {"address": USDC}, "quoteToken": {"address": WSOL}, "priceUsd": None, "liquidity": {"usd": 5}},
    _pair(WBTC, WSOL, 75000, 0, 17282, 1_696_822),
    no_reserve,
  ]
  assert ammo.pick_prices(pairs, [USDC, WBTC]) == {}


class _Response:
  def __init__(self, body):
    self.body = body

  def raise_for_status(self):
    pass

  def json(self):
    return self.body


BATCH_API = "https://dex.test/tokens/"
PAIRS_API = "https://dex.test/token-pairs/"


class _FakeDex:
  """Stands in for requests.get: one pool per token from the batch endpoint,
  the whole list from the per-token one - as DexScreener behaves."""

  def __init__(self, batch, per_token):
    self.batch = batch
    self.per_token = per_token
    self.urls = []

  def __call__(self, url, timeout=None, headers=None):
    self.urls.append(url)
    if url.startswith(BATCH_API):
      wanted = url[len(BATCH_API):].split(",")
      return _Response([p for p in self.batch if p["baseToken"]["address"] in wanted])
    return _Response(self.per_token[url[len(PAIRS_API):]])


def test_fetch_prices_looks_past_a_batch_pick_quoted_in_something_else(monkeypatch):
  usdc_sol = _pair(USDC, WSOL, 1.003, 0.01148, 15618, 1552477.94)
  fake = _FakeDex([ZEC_AVEN, usdc_sol], {ZEC: [ZEC_AVEN, ZEC_USDC, ZEC_SOL]})
  monkeypatch.setattr(ammo.requests, "get", fake)

  out = ammo.fetch_prices([ZEC, USDC, DUST], price_api=BATCH_API, pairs_api=PAIRS_API)

  assert out[ZEC]["usd"] == 1234.61
  assert out[USDC]["usd"] == 1.003
  # Only ZEC needed its own pool list. USDC's batch pick was usable, and a token
  # the batch returned nothing for has no indexed pool to go looking for.
  assert [u for u in fake.urls if u.startswith(PAIRS_API)] == [PAIRS_API + ZEC]
  assert DUST not in out


def test_fetch_prices_retries_a_lookup_that_fails_once(monkeypatch):
  # 1 of 58 lookups failed at the connection level when timed from the VPS; one
  # such blip must not throw away the whole reading.
  dex = _FakeDex([ZEC_AVEN], {ZEC: [ZEC_SOL]})
  failures = [ammo.requests.ConnectionError("connection reset")]

  def flaky(url, timeout=None, headers=None):
    if url.startswith(PAIRS_API) and failures:
      raise failures.pop()
    return dex(url, timeout, headers)

  monkeypatch.setattr(ammo.requests, "get", flaky)
  out = ammo.fetch_prices([ZEC], price_api=BATCH_API, pairs_api=PAIRS_API)
  assert out[ZEC]["usd"] == 1234.61


def test_fetch_prices_gives_up_once_the_lookups_run_past_their_budget(monkeypatch):
  fake = _FakeDex([ZEC_AVEN, PYTH_JUP], {ZEC: [ZEC_SOL], PYTH: [PYTH_SOL]})
  monkeypatch.setattr(ammo.requests, "get", fake)
  clock = iter([0.0, 0.0, 31.0])  # budget starts, ZEC goes out in time, PYTH would not
  monkeypatch.setattr(ammo, "time", SimpleNamespace(monotonic=lambda: next(clock)))

  with pytest.raises(ApiError, match="1 mints left"):
    ammo.fetch_prices([ZEC, PYTH], price_api=BATCH_API, pairs_api=PAIRS_API, budget_s=30)


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


def test_build_ammo_values_a_holding_at_most_at_its_pools_depth():
  # 100 ZEC at $1,234 is $123k on paper, but the pool pricing it holds $50k of
  # SOL - all that selling into it could ever bring back.
  prices = {ZEC: {"usd": 1234.0, "depthUsd": 50_000.0}, USDC: {"usd": 1.0, "depthUsd": 1e6}}
  out = ammo.build_ammo({ZEC: 100.0, USDC: 10.0}, {ZEC: "ZEC", USDC: "USDC"}, prices,
                        sol_lamports=0, stonk_mint=STONK, observed_at="x")
  rows = {r["symbol"]: r for r in out["quoteRows"]}
  assert rows["ZEC"]["usd"] == 50_000.0
  assert rows["ZEC"]["capped"] is True
  assert rows["USDC"]["usd"] == 10.0
  assert "capped" not in rows["USDC"]
  assert out["quoteUsd"] == 50_010.0


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


def test_history_rows_record_the_pricing_version():
  gauge = ammo.build_ammo({}, {}, {}, sol_lamports=0, stonk_mint=STONK, observed_at="2026-11-09T01:00:00.000Z")
  assert ammo.history_entry(gauge)["p"] == ammo.PRICING_VERSION


def test_build_payload_leaves_out_readings_priced_the_old_way(tmp_path):
  # Before reference-only pricing the level swung between ~$22k and $96M on
  # fantasy pool prices. Those rows stay in the log; they are just not plotted.
  path = tmp_path / "ammo_history.jsonl"
  ammo.append_history({"t": iso(at(1)), "q": 96_153_508.59, "s": 0.0, "k": 0.0, "n": 1, "u": 0}, path)
  ammo.append_history({"t": iso(at(2)), "q": 23_067.0, "s": 0.0, "k": 0.0, "n": 1, "u": 0,
                       "p": ammo.PRICING_VERSION}, path)
  payload = ammo.build_payload({"quoteRows": []}, history_path=path, window_days=7, now_ms=at(3))
  assert [h[1] for h in payload["history"]] == [23_067.0]
  assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_build_payload_trims_rows_and_windows_history(tmp_path):
  path = tmp_path / "ammo_history.jsonl"
  for d in range(10):
    ammo.append_history({"t": iso(at(0) - d * 86400000), "q": float(d), "s": 0.0, "k": 0.0, "n": 1, "u": 0,
                         "p": ammo.PRICING_VERSION}, path)
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
