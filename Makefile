# make ship V=<version>: build, sign, notarize and staple the Mac DMG here, replace the asset on release V, push the cask
# V reaches the script through the environment, so the shell never parses it
export V TAP
.PHONY: ship
ship:
	tools/ship.sh
