# Leela.app, the thin launcher: kavacha's launcher, a pinned uv and a signed bootstrap lock, from packaging/kavacha.toml. See docs/thin-app.md.
# make uv-fetch dev-lock app builds it in build/; SIGN_ID=- signs ad hoc for local checks. LAUNCHER=<kavacha-launcher> is a local build of
# kavacha's swift/ (make -C <kavacha>/swift launcher); with none, the app takes the kavacha release the spec pins.
SIGN_ID ?= -
LOCK ?= packaging/mac/build/dev-lock
PY ?= uv run --frozen python
KAVACHA ?= uv run --frozen kavacha
export SIGN_ID LOCK LOCK_SRC LOCK_DIR WORK LAUNCHER BUILD V

.PHONY: test uv-fetch dev-lock app verify lock-test-launcher

# the server's menu bar, fresh from the Python source with the default keymap, checked by the launcher with no window
MENU_JSON := $(CURDIR)/build/menu.json
test:
	@test -n "$$LAUNCHER" || { echo "Give LAUNCHER=<kavacha-launcher>, a build of kavacha's swift/" >&2; exit 1; }
	mkdir -p build
	cd ../.. && $(PY) -c "import os,sys,json,tempfile; os.environ['XDG_CONFIG_HOME']=tempfile.mkdtemp(); from leela.blocks.keys.menus import launcher_json, menu_json; json.dump({'menus': menu_json(), 'launcher': launcher_json()}, open(sys.argv[1], 'w'))" "$(MENU_JSON)"
	"$$LAUNCHER" --check-menu "$(MENU_JSON)"

uv-fetch:
	cd ../.. && $(KAVACHA) ship mac --uv-only

# a lock signed with a throwaway key, for local builds only; verify says so. LOCK_SRC=<lock files>, default packaging/lock
dev-lock:
	cd ../.. && $(PY) tools/lock.py dev-lock packaging/mac/build/dev-lock --from "$${LOCK_SRC:-packaging/lock}" --n "$${DEV_N:-0}"

# the bundle, signed (the helper first, then the app) and checked: plist, uv, lock signature, kavacha.json, size on disk and zipped
app:
	cd ../.. && $(KAVACHA) ship mac --lock "$$LOCK" --sign "$$SIGN_ID" $(if $(value LAUNCHER),--launcher "$$LAUNCHER") $(if $(value V),--version "$$V") $(if $(value BUILD),--build "$$BUILD")

verify:
	cd ../.. && $(PY) tools/lock.py verify-app packaging/mac/build/Leela.app --zip packaging/mac/build/Leela.zip
	codesign --verify --strict --deep build/Leela.app
	codesign --verify --strict build/Leela.app/Contents/Helpers/uv

# LOCK_DIR=<lock folder> WORK=<empty folder>: the built launcher's headless --lock-test, which builds the env as the app does; no window
lock-test-launcher:
	@test -n "$$LOCK_DIR" && test -n "$$WORK" || { echo "Give LOCK_DIR= and WORK=" >&2; exit 1; }
	build/Leela.app/Contents/MacOS/Leela --lock-test "$$LOCK_DIR" "$$WORK"
