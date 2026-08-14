"""Theme families: every family has both variants, and every variant is complete.

A half-defined variant does not fail — it inherits whatever the previous rule left behind and
looks subtly wrong — so completeness, not appearance, is what this guards.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastcore.all import L

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT/'leela/static/lee-ide.js').read_text()
CSS = (ROOT/'leela/static/lee-ide.css').read_text()

TOKENS = set('bg bg1 bg2 bg3 fg fg2 fg4 border accent sel selection-fg red green yellow orange blue '
             'purple aqua output warning log active-line bracket guide'.split())
BLOCK = re.compile(r'([^{}]*?)\{([^{}]*?)\}', re.S)
VARIANT = re.compile(r':root\[data-theme="(\w+)"\]\[data-mode="(dark|light)"\]\s*$')


def css_variants():
    "family, mode -> the --lee-* names that variant's block declares."
    out = {}
    for sel, body in BLOCK.findall(CSS):
        for one in sel.split(','):
            if m := VARIANT.search(one.strip()):
                out[m.groups()] = set(re.findall(r'--lee-([\w-]+):', body))
    return out


def js_families():
    "The family names in the JS THEMES table."
    table = JS.split('const THEMES = {', 1)[1].split('\n};', 1)[0]
    return set(re.findall(r'^\s*(\w+):\s*\{', table, re.M))


def test_every_family_ships_a_dark_and_a_light_variant():
    variants = css_variants()
    families = js_families()
    assert families >= {'leela', 'cursor', 'vscode', 'jetbrains', 'solarized', 'gruvbox', 'nord', 'dracula'}
    assert {f for f, _ in variants} == families, 'a family exists in only one of CSS and JS'
    for family in families:
        assert (family, 'dark') in variants and (family, 'light') in variants, family


def test_every_variant_declares_every_colour_token():
    """Missing tokens fall through to whatever :root had, which is another theme's colour."""
    for (family, mode), names in css_variants().items():
        assert not (TOKENS - names), f'{family}/{mode} is missing {sorted(TOKENS - names)}'


def test_whitespace_marks_have_their_own_token_in_every_variant():
    """The dots are drawn inside the selection, so --lee-fg4 washed out on light themes."""
    assert 'var(--lee-space-mark)' in CSS.split('.cm-lee-space-mark')[1].split('}')[0]
    assert 'var(--lee-space-mark)' in CSS.split('.cm-lee-tab-mark')[1].split('}')[0]
    for (family, mode), names in css_variants().items():
        assert 'space-mark' in names, f'{family}/{mode}'


def test_colour_scheme_is_only_ever_dark_or_light():
    """A family name is not a valid `color-scheme`; it is silently ignored when one lands there."""
    assigns = L(re.findall(r'colorScheme\s*=\s*([^;\n]+)', JS + (ROOT/'leela/app.py').read_text()))
    assert assigns, 'nothing sets colorScheme any more'
    for a in assigns: assert a.strip() in ('resolved', 'resolved;'), a


def test_density_is_its_own_axis_and_carries_the_chrome():
    """Tight chrome came from the cursor theme, but any family must be able to wear it."""
    assert ':root[data-density="tight"] .lee-phead' in CSS
    assert ':root[data-density="tight"] .lee-node.sel' in CSS
    # Structural rules key on density alone, so they apply in both modes and to every palette.
    keyed = re.findall(r':root\[data-density="tight"\](\[data-mode="\w+"\])?\s+\.lee-', CSS)
    assert keyed and not all(keyed)
    # Only the sans-serif face is cursor's own; nothing else may re-key structure onto a family.
    assert re.findall(r':root\[data-theme="\w+"\]\s+\.lee-', CSS) == []
    assert "const THEME_DENSITIES = ['tight', 'relaxed']" in JS


def test_density_reaches_the_document_before_the_first_paint():
    """Painting relaxed chrome and then tightening it a frame later is the flash this avoids."""
    app = (ROOT/'leela/app.py').read_text()
    assert 'dataset.density' in app and 'dataset.density' in JS
    for value in re.findall(r'dataset\.density\s*=\s*([^;\n]+)', JS):
        assert value.strip() == 'density'


def test_a_pre_family_preference_still_resolves():
    """`lee-theme` held system|dark|light|cursor; both readers must migrate it, not reset it."""
    for reader in (JS, (ROOT/'leela/app.py').read_text()):
        assert "dark: 'leela:dark:relaxed'" in reader and "cursor: 'cursor:light:tight'" in reader


def _lab(hex_):
    "sRGB hex to CIE Lab, so two colours can be compared the way an eye compares them."
    h = hex_.strip().lstrip('#')
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
    r, g, b = f(r), f(g), f(b)
    X, Y, Z = (.4124*r + .3576*g + .1805*b)/.95047, .2126*r + .7152*g + .0722*b, (.0193*r + .1192*g + .9505*b)/1.08883
    k = lambda t: t ** (1/3) if t > .008856 else 7.787 * t + 16/116
    X, Y, Z = k(X), k(Y), k(Z)
    return 116*Y - 16, 500*(X - Y), 200*(Y - Z)


def _dE(a, b): return sum((x - y) ** 2 for x, y in zip(_lab(a), _lab(b))) ** .5


#: The agent's activity legend paints five kinds at once -- search, view, edit, run, web -- so
#: these five are read against each other and cannot be the same colour. `blue` is also checked
#: against `purple`: they were literally the same hex in leela, which is how this test started.
LEGEND = ('accent', 'aqua', 'orange', 'green', 'blue')


def variant_colours():
    "family, mode -> the declared `--lee-*` values, not just their names."
    out = {}
    for sel, body in BLOCK.findall(CSS):
        for one in sel.split(','):
            if m := VARIANT.search(one.strip()):
                out[m.groups()] = {k: v.strip() for k, v in re.findall(r'--lee-([\w-]+):\s*([^;]+);', body)}
    return out


def test_no_variant_paints_two_legend_colours_the_same():
    """A duplicated hex is a copy-paste, not a palette choice, and it makes a legend unreadable.

    The bar is identity, not distance: palettes legitimately place two colours close together,
    and judging that is taste. Judging that `--lee-blue` is `--lee-accent` is not.
    """
    import itertools
    for (fam, mode), tokens in variant_colours().items():
        for a, b in [*itertools.combinations(LEGEND, 2), ('blue', 'purple')]:
            assert tokens[a].lower() != tokens[b].lower(), f'{fam} {mode}: {a} and {b} are both {tokens[a]}'
            assert _dE(tokens[a], tokens[b]) > 5, f'{fam} {mode}: {a} and {b} are indistinguishable'
