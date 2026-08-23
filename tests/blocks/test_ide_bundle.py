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

def test_the_dispatch_table_holds_thunks_and_not_bare_references():
    """`ACTIONS` used to hold `help: showHelp`, read the moment the module ran. A function
    declaration hoists to the top of its own script and no further, so that pinned the whole
    client to one script tag. Every entry is a thunk now; a bare name would pin it again.
    """
    src = next(p for p in builder.modules() if p.name == 'actions.js').read_text()
    lines = src.split('\n')
    start = next(i for i, l in enumerate(lines) if l.startswith('const ACTIONS = {'))
    end = next(i for i, l in enumerate(lines) if i > start and l.startswith('};'))
    bare = [l.strip() for l in lines[start:end + 1]
            if re.match(r'^\s+[A-Za-z_$][\w$]*\s*:\s*[A-Za-z_$][\w$]*,?\s*$', l)]
    assert bare == [], f'bare references would pin the client to one script tag: {bare}'

def test_no_bundle_reads_a_later_bundles_declaration_at_load_time():
    """The failure this prevents is not graceful: the throw aborts the rest of that bundle, so
    every `let` after it stays in its temporal dead zone and the shell paints but does nothing.
    A bare name used as a value in a top-level literal is read when the module runs, so it must
    not name a function some later bundle declares.
    """
    mods = builder.modules()
    at, bundle_of = {}, {}
    for i, (name, names) in enumerate(builder.LAYERS.items()):
        for n in names: bundle_of[str(builder.PKG/n)] = i
    for i, p in enumerate(mods):
        for m in re.finditer(r'^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)', p.read_text(), re.M):
            at.setdefault(m.group(1), i)
    bad = []
    for i, p in enumerate(mods):
        for ln, line in enumerate(p.read_text().split('\n'), 1):
            m = (re.match(r'^\s+[A-Za-z_$][\w$]*\s*:\s*([A-Za-z_$][\w$]*),?\s*$', line)
                 or re.match(r'^ACTIONS(?:\.\w+|\[[^\]]+\])\s*=\s*([A-Za-z_$][\w$]*)\s*;?\s*$', line))
            if not m: continue
            j = at.get(m.group(1))
            if j is not None and bundle_of[str(mods[j])] > bundle_of[str(p)]:
                bad.append(f'{p.name}:{ln} reads {m.group(1)!r} from a later bundle')
    assert bad == [], bad

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

def test_no_rule_paints_one_activity_button_unlike_its_siblings():
    "A `[data-left=...]` background made the files tab a different colour from the rest of the rail."
    assert re.findall(r'\.lee-activity-btn\[data-left=[^\]]+\]', CSS) == []

def test_the_pill_neutralises_the_button_defaults():
    "`#runspill` is a button and `#kpill` a span, so the UA border and font must be overridden."
    rule = re.search(r'\.lee-pill \{(.*?)\}', CSS, re.S).group(1)
    for decl in ('appearance: none', '-webkit-appearance: none', 'border: 0', 'font-family: inherit',
                 'line-height:', 'align-items: center'): assert decl in rule, decl
