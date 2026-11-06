#!/bin/sh
# usage: V=<app version> [TAP=<tap folder>] tools/ship_app.sh (make ship-app V=<version> does this). The thin Mac app: build it with the
# bootstrap lock the stable channel points at, sign it with the Developer ID in the keychain, notarize and staple it, zip it, put the zip
# on release app-v<V> with --latest=false, then write the cask (tools/ship_cask.sh with TAG_PREFIX=app-v). See docs/thin-app.md.
# Notary credentials as tools/ship.sh reads them. It never moves a tag, so it can always run again.
set -eu
: "${V:?Give the app version: make ship-app V=<version>}"
echo "$V" | grep -qE '^[0-9]+(\.[0-9]+)+$' || { echo "V must be a version such as 1.0.0" >&2; exit 1; }
cd "$(dirname "$0")/.."
R=vedicreader/leela M=packaging/mac APP=packaging/mac/build/Leela.app Z=packaging/mac/build/Leela.zip T="app-v$V"
MAKE=${MAKE:-make}
unset GITHUB_TOKEN   # the keyring of gh signs in; a stale token in the environment would win over it

test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' $M/Resources/Info.plist)" = "$V" ||
  { echo "$M/Resources/Info.plist is not version $V" >&2; exit 1; }
test -f packaging/lock/keys.pub || { echo "no packaging/lock/keys.pub; run make lock-key and commit the public keys" >&2; exit 1; }
test -z "$(git status --porcelain)" || { echo "the git tree has changes that are not committed" >&2; exit 1; }

ID=$(security find-identity -v -p codesigning | sed -n 's/.*"\(Developer ID Application: .*\)"$/\1/p' | head -n 1)
test -n "$ID" || { echo "no Developer ID Application identity in the keychain" >&2; exit 1; }
cfg="$HOME/.config/leela/notary.json"
test -f "$cfg" || cfg="$HOME/.config/sanketa/notary.json"
if [ -z "${LEELA_NOTARY_PROFILE:-}" ]; then
  test -f "$cfg" || { echo "no notary credentials: LEELA_NOTARY_PROFILE or ~/.config/leela/notary.json" >&2; exit 1; }
  { read -r KEY; read -r KEY_ID; read -r ISSUER; } <<EOF
$(python3 -c '
import json, os, sys
c = json.load(open(sys.argv[1]))
print(os.path.join(os.path.dirname(sys.argv[1]), os.path.expanduser(c["key_path"])), c["key_id"], c["issuer_id"], sep="\n")' "$cfg")
EOF
fi

# the bootstrap lock: what the stable channel serves, checked against the committed public keys
rm -rf $M/build/lock
uv run --frozen python tools/lock.py fetch $M/build/lock
"$MAKE" -C $M uv-fetch app verify SIGN_ID="$ID" LOCK=build/lock KEYS=../lock/keys.pub
codesign -dvv $APP 2>&1 | grep -q 'Authority=Developer ID Application' || { echo "$APP is not signed with a Developer ID" >&2; exit 1; }

rm -f $Z.notary.zip
ditto -c -k --sequesterRsrc --keepParent $APP $Z.notary.zip
if [ -n "${LEELA_NOTARY_PROFILE:-}" ]; then xcrun notarytool submit $Z.notary.zip --keychain-profile "$LEELA_NOTARY_PROFILE" --wait
else xcrun notarytool submit $Z.notary.zip --key "$KEY" --key-id "$KEY_ID" --issuer "$ISSUER" --wait; fi
xcrun stapler staple $APP
xcrun stapler validate $APP
spctl -a -t exec -vv $APP 2>&1 | tee /dev/stderr | grep -q 'source=Notarized Developer ID' || { echo "Gatekeeper does not accept $APP" >&2; exit 1; }
rm -f $Z $Z.notary.zip
ditto -c -k --sequesterRsrc --keepParent $APP $Z

if gh release view "$T" -R $R >/dev/null 2>&1; then gh release upload "$T" $Z --clobber -R $R
else gh release create "$T" $Z -R $R --latest=false --title "Leela app $V" --notes "The Leela Mac app $V. It installs Leela's packages from the signed lock on first run."; fi
TAG_PREFIX=app-v ASSET=Leela.zip PUSH=1 tools/ship_cask.sh
echo "Leela app $V is shipped."
