"""Hourly burn aggregates, derived from the full local ledger.

`intraday` in the snapshot only carries a trailing 48h of raw events, because the
page embeds them one by one. Any question about the *shape of a day* needs more
history than that, but not the individual events - so this module folds the whole
ledger down to hour buckets, which stay small enough to publish forever.

Two products, and the difference between them is the point:

  bins  every clock hour that sits entirely inside an observed coverage segment.
        A partial hour is excluded, because a bin that only saw 20 minutes would
        read as a quiet hour rather than a half-observed one.
  hod   the same events folded onto hour-of-day, divided by how many seconds of
        that hour-of-day were actually observed. Partial hours DO count here,
        numerator and denominator together, so nothing is thrown away.

Everything is UTC. A viewer in another whole-hour zone rotates `hod` by its
offset; that is why the buckets are published unshifted rather than pre-localised.
"""

import json
from datetime import datetime, timezone

from . import config, ledger

HOUR_MS = 3600 * 1000


def _epoch_ms(iso):
  return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _iso_hour(ms):
  return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:00Z")


def _iso(ms):
  return (datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
          .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


def _hour_of(ms):
  return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).hour


def _clip(segments_ms, since_ms, until_ms):
  """Coverage segments clipped to the window, then merged.

  ledger.merge_coverage already keeps each stream disjoint on disk, but the file
  format does not promise it - and overlap here would inflate the denominator, so
  a double-counted hour would read as half the burn rate it really was.
  """
  clipped = []
  for a, b in segments_ms:
    a, b = max(a, since_ms), min(b, until_ms)
    if b > a:
      clipped.append([a, b])

  merged = []
  for a, b in sorted(clipped):
    if merged and a <= merged[-1][1]:
      merged[-1][1] = max(merged[-1][1], b)
    else:
      merged.append([a, b])
  return merged


def _hod_seconds(segments_ms):
  """Observed seconds per UTC hour-of-day - the denominator for the hod means."""
  secs = [0.0] * 24
  for a, b in segments_ms:
    cur = a
    while cur < b:
      nxt = min(cur - cur % HOUR_MS + HOUR_MS, b)
      secs[_hour_of(cur)] += (nxt - cur) / 1000
      cur = nxt
  return secs


def _full_hours(segments_ms):
  """Every clock hour a single segment covers end to end, ascending.

  Driven by coverage rather than by the events, so an hour that was watched and
  saw nothing still emits a bin: that zero is an observation. An hour straddling
  two segments never qualifies - the hole inside it is exactly what disqualifies it.
  """
  hours = set()
  for a, b in segments_ms:
    start = a - a % HOUR_MS
    if start < a:
      start += HOUR_MS
    while start + HOUR_MS <= b:
      hours.add(start)
      start += HOUR_MS
  return sorted(hours)


def build_hourly(burn_path=None, coverage_path=None, window_days=None, now_ms=None):
  """Fold the burn ledger into hour buckets over a trailing window."""
  burn_path = burn_path or config.BURN_LEDGER_PATH
  coverage_path = coverage_path or config.COVERAGE_PATH
  window_days = window_days or config.HOURLY_WINDOW_DAYS
  if now_ms is None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
  since_ms = now_ms - window_days * 24 * HOUR_MS

  events = ledger.load_events(burn_path, since_ms)
  raw_coverage = ledger.read_coverage(coverage_path).get("burns") or []
  segments = _clip([[_epoch_ms(a), _epoch_ms(b)] for a, b in raw_coverage], since_ms, now_ms)

  # Source names come from the API and are not fixed; publish the order once and
  # let every bucket be a plain array against it.
  sources = sorted({e.get("s") or "unknown" for e in events})
  index = {name: i for i, name in enumerate(sources)}

  def _empty():
    return [0.0] * len(sources)

  bins_by_hour, hod_amounts = {}, [_empty() for _ in range(24)]
  hod_usd, hod_events = [0.0] * 24, [0] * 24

  for event in events:
    ms = _epoch_ms(event["t"])
    slot = index[event.get("s") or "unknown"]
    amount = event.get("a") or 0.0
    usd = event.get("u") or 0.0

    bucket = bins_by_hour.setdefault(ms - ms % HOUR_MS, {"a": _empty(), "u": 0.0, "n": 0})
    bucket["a"][slot] += amount
    bucket["u"] += usd
    bucket["n"] += 1

    hour = _hour_of(ms)
    hod_amounts[hour][slot] += amount
    hod_usd[hour] += usd
    hod_events[hour] += 1

  empty = {"a": _empty(), "u": 0.0, "n": 0}
  bins = []
  for start in _full_hours(segments):
    bucket = bins_by_hour.get(start, empty)
    bins.append({
      "t": _iso_hour(start),
      "a": [round(v, 3) for v in bucket["a"]],
      "u": round(bucket["u"], 2),
      "n": bucket["n"],
    })

  seconds = _hod_seconds(segments)
  hod = [
    {
      "utc": hour,
      "s": round(seconds[hour], 1),
      "n": hod_events[hour],
      "a": [round(v, 3) for v in hod_amounts[hour]],
      "u": round(hod_usd[hour], 2),
    }
    for hour in range(24)
  ]

  totals = sorted(sum(b["a"]) for b in bins)
  covered_hours = sum(seconds) / 3600
  tokens = sum(sum(row["a"]) for row in hod)
  usd_total = sum(row["u"] for row in hod)

  return {
    "generatedAt": _iso(now_ms),
    "windowDays": window_days,
    "since": _iso(since_ms),
    "sources": sources,
    "coverage": [[_iso(a), _iso(b)] for a, b in segments],
    "coverageHours": round(covered_hours, 3),
    "events": len(events),
    "bins": bins,
    "hod": hod,
    "totals": {
      "tokens": round(tokens, 3),
      "usd": round(usd_total, 2),
      "meanPerHour": round(tokens / covered_hours, 3) if covered_hours else 0.0,
      "meanUsdPerHour": round(usd_total / covered_hours, 2) if covered_hours else 0.0,
      "fullHours": len(bins),
      "median": totals[len(totals) // 2] if totals else 0.0,
      "min": totals[0] if totals else 0.0,
      "max": totals[-1] if totals else 0.0,
    },
  }


def save_hourly(payload, path=None):
  """Minified: this file is fetched on every page load, same as live.json."""
  path = path or config.HOURLY_PATH
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
  return path
