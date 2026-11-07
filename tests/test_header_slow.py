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

def test_tab_strip_takes_the_free_row_width_and_row_two_names_are_unique(tmp_path):
    "The strip measured `#tabbar`, which is only as wide as its tabs, so at 1440px it kept one tab and `+N`; two row-2 buttons were both `File`."
    for i in range(5): (tmp_path/f'f{i}.py').write_text(f'v = {i}\n')
    async def go(pg):
        await pg.set_viewport_size({'width': 1440, 'height': 900})
        for i in range(5): await pg.evaluate('p => leeOpenFile(p)', str(tmp_path/f'f{i}.py'))
        await pg.wait_for_function("document.querySelectorAll('.lee-tab').length === 5")
        await pg.wait_for_timeout(300)
        return await pg.evaluate("""() => ({shown: [...document.querySelectorAll('.lee-tab')].filter(t => t.offsetParent).length,
          more: document.querySelector('#taboverflow').hidden,
          names: [...document.querySelectorAll('#tabrow button')].filter(b => b.offsetParent && !b.closest('#tabbar')).map(b => b.textContent.trim()).filter(Boolean)})""")
    got = asyncio.run(_on_page(go, roots=[str(tmp_path)]))
    assert (got['shown'], got['more']) == (5, True), got
    assert len(got['names']) == len(set(got['names'])), got['names']

def test_git_pane_rows_show_the_file_names(tmp_path):
    "The row buttons were hidden with `opacity: 0` but kept their width, so a changed file showed no name."
    d = _repo(tmp_path)
    async def go(pg):
        await pg.set_viewport_size({'width': 1440, 'height': 900})
        await pg.evaluate("() => { leePane('left', true); leeLeft('git'); }")
        await pg.wait_for_function("document.querySelectorAll('.lee-git-panel .lee-git-change').length >= 3")
        clipped = await pg.evaluate("() => [...document.querySelectorAll('.lee-git-panel .lee-git-file')].filter(b => b.scrollWidth > b.clientWidth + 1).map(b => b.textContent)")
        row = pg.locator('.lee-git-panel .lee-git-change').first
        await row.hover()
        return clipped, await row.locator('[data-open]').is_visible()
    clipped, hovered = asyncio.run(_on_page(go, roots=[str(d)]))
    assert not clipped, clipped
    assert hovered, 'the row actions still show on hover'

def test_full_screen_side_pane_starts_below_the_header(tmp_path):
    "A full-screen pane sat at `top: 34px`, the old header height, and covered the second header row."
    async def go(pg):
        await pg.set_viewport_size({'width': 1440, 'height': 900})
        await pg.evaluate("() => { leePane('left', true); localStorage.setItem('lee-expand', 'left:full'); leeSyncExpand(); }")
        await pg.wait_for_function("document.querySelector('#shell').classList.contains('expand-full')")
        return await pg.evaluate("() => [document.querySelector('#left').getBoundingClientRect().top, document.querySelector('#header').getBoundingClientRect().bottom]")
    top, header = asyncio.run(_on_page(go, roots=[str(tmp_path)]))
    assert top == header == 92, (top, header)

def test_files_pane_header_fits_and_the_rest_wait_in_the_menu(tmp_path):
    "`open…`, `add…` and `⋯` were drawn past the Files pane over the editor."
    async def go(pg):
        await pg.set_viewport_size({'width': 1440, 'height': 900})
        await pg.evaluate("() => { leePane('left', true); leeLeft('files'); }")
        await pg.wait_for_timeout(200)
        return await pg.evaluate("""() => { const h = document.querySelector('.lee-files .lee-phead'), r = h.getBoundingClientRect();
          const kids = [...h.querySelectorAll('button')], shown = kids.filter(b => b.offsetParent);
          return {spill: Math.max(...shown.map(b => b.getBoundingClientRect().right)) - r.right,
                  hidden: kids.filter(b => !b.offsetParent).map(b => b.dataset.action),
                  menu: (lee.menus.files || []).map(m => m.action)}; }""")
    got = asyncio.run(_on_page(go, roots=[str(tmp_path)]))
    assert got['spill'] <= 0, got
    assert {'open_folder', 'add_root'} <= set(got['hidden']) and set(got['hidden']) <= set(got['menu']), got
