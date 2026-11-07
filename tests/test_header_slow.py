"The header in a real browser: title, brand, folder, branch and sync, the room per platform, and screenshots in light and dark for the owner."

import pytest

pytestmark = pytest.mark.slow

import asyncio, json, os, subprocess
from pathlib import Path

pytest.importorskip('playwright.async_api')
from test_web_slow import _on_page   # noqa: E402

SHOTS = Path(os.environ.get('LEELA_HEADER_SHOTS', '/tmp/header-shots'))

def _repo(root):
    "A git folder named `karma`, one commit ahead of its remote and two behind, with a notebook and three new files."
    run = lambda d, *a: subprocess.run(['git', '-C', str(d), '-c', 'user.email=t@t', '-c', 'user.name=t', *a], check=True, capture_output=True)
    d, bare, other = root/'karma', root/'origin.git', root/'other'
    d.mkdir(); run(root, 'init', '-q', '--bare', '-b', 'master', str(bare)); run(d, 'init', '-q', '-b', 'master')
    cell = {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': 'x = 1'}
    (d/'01_karma.ipynb').write_text(json.dumps({'cells': [cell], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    (d/'pyproject.toml').write_text('[project]\nname = "karma"\n')
    run(d, 'add', '.'); run(d, 'commit', '-qm', 'one'); run(d, 'remote', 'add', 'origin', str(bare)); run(d, 'push', '-qu', 'origin', 'master')
    run(root, 'clone', '-q', str(bare), str(other))
    for n in ('two', 'three'): (other/f'{n}.txt').write_text(n); run(other, 'add', '.'); run(other, 'commit', '-qm', n)
    run(other, 'push', '-q'); run(d, 'fetch', '-q')
    (d/'README.md').write_text('karma\n'); run(d, 'add', '.'); run(d, 'commit', '-qm', 'four')
    for f in ('a.py', 'b.py', 'c.py'): (d/f).write_text('x = 1\n')
    return d.resolve()

ROW = """() => { const r = s => document.querySelector(s).getBoundingClientRect(), q = s => document.querySelector(s);
  return {top: r('#titlebar').height, tabs: r('#tabrow').height, toolbarInRow: !!q('#tabrow #toolbar'),
    pad: getComputedStyle(q('#titlebar')).paddingLeft, brand: q('.lee-wordmark').textContent,
    folder: q('#workspacename').textContent, branch: q('#gitpill .lee-branch-name').textContent,
    count: q('#gitpill .lee-change-count').hidden ? '' : q('#gitpill .lee-change-count').textContent,
    pull: q('#gitpull').hidden ? null : q('#gitpull').textContent, push: q('#gitpush').hidden ? null : q('#gitpush').textContent,
    state: q('#gitpill').dataset.state, glyph: getComputedStyle(q('#gitpill .lee-branch-glyph')).display,
    text: q('#header').textContent, title: document.title}; }"""

def test_header_rows_title_pills_and_screenshots(tmp_path):
    d = _repo(tmp_path)
    async def go(pg):
        await pg.set_viewport_size({'width': 1440, 'height': 900})
        await pg.evaluate('p => leeOpenFile(p)', str(d/'01_karma.ipynb'))
        await pg.wait_for_function("() => document.querySelectorAll('.lee-tab').length >= 1 && document.title.endsWith('notebook')")
        await pg.wait_for_function("() => !document.querySelector('#gitpill .lee-change-count').hidden && !document.querySelector('#gitpull').hidden")
        got = {'first': await pg.evaluate(ROW)}
        # Painted and read in one turn: the git poll repaints the pill from the real repository between turns.
        paint = lambda call: pg.evaluate(f"() => {{ {call}; return ({ROW})(); }}")
        got['even'] = await paint("paintBranchPill({branch: 'master', changes: [1, 2, 3], ahead: 0, behind: 0})")
        for st in ('nogit', 'pending', 'error'): got[st] = await paint(f"paintBranchPill(null, '{st}')")
        # Headless Chromium's screen is its viewport, so it reads as full screen; a real window is smaller than its screen.
        await pg.evaluate("() => { document.documentElement.classList.remove('lee-fullscreen'); document.documentElement.classList.replace('lee-titlebar-browser', 'lee-titlebar-mac'); }")
        got['mac'] = await pg.evaluate(ROW)
        await pg.evaluate("() => document.documentElement.classList.add('lee-fullscreen')")
        got['macfull'] = await pg.evaluate(ROW)
        await pg.evaluate("() => { document.documentElement.classList.remove('lee-fullscreen'); document.documentElement.classList.replace('lee-titlebar-mac', 'lee-titlebar-win'); }")
        got['win'] = await pg.evaluate(ROW)
        await pg.evaluate("() => document.documentElement.classList.replace('lee-titlebar-win', 'lee-titlebar-browser')")
        await pg.evaluate('() => refreshGitPill()')
        SHOTS.mkdir(parents=True, exist_ok=True)
        for mode in ('light', 'dark'):
            await pg.evaluate(f"() => applyTheme('leela:{mode}:relaxed')")
            await pg.wait_for_function(f"() => document.documentElement.dataset.mode === '{mode}'")
            await pg.wait_for_timeout(500)
            await pg.screenshot(path=str(SHOTS/f'{mode}.png'), clip={'x': 0, 'y': 0, 'width': 1440, 'height': 200})
        return got
    got = asyncio.run(_on_page(go, roots=[str(d)], dpr=2))
    f = got['first']
    assert (f['top'], f['tabs'], f['toolbarInRow']) == (52, 40, True), 'two rows; the old toolbar row is gone'
    assert f['title'] == 'Leela · karma · notebook' and f['brand'] == 'Leela' and f['folder'] == 'karma', f
    assert (f['branch'], f['count'], f['pull'].strip(), f['push'].strip(), f['state']) == ('master', '3', '2', '1', 'branch'), f
    assert '⍁' not in f['text'] and '⭮' not in f['text'] and '—' not in f['title']
    assert (got['even']['pull'], got['even']['push'], got['even']['count']) == (None, None, '3'), 'arrows hidden at 0/0'

    assert [got[k]['branch'] for k in ('nogit', 'pending', 'error')] == ['no git', 'git …', 'git ?']
    assert all(got[k]['pull'] is None and got[k]['count'] == '' and got[k]['glyph'] == 'none' for k in ('nogit', 'pending', 'error'))
    assert (f['pad'], got['mac']['pad'], got['macfull']['pad'], got['win']['pad']) == ('16px', '94px', '16px', '16px'), \
        'room for the traffic lights only in a unified macOS window out of full screen'
    assert (SHOTS/'light.png').stat().st_size and (SHOTS/'dark.png').stat().st_size
