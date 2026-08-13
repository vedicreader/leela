#!/usr/bin/env python
"""Concatenate `leela/static/js/*.js` into `leela/static/lee-ide.js`.

Source of truth is the module folder; the served bundle stays one file so the
IDE keeps working offline with a single deferred script tag.
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'leela' / 'static' / 'js'
OUT = ROOT / 'leela' / 'static' / 'lee-ide.js'

def modules():
    manifest = JS / 'manifest.txt'
    if manifest.is_file():
        names = [ln.strip() for ln in manifest.read_text().splitlines() if ln.strip()]
        return [JS / n for n in names]
    return sorted(JS.glob('*.js'))

def build():
    parts = []
    for p in modules():
        if not p.is_file(): raise SystemExit(f'missing module: {p}')
        parts.append(p.read_text())
    text = ''.join(parts)
    if not text.endswith('\n'): text += '\n'
    OUT.write_text(text)
    print(f'wrote {OUT.relative_to(ROOT)} ({text.count(chr(10))} lines from {len(parts)} modules)')

if __name__ == '__main__':
    build()
