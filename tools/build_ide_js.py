#!/usr/bin/env python
"""Concatenate `leela/static/js/*.js` into the served `leela/static/lee-ide.js`.

The modules are the source; the bundle is generated and committed so the IDE stays
one deferred script tag with no build step at install time. `--check` fails when the
two have drifted, which is what CI and `tests/test_web_block.py` assert.
"""
from __future__ import annotations
import sys
from fastcore.all import Path

ROOT = Path(__file__).resolve().parent.parent
JS, OUT = ROOT/'leela'/'static'/'js', ROOT/'leela'/'static'/'lee-ide.js'


def modules():
    "The module paths in manifest order, refusing a manifest that has drifted from disk."
    listed = [ln.strip() for ln in (JS/'manifest.txt').read_text().splitlines() if ln.strip()]
    on_disk = {p.name for p in JS.glob('*.js')}
    if missing := [n for n in listed if n not in on_disk]: raise SystemExit(f'manifest names no such module: {missing}')
    if unlisted := sorted(on_disk - set(listed)): raise SystemExit(f'module not in manifest.txt: {unlisted}')
    return [JS/n for n in listed]


def bundle():
    "The concatenated bundle text."
    text = ''.join(p.read_text() for p in modules())
    return text if text.endswith('\n') else text + '\n'


def build(check=False):
    text = bundle()
    if check:
        if OUT.read_text() != text: raise SystemExit(f'{OUT.name} is stale; run python tools/build_ide_js.py')
        print(f'{OUT.name} matches its {len(modules())} modules')
        return
    OUT.write_text(text)
    print(f'wrote {OUT.name} ({text.count(chr(10))} lines from {len(modules())} modules)')


if __name__ == '__main__': build(check='--check' in sys.argv)
