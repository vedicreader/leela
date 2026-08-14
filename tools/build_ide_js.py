#!/usr/bin/env python
"""Concatenate `leela/static/js/*.js` into the served `leela/static/lee-ide.js`.

The modules are the source; the bundle is generated and committed so the IDE stays
one deferred script tag with no build step at install time. `--check` fails when the
two have drifted, which is what CI and `tests/blocks/test_ide_bundle.py` assert.
"""
from __future__ import annotations
import sys
from fastcore.all import Path

ROOT = Path(__file__).resolve().parent.parent
JS, OUT = ROOT/'leela'/'static'/'js', ROOT/'leela'/'static'/'lee-ide.js'


def modules():
    "The module paths in load order, which the numeric filename prefixes are there to fix."
    return sorted(JS.glob('*.js'))


def _text(p):
    "One module's source, newline-terminated: without it its last line fuses into the next module."
    t = p.read_text()
    return t if t.endswith('\n') else t + '\n'


def bundle():
    "The concatenated bundle text."
    return ''.join(_text(p) for p in modules())


def build(check=False):
    text = bundle()
    if check:
        if OUT.read_text() != text: raise SystemExit(f'{OUT.name} is stale; run python tools/build_ide_js.py')
        print(f'{OUT.name} matches its {len(modules())} modules')
        return
    OUT.write_text(text)
    print(f'wrote {OUT.name} ({text.count(chr(10))} lines from {len(modules())} modules)')


if __name__ == '__main__': build(check='--check' in sys.argv)
