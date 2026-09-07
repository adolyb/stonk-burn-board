"""CLI entry point for the STONK burn dashboard.

  python main.py            # fetch fresh data, then rebuild the dashboard
  python main.py fetch      # fetch only (also appends one reconciliation row)
  python main.py build      # rebuild the HTML from the saved snapshot
"""

import argparse
import sys

from stonk import collect, config, render


def cmd_fetch(_args):
  snapshot = collect.collect()
  path = collect.save_snapshot(snapshot)
  recon = snapshot["recon"]
  print(f"snapshot   -> {path}")
  print(f"supply      = {recon['supply']:,.6f} STONK  (slot {recon['slot']})")
  print(f"burned/chain= {recon['chainBurned']:,.6f} ({recon['burnedPctOfInitial']:.3f}% of initial)")
  print(f"burned/api  = {recon['apiBurned']:,.6f}")
  print(f"delta       = {recon['deltaTokens']:+,.6f} STONK  [{recon['direction']}]")
  if snapshot["rateLimitRemaining"] is not None:
    print(f"rate limit remaining: {snapshot['rateLimitRemaining']}")
  return snapshot


def cmd_build(_args):
  snapshot = collect.load_snapshot()
  path = render.render(snapshot)
  print(f"dashboard  -> {path}")
  return snapshot


def cmd_all(args):
  cmd_fetch(args)
  return cmd_build(args)


def main(argv=None):
  parser = argparse.ArgumentParser(description="STONK burn dashboard")
  parser.add_argument(
    "command",
    nargs="?",
    default="all",
    choices=["all", "fetch", "build"],
    help="all (default): fetch then build",
  )
  args = parser.parse_args(argv)

  handlers = {"all": cmd_all, "fetch": cmd_fetch, "build": cmd_build}
  try:
    handlers[args.command](args)
  except FileNotFoundError:
    print(f"No snapshot at {config.SNAPSHOT_PATH}. Run: python main.py fetch", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
