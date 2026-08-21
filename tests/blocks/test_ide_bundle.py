"""What the client's bundles must hold true, whatever the modules say.

They are concatenations into one shared lexical scope, so order is a contract and a name
declared twice is the last one winning silently. These are structural checks over the built
assets, not assertions about anyone's source text.
"""

from __future__ import annotations
import re, sys
from collections import Counter
from pathlib import Path
from fastcore.all import L

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder                                              # noqa: E402

CSS = (ROOT/'leela/static/lee-ide.css').read_text()
JS = ''.join((builder.OUTDIR/n).read_text() for n in builder.LAYERS)
DECL = re.compile(r'^(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)', re.M)

def test_every_bundle_is_its_modules_concatenated():
    for name in builder.LAYERS:
        assert (builder.OUTDIR/name).read_text() == builder.bundle(name), \
            f'{name} is stale; run python tools/build_ide_js.py'

def test_the_order_is_complete_and_names_nothing_that_is_not_there():
    "A module added to a block but left out of `LAYERS` would silently never load."
    assert builder.missing() == []
    assert builder.orphans() == []

def test_the_bundles_are_what_the_application_serves():
    "`core.web.IDE_BUNDLES` is the serving order; the build must produce exactly those."
    from leela.core.web import IDE_BUNDLES
    assert tuple(builder.LAYERS) == IDE_BUNDLES
    for name in IDE_BUNDLES: assert (builder.OUTDIR/name).is_file(), name

def test_the_dispatch_table_is_why_there_is_one_script_tag():
    """`ACTIONS` holds bare references to functions from across the client, read the moment it
    is evaluated. A function declaration hoists to the top of its own script and no further, so
    a second script tag would evaluate the table before those names existed. This is the
    measurement behind `LAYERS` having one entry; it changes when the entries become thunks.
    """
    import re
    mods = builder.modules()
    where = {}
    for i, p in enumerate(mods):
        for m in re.finditer(r'^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)', p.read_text(), re.M):
            where.setdefault(m.group(1), i)
    actions = next(i for i, p in enumerate(mods) if p.name == 'actions.js')
    bare = re.findall(r'^\s+[A-Za-z_$][\w$]*:\s*([A-Za-z_$][\w$]*),?$',
                      mods[actions].read_text(), re.M)
    forward = sorted({n for n in bare if where.get(n, -1) > actions})
    assert forward, 'the eager forward references are gone; LAYERS can be split now'
    assert len(builder.LAYERS) == 1, 'more than one bundle while the table still reads ahead'
    assert 'showHelp' in forward and 'quickOpen' in forward

def test_every_module_ends_with_a_newline():
    "Without one a module's last line fuses into the next module's first."
    assert [p.name for p in builder.modules() if not p.read_text().endswith('\n')] == []

def test_no_name_is_declared_in_two_modules():
    "One shared scope, so the second declaration wins and the first silently stops existing."
    decls = L(builder.modules()).map(lambda p: set(DECL.findall(p.read_text())))
    dupes = sorted(n for n, c in Counter(n for s in decls for n in s).items() if c > 1)
    assert dupes == [], f'declared in more than one module: {dupes}'

TOKENS = set('bg bg1 bg2 bg3 fg fg2 fg4 border accent sel selection-fg red green yellow orange blue '
             'purple aqua output warning log active-line bracket guide'.split())
BLOCK = re.compile(r'([^{}]*?)\{([^{}]*?)\}', re.S)
VARIANT = re.compile(r':root\[data-theme="(\w+)"\]\[data-mode="(dark|light)"\]\s*$')
LEGEND = ('accent', 'aqua', 'orange', 'green', 'blue')

def variants(values=False):
    "family, mode -> the `--lee-*` names that variant declares, or their values."
    out = {}
    for sel, body in BLOCK.findall(CSS):
        for one in sel.split(','):
            if m := VARIANT.search(one.strip()):
                out[m.groups()] = ({k: v.strip() for k, v in re.findall(r'--lee-([\w-]+):\s*([^;]+);', body)}
                                   if values else set(re.findall(r'--lee-([\w-]+):', body)))
    return out

def families():
    "The family names in the JS THEMES table."
    table = JS.split('const THEMES = {', 1)[1].split('\n};', 1)[0]
    return set(re.findall(r'^\s*(\w+):\s*\{', table, re.M))

def _lab(hex_):
    "sRGB hex to CIE Lab, so two colours compare the way an eye compares them."
    h = hex_.strip().lstrip('#')
    r, g, b = [int(h[i:i+2], 16)/255 for i in (0, 2, 4)]
    f = lambda c: c/12.92 if c <= .04045 else ((c + .055)/1.055)**2.4
    r, g, b = f(r), f(g), f(b)
    X, Y, Z = (.4124*r + .3576*g + .1805*b)/.95047, .2126*r + .7152*g + .0722*b, (.0193*r + .1192*g + .9505*b)/1.08883
    k = lambda t: t**(1/3) if t > .008856 else 7.787*t + 16/116
    X, Y, Z = k(X), k(Y), k(Z)
    return 116*Y - 16, 500*(X - Y), 200*(Y - Z)

def _dE(a, b): return sum((x - y)**2 for x, y in zip(_lab(a), _lab(b)))**.5

def test_every_theme_family_exists_in_both_css_and_js():
    fams = families()
    assert fams >= {'leela', 'cursor', 'vscode', 'jetbrains', 'solarized', 'gruvbox', 'nord', 'dracula'}
    assert {f for f, _ in variants()} == fams, 'a family exists in only one of CSS and JS'
    for f in fams: assert (f, 'dark') in variants() and (f, 'light') in variants(), f

def test_every_theme_variant_declares_every_token():
    for (family, mode), names in variants().items():
        assert not (TOKENS - names), f'{family}/{mode} is missing {sorted(TOKENS - names)}'
        assert 'space-mark' in names, f'{family}/{mode}'

def test_the_legend_colours_stay_distinguishable_in_every_variant():
    "Two identical legend colours make a chart unreadable, and dark modes drift together."
    import itertools
    for (fam, mode), tokens in variants(values=True).items():
        for a, b in [*itertools.combinations(LEGEND, 2), ('blue', 'purple')]:
            assert tokens[a].lower() != tokens[b].lower(), f'{fam} {mode}: {a} and {b} are both {tokens[a]}'
            assert _dE(tokens[a], tokens[b]) > 5, f'{fam} {mode}: {a} and {b} are indistinguishable'

def test_density_is_its_own_axis_and_not_a_property_of_a_family():
    "Tight chrome came from the cursor theme, but any family must be able to wear it."
    keyed = re.findall(r':root\[data-density="tight"\](\[data-mode="\w+"\])?\s+\.lee-', CSS)
    assert keyed and not all(keyed), 'density rules must exist and not all be mode-specific'
    assert re.findall(r':root\[data-theme="\w+"\]\s+\.lee-', CSS) == [], 'chrome keyed to a family'
