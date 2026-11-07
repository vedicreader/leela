# make ship V=<version>: build, sign, notarize and staple the Mac DMG here, replace the asset on release V, push the cask
# V reaches the script through the environment, so the shell never parses it
export V TAP
.PHONY: ship
ship:
	tools/ship.sh

# make vendor-check: rebuild the editor, terminal and htmx bundles from frontend/package-lock.json and fail if a byte differs
.PHONY: vendor-check
vendor-check:
	cd frontend && npm ci && npm run build
	git diff --exit-code leela/vendor
	uv run python tools/third_party.py --check
