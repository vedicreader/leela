#!/bin/sh
# usage: V=<app version> [TAP=<tap folder>] tools/ship_app.sh (make ship-app V=<version> does this). The thin Mac app, shipped by kavacha
# (`kavacha ship mac --release`): built with the bootstrap lock the stable channel points at, signed with the Developer ID in the keychain,
# notarized, stapled, zipped, put on release app-v<V> with --latest=false; then the cask goes to the tap (tools/ship_cask.sh). See docs/thin-app.md.
set -eu
: "${V:?Give the app version: make ship-app V=<version>}"
echo "$V" | grep -qE '^[0-9]+(\.[0-9]+)+$' || { echo "V must be a version such as 1.0.0" >&2; exit 1; }
cd "$(dirname "$0")/.."
unset GITHUB_TOKEN   # the keyring of gh signs in; a stale token in the environment would win over it

ID=$(security find-identity -v -p codesigning | sed -n 's/.*"\(Developer ID Application: .*\)"$/\1/p' | head -n 1)
test -n "$ID" || { echo "no Developer ID Application identity in the keychain" >&2; exit 1; }
cfg="$HOME/.config/leela/notary.json"
test -f "$cfg" || cfg="$HOME/.config/sanketa/notary.json"
if [ -n "${LEELA_NOTARY_PROFILE:-}" ]; then NOTARY="--profile $LEELA_NOTARY_PROFILE"
else
  test -f "$cfg" || { echo "no notary credentials: LEELA_NOTARY_PROFILE or ~/.config/leela/notary.json" >&2; exit 1; }
  NOTARY=$(python3 -c '
import json, os, shlex, sys
c = json.load(open(sys.argv[1]))
print("--key", shlex.quote(os.path.join(os.path.dirname(sys.argv[1]), os.path.expanduser(c["key_path"]))), "--key-id", c["key_id"], "--issuer", c["issuer_id"])' "$cfg")
fi

# shellcheck disable=SC2086
uv run --frozen kavacha ship mac --release "$V" --sign "$ID" $NOTARY ${LAUNCHER:+--launcher "$LAUNCHER"}
TAG_PREFIX=app-v ASSET=Leela.zip PUSH=1 tools/ship_cask.sh
echo "Leela app $V is shipped."
