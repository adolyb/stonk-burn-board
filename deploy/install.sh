#!/usr/bin/env bash
# Bootstrap the 24/7 collector on a fresh Debian/Ubuntu host.
#
#   ssh root@<host> 'bash -s' < deploy/install.sh
#
# Idempotent: safe to re-run after a code change to pick up new units.
set -euo pipefail

REPO="${STONK_REPO:-https://github.com/adolyb/stonk-burn-board.git}"
DIR="${STONK_DIR:-/opt/stonk}"

apt-get update -qq
apt-get install -y -qq python3-venv git >/dev/null

if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch --quiet origin
  git -C "$DIR" reset --hard --quiet origin/master
else
  git clone --quiet "$REPO" "$DIR"
fi

cd "$DIR"
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

echo "installed. next:"
echo "  1. write $DIR/.env  (STONK_RPC_URL=... for a private RPC)"
echo "  2. give the host push rights:  gh auth login  or a deploy key"
echo "  3. systemctl list-timers 'stonk-*'"
