#!/bin/sh
# usage: V=<version> [APP=1] [YES=1] tools/release.sh (make ship V=<version> does this). One Leela release, every step in order; each
# step is skipped when it is already done, so the command can always run again after a stop:
#   1. main is clean, pushed, and its CI passed        5. lock-publish: lock signed, on the test channel (asks for the key)
#   2. the GitHub release V exists (CHANGELOG notes)   6. you check an app on the test channel; YES=1 skips the question
#   3. the wheel for V is on that release              7. lock-promote: the stable channel points at it
#   4. a lock that pins V, tested fresh with extras    8. with APP=1 or no app-v<V> yet: ship-app (sign, notarize, cask)
# Steps 5 and 7 sign with ~/.ssh/leela_lock_ed25519 through the SSH agent: start one in this shell first (ssh-add --apple-use-keychain).
set -eu
: "${V:?Give the version: make ship V=<version>}"
echo "$V" | grep -qE '^[0-9]+(\.[0-9]+)+$' || { echo "V must be a version such as 1.0.1" >&2; exit 1; }
cd "$(dirname "$0")/.."
R=vedicreader/leela LOCKPY="uv run --frozen python tools/lock.py"
unset GITHUB_TOKEN GH_TOKEN   # the keyring of gh signs in; a stale token in the environment would win over it
say() { printf '\n== %s\n' "$*"; }
gitc() { git -c credential.helper= -c 'credential.helper=!gh auth git-credential' -c url.https://github.com/.insteadOf=git@github.com: "$@"; }

say "1. main is clean, pushed and green"
test "$(git branch --show-current)" = main || { echo "make ship runs on main" >&2; exit 1; }
grep -q "^__version__ = \"$V\"" leela/__init__.py || { echo "leela/__init__.py is not version $V" >&2; exit 1; }
test -z "$(git status --porcelain)" || { echo "the tree has changes or untracked files; commit them, or git stash push -u, then run again" >&2; exit 1; }
gitc fetch -q origin main
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" || { echo "main is not pushed (or is behind origin/main)" >&2; exit 1; }
head=$(git rev-parse HEAD)
ci=$(gh run list -R $R --commit "$head" --workflow test --json conclusion -q '.[0].conclusion' 2>/dev/null || true)
test "$ci" = success || { echo "CI for $head is '${ci:-not run}', not success; wait for it, then run again" >&2; exit 1; }

say "2. the release $V"
if gh release view "$V" -R $R >/dev/null 2>&1; then echo "release $V is there"
else
  notes=$(mktemp); sed -n "/^## $V\$/,/^## /p" CHANGELOG.md | sed '1d;$d' > "$notes"
  test -s "$notes" || { echo "CHANGELOG.md has no ## $V section" >&2; exit 1; }
  gh release create "$V" -R $R --target "$head" --title "v$V" --notes-file "$notes"
  gitc fetch -q --tags origin
fi

say "3. the wheel"
if gh release view "$V" -R $R --json assets -q '.assets[].name' | grep -qx "leela-$V-py3-none-any.whl"; then echo "the wheel is on release $V"
else $LOCKPY wheel "$V" --upload; fi

say "4. a lock for $V, tested"
if grep -q "\"leela==$V\"" packaging/lock/pyproject.toml && ls packaging/lock/tested/*.json >/dev/null 2>&1 && $LOCKPY check >/dev/null 2>&1; then echo "packaging/lock pins leela $V and is tested"
else
  test -x packaging/mac/build/uv/uv || make -C packaging/mac uv-fetch
  $LOCKPY make "$V"
  $LOCKPY test --fresh --extras
  git add packaging/lock && git add -f packaging/lock/.python-version
  git commit -qm "Lock for Leela $V, tested fresh with every extra"
  gitc push -q origin main
fi

say "5. publish the lock to the test channel"
test_v=$($LOCKPY verify --channel test 2>/dev/null | sed -n 's/.*lock \([0-9]*\), leela \([^,]*\),.*/\1 \2/p' || true)
if [ "${test_v#* }" = "$V" ]; then echo "the test channel has lock ${test_v% *} with leela $V"
else
  ssh-add -l 2>/dev/null | grep -q leela-lock-main || { echo "no leela-lock-main key in the SSH agent: eval \"\$(ssh-agent -s)\"; ssh-add --apple-use-keychain ~/.ssh/leela_lock_ed25519" >&2; exit 1; }
  # publish reads the new channel pointer back at once, and GitHub can take a few seconds to serve a new release; verify is the real check
  $LOCKPY publish || { sleep 15; $LOCKPY verify --channel test; }
  test_v=$($LOCKPY verify --channel test | sed -n 's/.*lock \([0-9]*\), leela \([^,]*\),.*/\1 \2/p')
fi
N=${test_v% *}

say "6. your check"
stable=$($LOCKPY verify 2>/dev/null | sed -n 's/.*lock \([0-9]*\),.*/\1/p' || true)
if [ "$stable" = "$N" ]; then echo "stable already points at lock $N"
elif [ "${YES:-}" = 1 ]; then echo "YES=1: no question"
else
  printf 'Lock %s (leela %s) is on the test channel. Open an app with LEELA_LOCK_CHANNEL=test, or a build from it, and check it.\nPromote it to stable? [y/N] ' "$N" "$V"
  read -r ok; [ "$ok" = y ] || [ "$ok" = yes ] || { echo "not promoted; run make ship V=$V again when it is good"; exit 1; }
fi

say "7. promote lock $N to stable"
if [ "$stable" = "$N" ]; then echo "done already"; else $LOCKPY promote "$N"; fi

say "8. the app"
if [ "${APP:-}" = 1 ] || ! gh release view "app-v$V" -R $R >/dev/null 2>&1; then MAKE="${MAKE:-make}" sh tools/ship_app.sh
else echo "app-v$V is there; a new lock reaches the installed app without one (APP=1 ships a new app anyway)"; fi
say "Leela $V is released."
