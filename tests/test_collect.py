"""The cross-check block exists to catch the platform's counters disagreeing.

Its token-side figure used to be published as `boughtBackTokens - burned` and read
as "bought but not yet burned". That only held while the buyback was the only way
a token reached the fire. Fees on pools quoted in the token burn directly, and the
flywheel buys on its own budget, so burned outgrew bought and the number went
negative under a label that could not describe it. These tests pin the corrected
direction and the reason for it.
"""

import pytest

from stonk import collect


HISTORY = {"days": [
  {"date": "2026-09-27", "dailyHoldersRevenue": 100.0},
  {"date": "2026-09-28", "dailyHoldersRevenue": 50.0},
]}


def revenue(**overrides):
  base = {
    "totalRevenueUsd": 1000.0,
    "platformPairExcludedUsd": 90.0,
    "totalBuybackUsd": 600.0,
    "boughtBackValueUsd": 590.0,
    "boughtBackTokens": 1000.0,
  }
  base.update(overrides)
  return base


def totals(**overrides):
  base = {"amountTokens": 1200.0, "valueUsdAtBurn": 700.0}
  base.update(overrides)
  return base


def test_non_buyback_burns_are_positive_when_other_paths_burn():
  """Burned beyond bought is the signature of the direct-burn paths."""
  result = collect.cross_check_usd(HISTORY, revenue(), totals())
  assert result["nonBuybackBurnedTokens"] == pytest.approx(200.0)


def test_buyback_only_platform_reports_a_buffer_as_negative():
  """With no other path, bought exceeds burned by whatever is still in the
  wallet - so the figure goes negative. That is the buffer, and the label says
  "non-buyback burns", which is why it is not reported as one."""
  result = collect.cross_check_usd(HISTORY, revenue(), totals(amountTokens=980.0))
  assert result["nonBuybackBurnedTokens"] == pytest.approx(-20.0)


def test_old_key_is_gone():
  """The retired name must not linger: the page falls back to deriving the value
  when it is absent, and a stale key would silently win over that fallback."""
  result = collect.cross_check_usd(HISTORY, revenue(), totals())
  assert "boughtNotYetBurnedTokens" not in result


def test_platform_pair_excluded_is_passed_through():
  result = collect.cross_check_usd(HISTORY, revenue(), totals())
  assert result["platformPairExcludedUsd"] == pytest.approx(90.0)


def test_missing_platform_pair_excluded_is_none_not_zero():
  """A field the API stopped sending is unknown, not zero; the page hides the
  row on None and would otherwise print a confident $0."""
  payload = revenue()
  del payload["platformPairExcludedUsd"]
  assert collect.cross_check_usd(HISTORY, payload, totals())["platformPairExcludedUsd"] is None


def test_holders_revenue_sums_the_daily_series():
  assert collect.cross_check_usd(HISTORY, revenue(), totals())["historyHoldersRevenueSum"] == 150.0


def test_missing_burn_amount_does_not_raise():
  """burn_totals came from the API; a missing amount must degrade, not crash the
  whole fetch."""
  result = collect.cross_check_usd(HISTORY, revenue(), {"valueUsdAtBurn": 700.0})
  assert result["nonBuybackBurnedTokens"] == pytest.approx(-1000.0)


def test_source_mix_groups_every_source():
  burns = [
    {"source": "buyback", "amountTokens": 10.0, "valueUsdAtBurn": 3.0},
    {"source": "quote-revenue", "amountTokens": 2.0, "valueUsdAtBurn": 1.0},
    {"source": "buyback", "amountTokens": 5.0, "valueUsdAtBurn": 2.0},
  ]
  mix = {row["source"]: row for row in collect.source_mix(burns)}
  assert mix["buyback"]["count"] == 2
  assert mix["buyback"]["amountTokens"] == pytest.approx(15.0)
  assert mix["quote-revenue"]["count"] == 1


def test_source_mix_keeps_unnamed_sources():
  """A source the API adds later still has to be counted, under its own key."""
  mix = collect.source_mix([{"amountTokens": 1.0, "valueUsdAtBurn": 1.0}])
  assert mix[0]["source"] == "unknown"
