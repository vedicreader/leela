"""A block's client module should talk to its own block's routes."""

from __future__ import annotations
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder                                              # noqa: E402


def test_every_keymap_action_has_a_dispatch_entry():
    """A named command with no `ACTIONS` entry is a menu row and a chord that do nothing."""
    import ast as _ast
    from leela.core.keys import KEYS
    src = next(p for p in builder.modules() if p.name == 'actions.js').read_text()
    lines = src.split('\n')
    start = next(i for i, l in enumerate(lines) if l.startswith('const ACTIONS = {'))
    end = next(i for i, l in enumerate(lines) if i > start and l.startswith('};'))
    entries = set(re.findall(r'^\s+([A-Za-z_$][\w$]*)\s*:', '\n'.join(lines[start:end + 1]), re.M))
    entries |= set(re.findall(r"ACTIONS\['([\w]+)'\s*\+", src))          # the tab_N family
    for p2 in builder.modules():                                     # and the later assignments
        t = p2.read_text()
        entries |= set(re.findall(r'ACTIONS\.(\w+)\s*=', t))
        entries |= set(re.findall(r"ACTIONS\['(\w+)'\]\s*=", t))
    dynamic = {'tab'}
    missing = sorted(a for a in {k.action for k in KEYS} if a not in entries
                     and not any(a.startswith(d) for d in dynamic))
    assert missing == [], f'named commands with no dispatch entry: {missing}'
