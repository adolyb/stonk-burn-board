#!/usr/bin/env bash
# Bootstrap the 24/7 collector on a fresh Debian/Ubuntu host.
#
#   ssh root@<host> 'bash -s' < deploy/install.sh
#
# Idempotent: safe to re-run after a code change to pick up new units.
set -euo pipefail

REPO="${STONK_REPO:-git@github.com:adolyb/stonk-burn-board.git}"
DIR="${STONK_DIR:-/opt/stonk}"
# The ledger cannot be re-fetched from the API, so it lives outside the checkout:
# the reset --hard below would otherwise throw away everything collected so far.
DATA="${STONK_DATA_DIR:-/var/lib/stonk}"

apt-get update -qq
apt-get install -y -qq python3-venv git >/dev/null

if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch --quiet origin
  git -C "$DIR" reset --hard --quiet origin/master
else
  git clone --quiet "$REPO" "$DIR"
fi

cd "$DIR"

mkdir -p "$DATA"
# First install only: carry the ledger committed in the repo over to its real home
# rather than starting the coverage record from scratch.
for f in burns.jsonl buybacks.jsonl coverage.json recon_history.jsonl snapshot.json; do
  [ -e "$DATA/$f" ] || [ ! -e "$DIR/data/$f" ] || cp "$DIR/data/$f" "$DATA/$f"
done

# EnvironmentFile is read by systemd, so this has to be a plain KEY=VALUE file.
if [ ! -e "$DIR/.env" ]; then
  printf 'STONK_DATA_DIR=%s
' "$DATA" > "$DIR/.env"
fi
grep -q '^STONK_DATA_DIR=' "$DIR/.env" || printf 'STONK_DATA_DIR=%s
' "$DATA" >> "$DIR/.env"

[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

# The collector pushes as a bot, not as a person: the commit author on the live
# branch is machine output, and mislabelling it as the maintainer would be a lie
# in `git log`.
git config user.name "stonk-collector"
git config user.email "stonk-collector@users.noreply.github.com"

install -m 644 deploy/stonk-fetch.service   /etc/systemd/system/
install -m 644 deploy/stonk-fetch.timer     /etc/systemd/system/
install -m 644 deploy/stonk-publish.service /etc/systemd/system/
install -m 644 deploy/stonk-publish.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now stonk-fetch.timer stonk-publish.timer

echo "installed."
echo "  ledger    $DATA"
echo "  env       $DIR/.env   (add STONK_RPC_URL=... to stop using the public RPC)"
echo "  timers    systemctl list-timers 'stonk-*'"
echo "  logs      journalctl -u stonk-fetch -u stonk-publish -f"
