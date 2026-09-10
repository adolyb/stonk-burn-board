"""The whole point of hourly.py is telling "quiet" apart from "not observed",
so most of these tests are about coverage holes rather than arithmetic.
"""

import json
from datetime import datetime, timezone

import pytest

from stonk import hourly

HOUR = 3600 * 1000


def at(hour, minute=0):
  """Epoch ms for 2026-09-08 <hour>:<minute> UTC."""
  return int(datetime(2026, 9, 8, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def iso(ms):
  return (datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
          .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


@pytest.fixture
def ledger_dir(tmp_path):
  """Writes a burn ledger + coverage file and returns a build() bound to them."""
  burns = tmp_path / "burns.jsonl"
  coverage = tmp_path / "coverage.json"

  def write(events, segments):
    burns.write_text(
      "".join(json.dumps({"id": f"sig{i}", "t": iso(ms), "a": a, "u": u, "s": s}) + "\n"
              for i, (ms, a, u, s) in enumerate(events)),
      encoding="utf-8",
    )
    coverage.write_text(
      json.dumps({"burns": [[iso(a), iso(b)] for a, b in segments]}), encoding="utf-8"
    )

    def build(**kwargs):
      kwargs.setdefault("now_ms", at(23, 59))
      kwargs.setdefault("window_days", 7)
      return hourly.build_hourly(burn_path=burns, coverage_path=coverage, **kwargs)

    return build

  return write


def test_empty_ledger_is_all_zeros(tmp_path):
  out = hourly.build_hourly(
    burn_path=tmp_path / "missing.jsonl",
    coverage_path=tmp_path / "missing.json",
    window_days=7,
    now_ms=at(12),
  )
  assert out["bins"] == []
  assert out["events"] == 0
  assert out["coverageHours"] == 0
  assert out["totals"]["meanPerHour"] == 0.0
  assert len(out["hod"]) == 24
  assert all(row["s"] == 0 for row in out["hod"])


def test_full_hour_becomes_a_bin(ledger_dir):
  build = ledger_dir(
    [(at(1, 10), 100.0, 5.0, "buyback"), (at(1, 40), 50.0, 2.0, "quote-revenue")],
    [(at(0), at(3))],
  )
  out = build()
  assert [b["t"] for b in out["bins"]] == ["2026-09-08T00:00Z", "2026-09-08T01:00Z", "2026-09-08T02:00Z"]
  hour1 = next(b for b in out["bins"] if b["t"] == "2026-09-08T01:00Z")
  assert out["sources"] == ["buyback", "quote-revenue"]
  assert hour1["a"] == [100.0, 50.0]
  assert hour1["u"] == 7.0
  assert hour1["n"] == 2


def test_partial_hour_is_excluded_from_bins_but_counted_in_hod(ledger_dir):
  # Coverage starts mid-hour: 05:00 is only half observed, so it must not appear
  # as a bin - but its events and its 1800 observed seconds still belong to hod.
  build = ledger_dir([(at(5, 45), 900.0, 9.0, "buyback")], [(at(5, 30), at(7))])
  out = build()

  assert [b["t"] for b in out["bins"]] == ["2026-09-08T06:00Z"]
  hod5 = out["hod"][5]
  assert hod5["s"] == 1800.0
  assert hod5["a"] == [900.0]
  assert hod5["n"] == 1
  # 900 tokens over half an hour is a 1800/h rate, not 900/h.
  assert out["coverageHours"] == pytest.approx(1.5)
  assert out["totals"]["meanPerHour"] == pytest.approx(600.0)


def test_gap_between_segments_produces_no_bins(ledger_dir):
  build = ledger_dir(
    [(at(1, 5), 10.0, 1.0, "buyback"), (at(9, 5), 20.0, 2.0, "buyback")],
    [(at(1), at(2)), (at(9), at(10))],
  )
  out = build()
  assert [b["t"] for b in out["bins"]] == ["2026-09-08T01:00Z", "2026-09-08T09:00Z"]
  # The six untouched hours in between are unknown, not zero.
  assert all(out["hod"][h]["s"] == 0 for h in range(3, 9))


def test_an_hour_split_across_two_segments_is_not_full(ledger_dir):
  # 04:00-04:20 and 04:40-05:00 observed: 20 minutes were missed inside the hour,
  # so it is not a full hour even though both edges are covered.
  build = ledger_dir(
    [(at(4, 10), 5.0, 1.0, "buyback")],
    [(at(4), at(4, 20)), (at(4, 40), at(5))],
  )
  out = build()
  assert out["bins"] == []
  assert out["hod"][4]["s"] == pytest.approx(2400.0)


def test_window_clips_old_events_and_coverage(ledger_dir):
  old = at(1) - 30 * 24 * HOUR
  build = ledger_dir(
    [(old, 999.0, 99.0, "buyback"), (at(1, 5), 10.0, 1.0, "buyback")],
    [(old, old + HOUR), (at(1), at(2))],
  )
  out = build(window_days=7)
  assert out["events"] == 1
  assert [b["t"] for b in out["bins"]] == ["2026-09-08T01:00Z"]
  assert out["coverageHours"] == pytest.approx(1.0)
  assert len(out["coverage"]) == 1


def test_hod_is_utc_and_unshifted(ledger_dir):
  build = ledger_dir([(at(16, 30), 42.0, 4.0, "buyback")], [(at(16), at(17))])
  out = build()
  assert out["hod"][16]["a"] == [42.0]
  assert sum(sum(row["a"]) for row in out["hod"]) == 42.0


def test_totals_track_the_full_hour_bins(ledger_dir):
  build = ledger_dir(
    [(at(1, 5), 300.0, 3.0, "buyback"),
     (at(2, 5), 100.0, 1.0, "buyback"),
     (at(3, 5), 200.0, 2.0, "buyback")],
    [(at(1), at(4))],
  )
  out = build()
  assert out["totals"]["fullHours"] == 3
  assert out["totals"]["min"] == 100.0
  assert out["totals"]["median"] == 200.0
  assert out["totals"]["max"] == 300.0
  assert out["totals"]["meanPerHour"] == pytest.approx(200.0)


def test_unknown_source_still_gets_a_slot(ledger_dir):
  build = ledger_dir([(at(1, 5), 7.0, 0.0, None)], [(at(1), at(2))])
  out = build()
  assert out["sources"] == ["unknown"]
  assert out["bins"][0]["a"] == [7.0]


def test_save_hourly_writes_minified_json(tmp_path):
  path = hourly.save_hourly({"a": 1, "b": [1, 2]}, path=tmp_path / "sub" / "hourly.json")
  text = path.read_text(encoding="utf-8")
  assert text == '{"a":1,"b":[1,2]}'


def test_overlapping_coverage_is_not_double_counted(ledger_dir):
  # coverage.json is merged per stream today, but nothing in the file format
  # guarantees it. Two segments describing the same hour are one observed hour.
  build = ledger_dir(
    [(at(1, 5), 300.0, 3.0, "buyback")],
    [(at(1), at(2)), (at(1), at(2)), (at(1, 30), at(2, 30))],
  )
  out = build()
  assert out["coverageHours"] == pytest.approx(1.5)
  assert out["hod"][1]["s"] == pytest.approx(3600.0)
  assert out["totals"]["meanPerHour"] == pytest.approx(200.0)
  # And the hour still counts once as a bin, not three times.
  assert [b["t"] for b in out["bins"]] == ["2026-09-08T01:00Z"]
