"A bundle step that could emit a duplicate top-level name failed the whole IDE page at load (`leeDock`)."
import sys, pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as b
from jsdecls import declared

names = lambda s: [n for n, _ in declared(s)]

CASES = [
    ('const a = 1; const b = 2', ['a', 'b']),
    ('function f(){ let inner; const x = 1 }\nclass K { m(){ var z } }', ['f', 'K']),
    ('let a\nvar b, c = [1, 2], d\nclass E extends F {}', ['a', 'b', 'c', 'd', 'E']),
    ('const s = "const no"; const t = \'let no\'; // const no\n/* var no */ const u = /const no\\//g; const v = `let ${ {a: 1}.a } no ${`function no`}`', ['s', 't', 'u', 'v']),
    ('const {a, b: c, ...d} = o, [e, , f = 3, [g]] = p', ['a', 'c', 'd', 'e', 'f', 'g']),
    ('export const x = 1\nexport default function y(){}\nexport class Z {}', ['x', 'y', 'Z']),
    ('outer: for (const i of xs) { if (i) continue outer }\nconst after = 1', ['after']),
    ('const f = function g(){}\nconst h = class I {}\nfunction j(){}\no.const = 1; o.class = 2', ['f', 'h', 'j']),
    ('const a = 1\nconst b = x => x\nfunction c(){}', ['a', 'b', 'c']),
    ('if (x) { const hidden = 1; function nested(){} }\nconst shown = 2', ['shown']),
]

@pytest.mark.parametrize('src,want', CASES)
def test_declared(src, want): assert names(src) == want

def test_lines():
    assert declared('\n\nconst a = 1\n/* x\ny */\nlet b') == [('a', 3), ('b', 6)]

def _mods(tmp_path, files):
    ps = []
    for n, t in files.items():
        p = tmp_path/n; p.write_text(t); ps.append(p)
    return ps

@pytest.mark.parametrize('first,second', [('const leeDock = 1', 'const leeDock = 2'), ('function leeDock(){}', 'let leeDock'),
                                         ('class leeDock {}', 'var leeDock'), ('const {leeDock} = x', 'function leeDock(){}')])
def test_dupe_named(tmp_path, monkeypatch, first, second):
    a, b2 = _mods(tmp_path, {'mode.js': first, 'dock.js': second})
    monkeypatch.setattr(b, 'PKG', tmp_path)
    monkeypatch.setattr(b, 'PAGES', {'the IDE page': lambda: [a, b2]})
    (msg,) = b.dupes()
    assert 'leeDock' in msg and 'mode.js:1' in msg and 'dock.js:1' in msg

def test_build_and_check_fail_on_dupe(tmp_path, monkeypatch):
    a, b2 = _mods(tmp_path, {'a.js': 'const x = 1', 'b.js': 'const x = 2'})
    monkeypatch.setattr(b, 'PKG', tmp_path)
    monkeypatch.setattr(b, 'PAGES', {'p': lambda: [a, b2]})
    for check in (False, True):
        with pytest.raises(SystemExit, match='`x` is declared twice'): b.build(check=check)

def test_real_bundles_have_no_dupes(): assert b.dupes() == []
