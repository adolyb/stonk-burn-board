#!/usr/bin/env bash
# Publish data/live.json and data/hourly.json onto the `live` branch, which the
# deployed page fetches.
#
# The branch is deliberately kept at exactly one commit (amend + force push): the
# payload is rewritten every few minutes, and keeping that as history would grow
# the repository by ~100KB per cycle forever, for data nobody ever reads twice.
#
# It is an orphan branch so the published JSON shares no history with the source
# tree - a force push here can never rewrite code.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKTREE="${STONK_LIVE_WORKTREE:-$ROOT/.live}"
PYTHON="${STONK_PYTHON:-$ROOT/.venv/bin/python}"
REMOTE="${STONK_GIT_REMOTE:-origin}"
cd "$ROOT"

"$PYTHON" main.py publish

if [ ! -e "$WORKTREE/.git" ]; then
  git worktree prune
  if git show-ref --quiet "refs/heads/live"; then
    git worktree add "$WORKTREE" live
  else
    # --orphan needs git >= 2.42; the fallback does the same thing by hand.
    git worktree add --orphan -B live "$WORKTREE" 2>/dev/null || {
      git worktree add --detach "$WORKTREE"
      git -C "$WORKTREE" checkout --orphan live
      git -C "$WORKTREE" rm -rf --cached . >/dev/null 2>&1 || true
      find "$WORKTREE" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
    }
  fi
fi

# Ask the package where the payload landed: STONK_DATA_DIR moves it off the
# checkout on servers, so hardcoding $ROOT/data here would publish a stale file.
LIVE_JSON="$("$PYTHON" -c 'from stonk import config; print(config.LIVE_PATH)')"
HOURLY_JSON="$("$PYTHON" -c 'from stonk import config; print(config.HOURLY_PATH)')"
mkdir -p "$WORKTREE/data"
cp "$LIVE_JSON" "$WORKTREE/data/live.json"
cp "$HOURLY_JSON" "$WORKTREE/data/hourly.json"

cd "$WORKTREE"
git add data/live.json data/hourly.json
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  git commit -q --amend -m "data: live.json @ $STAMP"
else
  git commit -q -m "data: live.json @ $STAMP"
fi
git push -q --force "$REMOTE" live
echo "published live.json @ $STAMP"
