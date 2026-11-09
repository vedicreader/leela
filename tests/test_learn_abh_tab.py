import re
from pathlib import Path

from leela.blocks.learn import walk


def test_learn_tab_hosts_abhyasa_pages_under_the_prefix_with_leela_htmx():
    js = open(walk.__file__.replace('walk.py', 'walk.js')).read()
    assert 'class="abh"' in js and "LEARN = '/learn/abh'" in js and "LEARN + '/open'" in js
    assert "registerTabMount('learn_walk'" in js and "registerTabMount('learn'" in js
    assert "select: 'main'" in js and 'hx-push-url="false"' in js and "pane" in js
    assert 'vendor/htmx' not in js and 'fasthtml.js' not in js and 'pushState' not in js


def test_abh_styles_are_scoped_and_follow_leela_tokens():
    css = walk.abh_styles()
    tokens = Path(walk.__file__).with_name('abh.css').read_text()
    assert '@scope (.abh)' in css and css.startswith('@font-face')
    assert not re.search(r'(?m)^\s*(?:body|html|:root)\b', css) and '\nhtml' not in css and ':root' not in css and css.count('@scope (.abh)') == 1 and css.rstrip().endswith('}')
    assert '\nmain {' in css
    expected = {'--bg': '--lee-bg', '--fg': '--lee-fg', '--ink2': '--lee-fg2', '--mute': '--lee-fg4', '--line': '--lee-border', '--rule': '--lee-border', '--raised': '--lee-bg1', '--sunken': '--lee-bg2', '--acc': '--lee-accent', '--ok': '--lee-green', '--no': '--lee-orange', '--bad': '--lee-red'}
    for name, lee in expected.items(): assert f'{name}: var({lee})' in tokens
