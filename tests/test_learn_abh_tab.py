from pathlib import Path

from leela.blocks.learn import walk


def test_walk_tab_loads_the_pane_page_with_leela_htmx():
    src = (walk.__file__.replace('walk.py', 'walk.js'))
    js = open(src).read()
    assert 'class="abh"' in js
    assert 'hx-get="' in js and '/w/' in js
    assert 'hx-select="main"' in js
    assert 'hx-target="closest .abh"' in js
    assert 'hx-boost="true"' in js
    assert 'hx-push-url="false"' in js
    assert 'pane=1' in js
    assert 'vendor/htmx' not in js and 'fasthtml.js' not in js


def test_abh_styles_are_scoped_and_follow_leela_tokens():
    css = walk.abh_styles()
    tokens = Path(walk.__file__).with_name('abh.css').read_text()
    assert css.startswith('@scope (.abh)')
    assert 'body {' not in css and '\nmain {' not in css
    expected = {'--bg': '--lee-bg', '--fg': '--lee-fg', '--ink2': '--lee-fg2', '--mute': '--lee-fg4', '--line': '--lee-border', '--rule': '--lee-border', '--raised': '--lee-bg1', '--sunken': '--lee-bg2', '--acc': '--lee-accent', '--ok': '--lee-green', '--no': '--lee-orange', '--bad': '--lee-red'}
    for name, lee in expected.items(): assert f'{name}: var({lee})' in tokens
