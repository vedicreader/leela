#!/bin/sh
# usage: V=<version> [TAP=<tap folder>] tools/ship.sh (make ship V=<version> does this). The Mac release of Leela, as abhyasa's
# mac/scripts/ship.sh does it: build Leela.app on this Mac, sign it with the Developer ID in the keychain, notarize and staple
# the DMG, put it on the GitHub release for V in place of the one that CI attached, then write its sha256 into the tap and
# push it (tools/ship_cask.sh with PUSH=1). It never moves a tag or a release, so it can always run again.
# Notary credentials, first match wins: LEELA_NOTARY_PROFILE (a notarytool keychain profile), LEELA_ASC_KEY with
# LEELA_ASC_KEY_ID and LEELA_ASC_ISSUER, then ~/.config/leela/notary.json or Sanketa's ~/.config/sanketa/notary.json
# {"key_id","issuer_id","key_path"}, the file that abhyasa's mac/scripts/notarize.sh reads.
set -eu
: "${V:?Give the version: make ship V=<version>}"
echo "$V" | grep -qE '^[0-9]+(\.[0-9]+)+$' || { echo "V must be a version such as 0.1.12" >&2; exit 1; }
cd "$(dirname "$0")/.."
R=vedicreader/leela D=dist/Leela-macOS.dmg
unset GITHUB_TOKEN   # the keyring of gh signs in; a stale token in the environment would win over it

grep -q "^__version__ = \"$V\"" leela/__init__.py || { echo "leela/__init__.py is not version $V" >&2; exit 1; }
tag=$(for t in "v$V" "$V"; do gh release view "$t" -R $R --json tagName -q .tagName 2>/dev/null && break; done || true)
test -n "$tag" || { echo "no release for $V on $R. Make it with ship-gh first." >&2; exit 1; }

LEELA_CODESIGN_IDENTITY=$(security find-identity -v -p codesigning | sed -n 's/.*"\(Developer ID Application: .*\)"$/\1/p' | head -n 1)
test -n "$LEELA_CODESIGN_IDENTITY" || { echo "no Developer ID Application identity in the keychain" >&2; exit 1; }
cfg="$HOME/.config/leela/notary.json"
test -f "$cfg" || cfg="$HOME/.config/sanketa/notary.json"
if [ -z "${LEELA_NOTARY_PROFILE:-}${LEELA_ASC_KEY:-}" ] && [ -f "$cfg" ]; then
  { read -r LEELA_ASC_KEY; read -r LEELA_ASC_KEY_ID; read -r LEELA_ASC_ISSUER; } <<EOF
$(python3 -c '
import json, os, sys
c = json.load(open(sys.argv[1]))
print(os.path.join(os.path.dirname(sys.argv[1]), os.path.expanduser(c["key_path"])), c["key_id"], c["issuer_id"], sep="\n")' "$cfg")
EOF
  echo "notary: API key $LEELA_ASC_KEY_ID from $cfg"
fi
test -n "${LEELA_NOTARY_PROFILE:-}${LEELA_ASC_KEY:-}" || {
  echo "no notary credentials. Write ~/.config/leela/notary.json with key_id, issuer_id and key_path, or run" \
    "'xcrun notarytool store-credentials leela-notary --apple-id <id> --team-id 7632NRC559' and then LEELA_NOTARY_PROFILE=leela-notary make ship V=$V" >&2
  exit 1; }
export LEELA_CODESIGN_IDENTITY LEELA_NOTARY_PROFILE="${LEELA_NOTARY_PROFILE:-}" LEELA_ASC_KEY="${LEELA_ASC_KEY:-}" \
  LEELA_ASC_KEY_ID="${LEELA_ASC_KEY_ID:-}" LEELA_ASC_ISSUER="${LEELA_ASC_ISSUER:-}"

# build_release signs with the identity, makes the DMG, notarizes it and staples it
uv run --frozen python tools/build_release.py
xcrun stapler validate $D
spctl -a -t exec -vv dist/Leela.app 2>&1 | tee /dev/stderr | grep -q 'source=Notarized Developer ID' ||
  { echo "Gatekeeper does not accept dist/Leela.app as notarized" >&2; exit 1; }

# desktop-artifacts attaches its own DMG to the tag; wait for it, so it cannot replace this one after the upload
while case "$(gh run list -R $R -w desktop-artifacts -b "$tag" -L 1 --json status -q '.[0].status')" in
  queued|in_progress|waiting|pending|requested) true;; *) false;; esac; do
  echo "Waiting for desktop-artifacts on $tag"; sleep 30
done
gh release upload "$tag" $D --clobber -R $R
PUSH=1 tools/ship_cask.sh
echo "Leela $V for Mac is shipped."
