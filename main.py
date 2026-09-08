"""CLI entry point for the STONK burn dashboard.

  python main.py                 # fetch fresh data, then rebuild the dashboard
  python main.py fetch           # fetch only (also appends one reconciliation row)
  python main.py build           # rebuild the HTML from the saved snapshot
  python main.py watch           # poll on an interval to accumulate intraday history
  python main.py publish         # write data/live.json for the 24/7 collector to push
"""

import argparse
import sys
import time

from stonk import collect, config, render


def _report_fetch(snapshot):
  recon = snapshot["recon"]
  added = snapshot["ledgerUpdate"]["added"]
  intraday = snapshot["intraday"]["totals"]
  print(f"supply      = {recon['supply']:,.6f} STONK  (slot {recon['slot']})")
  print(f"burned/chain= {recon['chainBurned']:,.6f} ({recon['burnedPctOfInitial']:.3f}% of initial)")
  print(f"burned/api  = {recon['apiBurned']:,.6f}")
  print(f"delta       = {recon['deltaTokens']:+,.6f} STONK  [{recon['direction']}]")
  print(f"ledger      + {added['burns']} burns, + {added['buybacks']} buybacks"
        f"  (window: {intraday['burnEvents']} burns / {intraday['buybackEvents']} buybacks)")

  # A page that arrived entirely unseen means older records rotated out before we
  # polled: the intraday series has a hole, and the board will draw it as one.
  behind = [k for k, v in snapshot["ledgerUpdate"]["pageFullyNew"].items() if v]
  if behind:
    print(f"WARNING     polling fell behind on: {', '.join(behind)} — shorten STONK_WATCH_INTERVAL",
          file=sys.stderr)


def cmd_fetch(_args):
  snapshot = collect.collect()
  path = collect.save_snapshot(snapshot)
  print(f"snapshot   -> {path}")
  _report_fetch(snapshot)
  if snapshot["rateLimitRemaining"] is not None:
    print(f"rate limit remaining: {snapshot['rateLimitRemaining']}")
  return snapshot


def cmd_publish(_args):
  """Write data/live.json from the newest snapshot for the collector to push."""
  snapshot = collect.load_snapshot()
  path = collect.save_live(snapshot)
  size_kb = path.stat().st_size / 1024
  print(f"live       -> {path}  ({size_kb:,.0f} KB, generatedAt {snapshot['generatedAt']})")
  return snapshot


def cmd_build(_args):
  snapshot = collect.load_snapshot()
  path = render.render(snapshot)
  print(f"dashboard  -> {path}")
  return snapshot


def cmd_all(args):
  cmd_fetch(args)
  return cmd_build(args)


def cmd_watch(args):
  interval = args.interval or config.WATCH_INTERVAL
  print(f"watching every {interval}s — Ctrl+C to stop")
  try:
    while True:
      started = time.time()
      try:
        snapshot = collect.collect()
        collect.save_snapshot(snapshot)
        render.render(snapshot)
        stamp = snapshot["generatedAt"][11:19]
        added = snapshot["ledgerUpdate"]["added"]
        print(f"[{stamp}] +{added['burns']} burns  +{added['buybacks']} buybacks  "
              f"delta {snapshot['recon']['deltaTokens']:+,.2f}")
      except Exception as exc:  # keep the loop alive across transient API errors
        print(f"[error] {exc}", file=sys.stderr)
      time.sleep(max(1.0, interval - (time.time() - started)))
  except KeyboardInterrupt:
    print("\nstopped")


def main(argv=None):
  parser = argparse.ArgumentParser(description="STONK burn dashboard")
  parser.add_argument(
    "command",
    nargs="?",
    default="all",
    choices=["all", "fetch", "build", "watch", "publish"],
    help="all (default): fetch then build",
  )
  parser.add_argument("--interval", type=int, default=None, help="watch poll interval in seconds")
  args = parser.parse_args(argv)

  handlers = {
    "all": cmd_all,
    "fetch": cmd_fetch,
    "build": cmd_build,
    "watch": cmd_watch,
    "publish": cmd_publish,
  }
  try:
    handlers[args.command](args)
  except FileNotFoundError:
    print(f"No snapshot at {config.SNAPSHOT_PATH}. Run: python main.py fetch", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
