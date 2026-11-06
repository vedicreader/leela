# Leela.app, the thin launcher: a Swift app with a pinned uv and a signed bootstrap lock. See docs/thin-app.md.
# make uv-fetch app verify builds and checks it here; SIGN_ID=- signs ad hoc for local checks.
SIGN_ID ?= -
APP := build/Leela.app
UV_VERSION := $(shell cat ../uv.version)
UV_SHA := $(shell cat ../uv.sha256)
UV := build/uv/uv
# the size limits of the plan: 60 MB on disk, 25 MB zipped
MAX_KB := 61440
MAX_ZIP_KB := 25600
# LOCK=<folder with manifest.json, manifest.sig and the lock files>; the default is the dev lock that make dev-lock writes
LOCK ?= build/dev-lock
KEYS ?= $(if $(filter build/dev-lock,$(LOCK)),build/dev-lock/keys.pub,../lock/keys.pub)
ZIP := build/Leela.zip
export SIGN_ID LOCK KEYS LOCK_SRC LOCK_DIR WORK

.PHONY: test build plist uv-fetch dev-lock bundle app verify zip fixtures clean

# the shortcut tests read the server's menu.json fresh from the Python source, with the default keymap
MENU_JSON := $(CURDIR)/build/menu.json
test:
	mkdir -p build
	cd ../.. && uv run --frozen python -c "import os,sys,json,tempfile; os.environ['XDG_CONFIG_HOME']=tempfile.mkdtemp(); from leela.blocks.keys.menus import launcher_json, menu_json; json.dump({'menus': menu_json(), 'launcher': launcher_json()}, open(sys.argv[1], 'w'))" "$(MENU_JSON)"
	LEELA_MENU_JSON="$(MENU_JSON)" swift test $(if $(value FILTER),--filter "$$FILTER")

build:
	swift build

# Info.plist's document types from leela.workspace.doc_types, the old app's list; test_packaging fails until this runs after a change
plist:
	cd ../.. && uv run --frozen python -c "import os,sys,plistlib,tempfile; os.environ['XDG_CONFIG_HOME']=tempfile.mkdtemp(); from leela.workspace import doc_types, imported_types; f=sys.argv[1]; p=plistlib.load(open(f,'rb')); p.update(CFBundleDocumentTypes=doc_types(), UTImportedTypeDeclarations=imported_types()); open(f,'wb').write(plistlib.dumps(p))" packaging/mac/Resources/Info.plist

# the pinned uv from its GitHub release, checked against packaging/uv.sha256 before it is unpacked
uv-fetch:
	mkdir -p build/uv
	curl -fsSL -o build/uv/uv.tar.gz "https://github.com/astral-sh/uv/releases/download/$(UV_VERSION)/uv-aarch64-apple-darwin.tar.gz"
	echo "$(UV_SHA)  build/uv/uv.tar.gz" | shasum -a 256 -c -
	tar -xzf build/uv/uv.tar.gz -C build/uv --strip-components 1
	test "$$(build/uv/uv --version | cut -d ' ' -f 2)" = "$(UV_VERSION)"
	@echo "uv $(UV_VERSION) in build/uv"

# a lock signed with a throwaway key, for local builds only; verify says so and ship-app refuses it. LOCK_SRC=<lock files>, default packaging/lock
dev-lock:
	cd ../.. && uv run --frozen python tools/lock.py dev-lock packaging/mac/build/dev-lock --from "$${LOCK_SRC:-packaging/lock}" --n "$${DEV_N:-0}"

# SSHSIG fixtures for the Swift tests, made by the real ssh-keygen with throwaway keys and a temporary HOME
fixtures:
	cd ../.. && uv run --frozen python tools/lock.py fixtures packaging/mac/Tests/LeelaCoreTests/Fixtures

bundle:
	swift build -c release --arch arm64
	test -x $(UV) || { echo "no pinned uv; run make uv-fetch" >&2; exit 1; }
	test -f "$$LOCK/manifest.sig" || { echo "no signed lock in $$LOCK; run make dev-lock or give LOCK=" >&2; exit 1; }
	mkdir -p build/trash
	if [ -e $(APP) ]; then mv $(APP) build/trash/Leela.app-$$$$; fi
	mkdir -p $(APP)/Contents/MacOS $(APP)/Contents/Helpers $(APP)/Contents/Resources/Lock
	cp "$$(swift build -c release --arch arm64 --show-bin-path)/Leela" $(APP)/Contents/MacOS/Leela
	cp $(UV) $(APP)/Contents/Helpers/uv
	cp Resources/Info.plist $(APP)/Contents/Info.plist
	cp ../childenv.json $(APP)/Contents/Resources/childenv.json
	cp "$$KEYS" $(APP)/Contents/Resources/lock-keys.pub
	for f in manifest.json manifest.sig pyproject.toml uv.lock .python-version; do cp "$$LOCK/$$f" $(APP)/Contents/Resources/Lock/; done
	if [ -f ../assets/Leela.icns ]; then cp ../assets/Leela.icns $(APP)/Contents/Resources/AppIcon.icns; else echo "no packaging/assets/Leela.icns (tools/build_icons.py makes it): the app has no icon"; fi

# the helper first, then the app: codesign signs nested code from the inside out
app: bundle
	codesign --force --options runtime --timestamp=none --sign "$$SIGN_ID" $(APP)/Contents/Helpers/uv
	codesign --force --options runtime --timestamp=none --entitlements entitlements.plist --sign "$$SIGN_ID" $(APP)

zip:
	rm -f $(ZIP)
	ditto -c -k --sequesterRsrc --keepParent $(APP) $(ZIP)

# checks the bundle without opening it: plist keys, uv version, lock signature, signature, size on disk and zipped
verify: zip
	cd ../.. && uv run --frozen python tools/lock.py verify-app packaging/mac/$(APP) --zip packaging/mac/$(ZIP) --max-kb $(MAX_KB) --max-zip-kb $(MAX_ZIP_KB)
	codesign --verify --strict --deep $(APP)
	codesign --verify --strict $(APP)/Contents/Helpers/uv
	@codesign -dvv $(APP) 2>&1 | grep -E 'Identifier|Authority|Signature|flags' || true
	@du -sk $(APP) | awk '{printf "on disk: %.1f MB\n", $$1/1024}'
	@ls -l $(ZIP) | awk '{printf "zipped: %.1f MB\n", $$5/1048576}'

clean:
	rm -rf build .build

# LOCK_DIR=<lock folder> WORK=<empty folder>: the built launcher's headless --lock-test, which builds the env as the app does; no window
lock-test-launcher:
	@test -n "$$LOCK_DIR" && test -n "$$WORK" || { echo "Give LOCK_DIR= and WORK=" >&2; exit 1; }
	$(APP)/Contents/MacOS/Leela --lock-test "$$LOCK_DIR" "$$WORK"
