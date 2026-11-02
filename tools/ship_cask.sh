#!/bin/sh
# usage: V=<version> [TAP=<tap folder>] [PUSH=1] tools/ship_cask.sh, after `gh release create`. It updates the Leela cask.
# It waits up to 60 minutes for desktop-artifacts to attach Leela-macOS.dmg, reads the sha256 that GitHub keeps for the
# asset, writes the version, the tag prefix and the hash into Casks/leela.rb, and commits the tap. PUSH=1 also pushes it.
# A second run with the same V makes no new commit, so it can always run again.
set -eu
: "${V:?Give the version: V=<version> tools/ship_cask.sh}"
echo "$V" | grep -qE '^[0-9]+(\.[0-9]+)+$' || { echo "V must be a version such as 0.1.12" >&2; exit 1; }
TAP=${TAP:-$(dirname "$0")/../../homebrew-tap}
R=vedicreader/leela A=Leela-macOS.dmg C="$TAP/Casks/leela.rb"
unset GITHUB_TOKEN   # the keyring of gh signs in; a stale token in the environment would win over it

test -f "$C" || { echo "$C is not there" >&2; exit 1; }
test -z "$(git -C "$TAP" status --porcelain)" || { echo "$TAP has changes that are not committed" >&2; exit 1; }
# ship-gh tags the bare version and gh release create takes what you give it, so try both
tag=$(for t in "v$V" "$V"; do gh release view "$t" -R $R --json tagName -q .tagName 2>/dev/null && break; done || true)
test -n "$tag" || { echo "no release for $V on $R. Make it with gh release create first." >&2; exit 1; }

n=0
until sum=$(gh release view "$tag" -R $R --json assets -q ".assets[] | select(.name == \"$A\" and .state == \"uploaded\") | .digest") && test -n "$sum"; do
  test "$(gh run list -R $R -w desktop-artifacts -b "$tag" -L 1 --json conclusion -q '.[0].conclusion')" != failure ||
    { echo "desktop-artifacts failed for $tag. Run it again in GitHub Actions, then run this script again." >&2; exit 1; }
  n=$((n + 1))
  test $n -le 120 || { echo "$A is not on $tag after 60 minutes" >&2; exit 1; }
  echo "Waiting for $A on $tag ($n of 120)"; sleep 30
done
sum=${sum#sha256:}
echo "$sum" | grep -qE '^[0-9a-f]{64}$' || { echo "GitHub gave no sha256 for $A on $tag" >&2; exit 1; }

sed -i '' -e "s/^  version \".*\"/  version \"$V\"/" -e "s/^  sha256 \".*\"/  sha256 \"$sum\"/" \
  -e "s|/download/[^/]*#{version}/|/download/${tag%"$V"}#{version}/|" "$C"
grep -E '^  (version|sha256|url) ' "$C"
git -C "$TAP" add Casks/leela.rb
git -C "$TAP" diff --cached --quiet || git -C "$TAP" commit -m "Leela $V"
test "${PUSH:-}" = 1 || { echo "The tap is committed. To publish it: PUSH=1 V=$V tools/ship_cask.sh"; exit 0; }
git -C "$TAP" -c credential.helper= -c "credential.helper=!gh auth git-credential" push
echo "Leela $V is in the tap."
