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

need_gh() { gh release list -R $R --limit 1 >/dev/null 2>&1 || { echo "gh cannot reach $R: it is not signed in, or the keychain is locked. Run gh auth status, then gh auth login if it says so, and run make ship V=$V again" >&2; exit 1; }; }
need_gh   # a broken gh login stops the release here, before the slow steps

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
if grep -q "\"leela==$V\"" packaging/lock/pyproject.toml && test -f "packaging/lock/tested/$($LOCKPY hash).json"; then echo "packaging/lock pins leela $V and has its test record"
else
  test -x packaging/mac/build/uv/uv || make -C packaging/mac uv-fetch
  $LOCKPY make "$V"
  $LOCKPY test --fresh --extras
fi
git add packaging/lock && git add -f packaging/lock/.python-version
git diff --cached --quiet || git commit -qm "Lock for Leela $V, tested fresh with every extra"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" || gitc push -q origin main

say "5. publish the lock to the test channel"
# steps 5 and 7 both sign, so the key must be in the agent on every run
ssh-add -l 2>/dev/null | grep -q leela-lock-main || { echo "no leela-lock-main key in the SSH agent. fish: eval (ssh-agent -c); bash or zsh: eval \"\$(ssh-agent -s)\". Then: ssh-add --apple-use-keychain ~/.ssh/leela_lock_ed25519" >&2; exit 1; }
test_v=$($LOCKPY verify --channel test 2>/dev/null | sed -n 's/.*lock \([0-9]*\), leela \([^,]*\),.*/\1 \2/p' || true)
if [ "${test_v#* }" = "$V" ]; then echo "the test channel has lock ${test_v% *} with leela $V"
else
  # the test channel decides: publish can stop on a read-back while GitHub settles, so look again for up to 2 minutes
  $LOCKPY publish || echo "publish stopped; checking the test channel for up to 2 minutes" >&2
  for _ in 1 2 3 4 5 6 7 8; do
    test_v=$($LOCKPY verify --channel test 2>/dev/null | sed -n 's/.*lock \([0-9]*\), leela \([^,]*\),.*/\1 \2/p' || true)
    [ "${test_v#* }" = "$V" ] && break; sleep 15
  done
fi
[ "${test_v#* }" = "$V" ] || { echo "the test channel has '${test_v:-nothing}', not leela $V, so publish failed. If a lock-<n> release was made but the channel did not move, delete it (gh release delete lock-<n> -R $R --cleanup-tag -y) and run again" >&2; exit 1; }
N=${test_v% *}

say "6. your check"
stable=$($LOCKPY verify 2>/dev/null | sed -n 's/.*lock \([0-9]*\),.*/\1/p' || true)
if [ "$stable" = "$N" ]; then echo "stable already points at lock $N"
elif [ "${YES:-}" = 1 ]; then echo "YES=1: no question"
else
  printf 'Lock %s (leela %s) is on the test channel. Open an app with LEELA_LOCK_CHANNEL=test, or a build from it, and check it.\nPromote it to stable? [y/N] ' "$N" "$V"
  read -r ok || ok=; [ "$ok" = y ] || [ "$ok" = yes ] || { echo "not promoted; run make ship V=$V again when it is good"; exit 1; }
fi

say "7. promote lock $N to stable"
if [ "$stable" = "$N" ]; then echo "done already"; else $LOCKPY promote "$N"; fi

say "8. the app"
need_gh   # signing and notarizing take minutes, and the keychain can lock in that time: look again before them
if [ "${APP:-}" = 1 ] || ! gh release view "app-v$V" -R $R >/dev/null 2>&1; then MAKE="${MAKE:-make}" sh tools/ship_app.sh
else
  echo "app-v$V is there; a new lock reaches the installed app without one (APP=1 ships a new app anyway)"
  TAG_PREFIX=app-v ASSET=Leela.zip PUSH=1 sh tools/ship_cask.sh   # a stop after the upload left the cask behind; makes no commit when it is current
fi
say "Leela $V is released."
