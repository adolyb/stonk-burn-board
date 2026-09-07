"""Append-only local event ledger for intraday views.

The API pages both burns and buybacks at 100 records, which at current activity
is roughly 25 minutes of history and cannot be backfilled. Anything intraday has
to be accumulated locally: every fetch merges the newest page into a JSONL file,
deduplicated by signature.

Because polling can fall behind a burst, the ledger also tracks which time ranges
were actually observed. A bin with no events inside an observed range is a real
zero; a bin inside a gap is unknown, and the dashboard must not draw them alike.
"""

import json
from datetime import datetime, timezone

from . import config


def _epoch_ms(iso):
  if not iso:
    return None
  return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _iso(ms):
  return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_events(path, since_ms=None):
  """Read the ledger, oldest first, optionally clipped to a trailing window."""
  if not path.exists():
    return []
  rows = []
  with path.open(encoding="utf-8") as handle:
    for line in handle:
      line = line.strip()
      if not line:
        continue
      row = json.loads(line)
      if since_ms is not None and _epoch_ms(row.get("t")) < since_ms:
        continue
      rows.append(row)
  rows.sort(key=lambda r: r["t"])
  return rows


def _known_ids(path):
  ids = set()
  if not path.exists():
    return ids
  with path.open(encoding="utf-8") as handle:
    for line in handle:
      line = line.strip()
      if line:
        ids.add(json.loads(line).get("id"))
  return ids


def append_events(path, records):
  """Merge a page of normalised records into the ledger.

  Returns (added, page_oldest, page_newest, had_prior). had_prior separates a
  first run - where every record is legitimately new - from a poll that fell
  behind, where an all-new page means records rotated out unseen.
  """
  path.parent.mkdir(parents=True, exist_ok=True)
  records = [r for r in records if r.get("t") and r.get("id")]
  known = _known_ids(path)
  if not records:
    return 0, None, None, bool(known)

  records.sort(key=lambda r: r["t"])
  fresh = [r for r in records if r["id"] not in known]

  if fresh:
    with path.open("a", encoding="utf-8") as handle:
      for row in fresh:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")

  return len(fresh), records[0]["t"], records[-1]["t"], bool(known)


def merge_coverage(path, stream, start_iso, end_iso):
  """Record an observed interval and merge it into the stream's coverage.

  Two intervals join only when they actually overlap. A page whose oldest record
  is newer than everything seen so far leaves a real hole, and that hole survives
  as a separate segment instead of being papered over.
  """
  if not start_iso or not end_iso:
    return read_coverage(path).get(stream, [])

  data = {}
  if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))

  segments = [[_epoch_ms(a), _epoch_ms(b)] for a, b in data.get(stream, [])]
  segments.append([_epoch_ms(start_iso), _epoch_ms(end_iso)])
  segments.sort()

  merged = []
  for seg in segments:
    if merged and seg[0] <= merged[-1][1]:
      merged[-1][1] = max(merged[-1][1], seg[1])
    else:
      merged.append(seg)

  data[stream] = [[_iso(a), _iso(b)] for a, b in merged]
  path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
  return data[stream]


def read_coverage(path):
  if not path.exists():
    return {}
  return json.loads(path.read_text(encoding="utf-8"))


def normalise_burns(burns):
  """API burn rows -> ledger rows. Short keys: these accumulate fast."""
  return [
    {
      "id": b.get("signature"),
      "t": b.get("burnedAt"),
      "a": b.get("amountTokens") or 0.0,
      "u": b.get("valueUsdAtBurn") or 0.0,
      "s": b.get("source") or "unknown",
    }
    for b in burns
  ]


def normalise_buybacks(buybacks):
  """API buyback rows -> ledger rows.

  boughtValueUsd / boughtTokens is the price the treasury actually paid, which is
  the one intraday series the daily endpoint cannot express.
  """
  rows = []
  for b in buybacks:
    bought = b.get("boughtTokens") or 0.0
    rows.append({
      "id": b.get("signature"),
      "t": b.get("boughtAt"),
      "bt": bought,
      "bu": b.get("boughtValueUsd") or 0.0,
      "su": b.get("spentValueUsd") or 0.0,
      "q": (b.get("quote") or {}).get("symbol") or "?",
    })
  return rows


def update(burns, buybacks):
  """Merge both streams and return what the snapshot needs to describe them."""
  burn_rows = normalise_burns(burns)
  buyback_rows = normalise_buybacks(buybacks)

  burn_added, burn_from, burn_to, burn_prior = append_events(config.BURN_LEDGER_PATH, burn_rows)
  buy_added, buy_from, buy_to, buy_prior = append_events(config.BUYBACK_LEDGER_PATH, buyback_rows)

  coverage = {
    "burns": merge_coverage(config.COVERAGE_PATH, "burns", burn_from, burn_to),
    "buybacks": merge_coverage(config.COVERAGE_PATH, "buybacks", buy_from, buy_to),
  }

  return {
    "added": {"burns": burn_added, "buybacks": buy_added},
    "page": {
      "burns": [burn_from, burn_to],
      "buybacks": [buy_from, buy_to],
    },
    # A full page of unseen records on a ledger that already had history means the
    # poll fell behind: older records rotated out before we ever saw them.
    "pageFullyNew": {
      "burns": burn_prior and burn_added == len(burn_rows) and len(burn_rows) >= config.LIST_LIMIT,
      "buybacks": buy_prior and buy_added == len(buyback_rows) and len(buyback_rows) >= config.LIST_LIMIT,
    },
    "coverage": coverage,
  }


def build_intraday(window_hours=None, signature_rows=300):
  """Trailing window of both ledgers, trimmed for embedding in the page."""
  window_hours = window_hours or config.INTRADAY_WINDOW_HOURS
  now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
  since = now_ms - window_hours * 3600 * 1000

  burns = load_events(config.BURN_LEDGER_PATH, since)
  buybacks = load_events(config.BUYBACK_LEDGER_PATH, since)
  coverage = read_coverage(config.COVERAGE_PATH)

  # Signatures are 88 chars each; only the rows the table shows need them.
  for row in burns[:-signature_rows]:
    row.pop("id", None)
  for row in buybacks[:-signature_rows]:
    row.pop("id", None)

  return {
    "windowHours": window_hours,
    "generatedAtMs": now_ms,
    "burns": burns,
    "buybacks": buybacks,
    "coverage": coverage,
    "totals": {
      "burnEvents": len(burns),
      "burnTokens": sum(r["a"] for r in burns),
      "burnUsd": sum(r["u"] for r in burns),
      "buybackEvents": len(buybacks),
      "boughtTokens": sum(r["bt"] for r in buybacks),
      "spentUsd": sum(r["su"] for r in buybacks),
    },
  }
