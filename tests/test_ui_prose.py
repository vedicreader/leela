"No em dash in a string the app shows: the owner's writing rules ban it, and the review found 104."
import re
from pathlib import Path

PKG = Path(__file__).parents[1]/'leela'
#: Built bundles are generated from the block modules; vendored files are not ours.
BUILT = re.compile(r'^lee-.*\.js$|\.min\.js$')
#: A string or template literal on one line.
STR = re.compile(r"""(?P<q>'''|\"\"\"|'|"|`)(?P<s>(?:\\.|(?!(?P=q)).)*?)(?P=q)""")
#: Code that reads window titles keeps the dash older titles had, as Sanketa's patterns do.
TITLE_PARSER = re.compile(r'Google Chrome|\[Ll\]eela')

def sources():
    for p in sorted(PKG.rglob('*')):
        if p.suffix not in ('.py', '.js') or 'vendor' in p.parts or BUILT.search(p.name): continue
        yield p

def em_dashes(p):
    "Each `(line number, line)` of `p` with an em dash inside a string literal."
    for i, line in enumerate(p.read_text(errors='ignore').splitlines(), 1):
        st = line.strip()
        if '—' not in st or st.startswith(('#', '//', '*', '/*')) or TITLE_PARSER.search(st): continue
        if any('—' in m.group('s') for m in STR.finditer(line)): yield i, st[:120]

def test_the_scan_finds_a_dash_in_each_kind_of_string(tmp_path):
    p = tmp_path/'x.js'
    p.write_text("status('a — b');\nconst t = `x — ${y}`;\n// a comment — fine\nf(\"q — r\")\n")
    assert [i for i, _ in em_dashes(p)] == [1, 2, 4]

def test_no_ui_string_has_an_em_dash():
    files = list(sources())
    assert len(files) > 100 and any(f.suffix == '.js' for f in files), 'the scan reads the block modules'
    bad = [f'{p.relative_to(PKG.parent)}:{i}: {s}' for p in files for i, s in em_dashes(p)]
    assert not bad, 'use a full stop, a colon or " · " instead:\n' + '\n'.join(bad)
