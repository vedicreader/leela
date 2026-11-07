"Every text token meets WCAG AA (4.5:1) on every background token, in every theme variant, from `lee-ide.css` itself."
import re
from pathlib import Path
import pytest

CSS = (Path(__file__).parents[1]/'leela/static/lee-ide.css').read_text()
BGS, TEXT = ('bg', 'bg1', 'bg2'), ('fg', 'fg2', 'fg4', 'output')
#: The default family carries status text in its colour tokens too; the named families keep their canonical syntax palettes.
STATUS = ('warning', 'log', 'red', 'green', 'yellow', 'accent')

def _lum(h):
    c = [int(h[i:i+2], 16)/255 for i in (1, 3, 5)]
    r, g, b = [x/12.92 if x <= .03928 else ((x+.055)/1.055)**2.4 for x in c]
    return .2126*r + .7152*g + .0722*b

def ratio(a, b):
    lo, hi = sorted([_lum(a), _lum(b)])
    return (hi+.05)/(lo+.05)

def variants():
    for m in re.finditer(r'(:root[^{]*)\{([^}]*--lee-bg:[^}]*)\}', CSS):
        yield m.group(1).strip().splitlines()[-1].strip(), dict(re.findall(r'--lee-([\w-]+):\s*(#[0-9a-fA-F]{6})\b', m.group(2)))

def test_the_ratio_matches_known_wcag_values():
    assert round(ratio('#000000', '#ffffff'), 1) == 21.0
    assert round(ratio('#767676', '#ffffff'), 2) == 4.54

def test_every_variant_is_found():
    vs = dict(variants())
    assert len(vs) >= 20 and ':root[data-theme="leela"][data-mode="dark"]' in vs and ':root[data-theme="leela"][data-mode="light"]' in vs

@pytest.mark.parametrize('sel,toks', list(variants()), ids=lambda v: v if isinstance(v, str) else '')
def test_text_tokens_meet_aa_on_every_background(sel, toks):
    texts = TEXT + (STATUS if '"leela"' in sel or 'not(' in sel else ())
    bad = [(f, b, round(ratio(toks[f], toks[b]), 2)) for f in texts for b in BGS if ratio(toks[f], toks[b]) < 4.5]
    assert not bad, f'{sel}: {bad}'
