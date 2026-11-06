# Leela's release targets. Values reach recipes through the environment ("$$V"), so the shell never parses them.
# The thin Mac app and its environment lock: docs/thin-app.md. The old fat app: make ship V=<version> (py2app, being retired).
export V TAP N WHEEL DIR CHANNEL FRESH EXTRAS ALLOW_DOWNGRADE
PY := uv run --frozen python
LOCKPY := $(PY) tools/lock.py
.PHONY: ship ship-app lock lock-wheel lock-hash lock-check lock-test lock-diff lock-publish lock-promote lock-verify lock-key

# The fat py2app DMG. Kept for one release while the thin app ships; it says so first.
ship:
	@echo "make ship builds the old py2app app. The thin Mac app ships with: make lock V=..., make lock-test, make lock-publish,"
	@echo "make lock-promote N=..., then make ship-app V=<app version>. See docs/thin-app.md."
	tools/ship.sh

# V=<app version>: sign, notarize, staple, zip, upload to app-v<V> (--latest=false), update the cask
ship-app:
	@test -n "$$V" || { echo "Give the app version: make ship-app V=1.0.0" >&2; exit 1; }
	MAKE="$(MAKE)" sh tools/ship_app.sh

# V=<leela version>: build the wheel from tag V and attach it to release V; make lock pins it by GitHub's sha256
lock-wheel:
	@test -n "$$V" || { echo "Give the Leela version: make lock-wheel V=0.1.23" >&2; exit 1; }
	$(LOCKPY) wheel "$$V" --upload

# V=<leela version> [WHEEL=<local wheel>, test only] [DIR=<folder>, default packaging/lock]
lock:
	@test -n "$$V" || { echo "Give the Leela version: make lock V=0.1.23" >&2; exit 1; }
	$(LOCKPY) make "$$V" $(if $(value WHEEL),--wheel "$$WHEEL") $(if $(value DIR),--dir "$$DIR")

lock-hash:
	$(LOCKPY) hash $(if $(value DIR),--dir "$$DIR")

lock-check:
	$(LOCKPY) check $(if $(value DIR),--dir "$$DIR")

# FRESH=1 empty uv cache, EXTRAS=1 each extra too; writes packaging/lock/tested/<hash>.json when it passes
lock-test:
	$(LOCKPY) test $(if $(value DIR),--dir "$$DIR") $(if $(filter 1,$(FRESH)),--fresh) $(if $(filter 1,$(EXTRAS)),--extras)

lock-diff:
	$(LOCKPY) diff $(if $(value DIR),--dir "$$DIR")

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
