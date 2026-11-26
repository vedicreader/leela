# Leela's release targets. Values reach recipes through the environment ("$$V"), so the shell never parses them.
# The release: make ship V=<version> (py2app app, tools/ship.sh). The archived thin app and its environment lock: docs/thin-app.md, make ship-archive.
export V APP YES TAP N WHEEL DIR CHANNEL FRESH EXTRAS ALLOW_DOWNGRADE PIN AGAINST
PY ?= uv run --frozen python
LOCKPY := $(PY) tools/lock.py
.PHONY: ship ship-archive ship-app lock lock-wheel lock-hash lock-check lock-test lock-diff lock-publish lock-promote lock-verify lock-key

# V=<version>: build, sign, notarize and staple the py2app DMG and zip, put both on release V, and push the cask. The release V must exist.
ship:
	@test -n "$$V" || { echo "Give the version: make ship V=1.0.1" >&2; exit 1; }
	tools/ship.sh

# Archived. V=<version> [APP=1] [YES=1]: the thin-app release, each step skipped when it is done (tools/release.sh says which):
# CI green, release V and its wheel, a tested lock, lock-publish, your check, lock-promote, ship-app. Start an SSH agent first.
ship-archive:
	@test -n "$$V" || { echo "Give the version: make ship-archive V=1.0.1" >&2; exit 1; }
	MAKE="$(MAKE)" sh tools/release.sh

# V=<app version>: sign, notarize, staple, zip, upload to app-v<V> (--latest=false), update the cask
ship-app:
	@test -n "$$V" || { echo "Give the app version: make ship-app V=1.0.0" >&2; exit 1; }
	MAKE="$(MAKE)" sh tools/ship_app.sh

# V=<leela version>: build the wheel from tag V and attach it to release V; make lock pins it by GitHub's sha256
lock-wheel:
	@test -n "$$V" || { echo "Give the Leela version: make lock-wheel V=0.1.23" >&2; exit 1; }
	$(LOCKPY) wheel "$$V" --upload

# V=<leela version> [WHEEL=<local wheel>, test only] [DIR=<folder>, default packaging/lock] [PIN=<one constraint, such as ramabana==0.2.109>]
lock:
	@test -n "$$V" || { echo "Give the Leela version: make lock V=0.1.23" >&2; exit 1; }
	$(LOCKPY) make "$$V" $(if $(value WHEEL),--wheel "$$WHEEL") $(if $(value DIR),--dir "$$DIR") $(if $(value PIN),--pin "$$PIN")

lock-hash:
	$(LOCKPY) hash $(if $(value DIR),--dir "$$DIR")

lock-check:
	$(LOCKPY) check $(if $(value DIR),--dir "$$DIR")

# FRESH=1 empty uv cache, EXTRAS=1 each extra too; writes packaging/lock/tested/<hash>.json when it passes
lock-test:
	$(LOCKPY) test $(if $(value DIR),--dir "$$DIR") $(if $(filter 1,$(FRESH)),--fresh) $(if $(filter 1,$(EXTRAS)),--extras)

lock-diff:
	$(LOCKPY) diff $(if $(value DIR),--dir "$$DIR") $(if $(value AGAINST),--against "$$AGAINST")

# refuses an untested, stale or unpushed lock; ALLOW_DOWNGRADE=1 publishes an older leela as a roll back
lock-publish:
	$(LOCKPY) publish $(if $(filter 1,$(ALLOW_DOWNGRADE)),--allow-downgrade)

lock-promote:
	@test -n "$$N" || { echo "Give the lock number on the test channel: make lock-promote N=4" >&2; exit 1; }
	$(LOCKPY) promote "$$N"

# CHANNEL=test checks the test channel
lock-verify:
	$(LOCKPY) verify $(if $(filter test,$(CHANNEL)),--channel test)

# the SSH signing keys in ~/.ssh, asks for a passphrase; refuses to overwrite
lock-key:
	$(LOCKPY) key

# make vendor-check: rebuild the editor, terminal and htmx bundles from frontend/package-lock.json and fail if a byte differs
.PHONY: vendor-check
vendor-check:
	cd frontend && npm ci && npm run build
	git diff --exit-code leela/vendor
	uv run python tools/third_party.py --check
