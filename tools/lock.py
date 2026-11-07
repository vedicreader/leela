#!/usr/bin/env python3
"Leela's environment lock: kavacha's lock tool with Leela's spec (packaging/kavacha.toml) and checks (tools/lock_hooks.py). See docs/thin-app.md."
import sys
from pathlib import Path
from kavacha.lock import main

ROOT = Path(__file__).resolve().parent.parent

if __name__ == '__main__': main(['--root', str(ROOT), *sys.argv[1:]])
