"The review's UX items in a real browser: the welcome screen, landmarks and tabs, the palette and menus, focus, toasts, tables, paths and the exec box."

import pytest

pytestmark = pytest.mark.slow

import asyncio, json, os, subprocess
from pathlib import Path

pytest.importorskip('playwright.async_api')
from test_web_slow import _on_page   # noqa: E402

PACKAGE_WORDS = ('Kosha', 'Fossick', 'Vishalakshi', 'Ramabana', 'CodeMirror', 'FTS5')

WELCOME = """() => { const q = s => document.querySelector(s), e = q('#editor .lee-empty');
  return {lang: document.documentElement.lang, h1: [...document.querySelectorAll('h1')].map(h => h.textContent),
    main: document.querySelectorAll('main, [role=main]').length, banner: !!q('header#header'), footer: !!q('footer.lee-footer'),
    text: e.textContent, kbd: [...e.querySelectorAll('kbd')].map(k => k.textContent),
    pill: [q('#gitpill').dataset.state, getComputedStyle(q('#gitpill')).display],
    setup: !!q('.lee-agent-welcome [onclick*=leeAgentState]')}; }"""

TABLISTS = """() => [...document.querySelectorAll('[role=tablist]')].filter(t => t.offsetParent || t.closest('#header, #right, #bottomdock')).map(t => ({
  label: t.getAttribute('aria-label'), kids: [...t.children].map(c => c.getAttribute('role')),
  selected: [...t.children].filter(c => c.getAttribute('aria-selected') === 'true').length}))"""

def test_the_welcome_screen_speaks_plainly_and_the_page_has_landmarks():
    "S19, S20, S21 and N2: package words, em dashes and `mod+o` on the welcome screen; `git …` for ever; a setup card with no folder; no `lang`, `main` or h1."
    async def go(pg):
        await pg.wait_for_function("() => document.querySelector('#gitpill').dataset.state === 'nofolder'")
        got = await pg.evaluate(WELCOME)
        got['tabs'] = await pg.evaluate(TABLISTS)
        await pg.evaluate("() => leeRight('vars')")
        got['vars'] = await pg.evaluate("() => [...document.querySelectorAll('.lee-righttab')].map(t => t.getAttribute('aria-selected'))")
        return got
    got = asyncio.run(_on_page(go))
    assert got['lang'] == 'en' and got['h1'] == ['Leela'] and got['main'] == 1 and got['banner'] and got['footer'], got
    assert not any(w in got['text'] for w in PACKAGE_WORDS) and '—' not in got['text'], got['text']
    assert got['kbd'] and not any('mod+' in k for k in got['kbd']) and got['kbd'][0] in ('⌘O', 'Ctrl+O'), got['kbd']
    assert got['pill'] == ['nofolder', 'none'], 'no folder, no git pill'
    assert not got['setup'], 'agent state belongs to a folder'
    for t in got['tabs']: assert set(t['kids']) <= {'tab'} and t['selected'] == (1 if t['kids'] else 0), t
    assert {'bottom tools', 'right tools'} <= {t['label'] for t in got['tabs']}
    assert got['vars'] == ['false', 'true', 'false', 'false']

def _project(root):
    d = root/'monsoon'; d.mkdir()
    run = lambda *a: subprocess.run(['git', '-C', str(d), '-c', 'user.email=t@t', '-c', 'user.name=t', *a], check=True, capture_output=True)
    run('init', '-q', '-b', 'main')
    (d/'cities.py').write_text('x = 1\n'); (d/'empty').mkdir()
    rows = ''.join(f'<tr><th>{i}</th><td>{c}</td></tr>' for i, c in enumerate(('Pune', 'Delhi')))
    html = f'<style>.dataframe tbody tr th {{vertical-align: top;}}</style><table border="1" class="dataframe"><thead><tr><th></th><th>city</th></tr></thead><tbody>{rows}</tbody></table>'
    cell = {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': 1, 'source': 'df',
            'outputs': [{'output_type': 'execute_result', 'execution_count': 1, 'metadata': {}, 'data': {'text/html': html, 'text/plain': 'df'}}]}
    (d/'rain.ipynb').write_text(json.dumps({'cells': [cell], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    run('add', 'cities.py'); run('commit', '-qm', 'one'); (d/'cities.py').write_text('x = 2\n')
    return d.resolve()

PALETTE = """() => { leeAct('palette'); const rows = [...document.querySelectorAll('#cplist .lee-mrow')], box = document.querySelector('#cplist').getBoundingClientRect();
  return {label: document.querySelector('#cp').getAttribute('aria-label'), first: rows[0].textContent, bottom: box.bottom, h: innerHeight,
    global: rows.filter(r => /global/.test(r.textContent)).length, lower: rows.filter(r => /^(?!nbdev|fastship|uv)[a-z]/.test(r.firstChild.textContent)).length}; }"""

MENU = """() => { const r = document.querySelector('.lee-cell').getBoundingClientRect(); openMenu('cell', r.left + 40, r.top + 10);
  const m = document.querySelector('.lee-ctxmenu'), b = m.getBoundingClientRect(); m.focus();
  return {bottom: b.bottom, h: innerHeight, scrolls: m.scrollHeight > m.clientHeight, outline: getComputedStyle(m).outlineStyle,
    lower: [...m.querySelectorAll('.lee-menuitem > span')].filter(s => /^(?!nbdev|fastship|uv)[a-z]/.test(s.textContent)).map(s => s.textContent)}; }"""

TABLE = """() => { const root = document.querySelector('.lee-out-rich').shadowRoot, td = root.querySelector('td'), s = getComputedStyle(td);
  return {left: s.borderLeftWidth, bottom: s.borderBottomColor, line: getComputedStyle(document.documentElement).getPropertyValue('--lee-border').trim()}; }"""

def test_the_palette_menus_paths_tables_and_toasts_in_both_themes(tmp_path):
    "S22 and S23: an empty go-to-file box, ` · global` rows, menus off screen, rings round the tree and the menu, absolute paths, white table borders, toasts over the dock pill, a vertical approval label, centred git rows."
    d = _project(tmp_path)
    async def go(pg):
        await pg.set_viewport_size({'width': 900, 'height': 700})
        got = {}
        await pg.evaluate("() => leeAct('quick_open')"); await pg.fill('#qo', 'zzqqxx')
        await pg.wait_for_selector('#qolist .lee-qo-none'); got['none'] = await pg.text_content('#qolist')
        await pg.fill('#qo', 'cities'); await pg.wait_for_selector('#qolist .lee-mrow')
        got['path'] = await pg.text_content('#qolist .lee-mrow .sub'); await pg.keyboard.press('Escape')
        got['palette'] = await pg.evaluate(PALETTE); await pg.keyboard.press('Escape')
        await pg.evaluate('p => leeOpenFile(p)', str(d/'rain.ipynb')); await pg.wait_for_selector('.lee-out-rich', timeout=15000)
        for mode in ('light', 'dark'):
            await pg.evaluate(f"() => applyTheme('leela:{mode}:relaxed')")
            await pg.wait_for_function(f"() => document.documentElement.dataset.mode === '{mode}'")
            got[f'table-{mode}'] = await pg.evaluate(TABLE)
        got['menu'] = await pg.evaluate(MENU); await pg.evaluate('closeMenu()')
        got['tree'] = await pg.evaluate("() => { const t = document.querySelector('#filetree'); t.focus(); return getComputedStyle(t).outlineStyle; }")
        got['toast'] = await pg.evaluate("""async () => { leePane('bottom', false); status('a long enough message to reach the pill', 'err');
          await new Promise(r => setTimeout(r, 300)); const a = document.querySelector('#status').getBoundingClientRect(), b = document.querySelector('.restore-bottom').getBoundingClientRect();
          leePane('bottom', true); return a.bottom <= b.top || b.bottom <= a.top; }""")
        got['label'] = await pg.evaluate("""() => { leePane('right', true); leeRight('agent');
          showApproval({id: 'a1', tool: 'view_file', args: {path: 'a.py'}, schemas: [{name: 'view_file', group: 'files', description: '', fields: []}]});
          const r = document.querySelector('.lee-run-policy-label > span').getBoundingClientRect(); return r.width > r.height; }""")
        await pg.evaluate("() => leeLeft('git')"); await pg.wait_for_selector('.lee-git-change .lee-git-file', timeout=15000)
        got['git'] = await pg.evaluate("""() => { const b = document.querySelector('.lee-git-change .lee-git-file'), s = b.querySelector('.lee-git-status');
          return [getComputedStyle(b).justifyContent, Math.round(s.getBoundingClientRect().left - b.getBoundingClientRect().left)]; }""")
        await pg.evaluate("() => leeAct('settings')"); await pg.wait_for_selector('.lee-settings-scope > span')
        got['settings'] = await pg.evaluate("() => [...document.querySelectorAll('.lee-settings-scope label')].map(l => l.getBoundingClientRect().height)")
        return got
    got = asyncio.run(_on_page(go, roots=[str(d)]))
    assert got['none'].strip() == 'No file matches.', got['none']
    assert got['path'] == 'monsoon/cities.py', 'a path inside a root reads from the root'
    p = got['palette']
    assert p['label'] == 'Command palette' and p['global'] == 0 and p['lower'] == 0 and p['bottom'] <= p['h'], p
    for mode in ('light', 'dark'):
        t = got[f'table-{mode}']
        assert t['left'] == '0px' and t['bottom'] not in ('rgb(128, 128, 128)', 'rgb(255, 255, 255)'), (mode, t)
    m = got['menu']
    assert m['bottom'] <= m['h'] and m['scrolls'] and m['outline'] == 'none' and not m['lower'], m
    assert got['tree'] == 'none', 'the tree container draws no focus ring'
    assert got['toast'], 'the toast clears the terminal / exec pill'
    assert got['label'], '"After this" stays on one line'
    assert got['git'][0] == 'flex-start' and got['git'][1] < 8, got['git']
    assert max(got['settings']) < 40, 'Save to and Apply to stay on one line'

def test_an_empty_folder_says_so_and_tab_leaves_the_exec_box(tmp_path):
    "N2: an open empty folder showed nothing; a Tab walk that reached the exec box stayed in it; ⌘O in a browser tab waited 1.5 s each time."
    d = _project(tmp_path)
    async def go(pg):
        got = {}
        await pg.evaluate("p => loadTreeDir(document.querySelector(`.lee-root[data-path='${p}']`))", str(d))
        await pg.wait_for_selector(f".lee-dir[data-path='{d/'empty'}']")
        await pg.evaluate("p => loadTreeDir(document.querySelector(`.lee-dir[data-path='${p}']`))", str(d/'empty'))
        got['empty'] = await pg.evaluate("p => getComputedStyle(document.querySelector(`.lee-dir[data-path='${p}'] > .lee-kids`), '::before').content", str(d/'empty'))
        inside = "() => !!document.activeElement.closest('#execbox')"
        await pg.evaluate("() => { leeDock('exec'); lee.editors.get('exec').focus(); }")
        await pg.keyboard.press('Tab'); got['exec'] = [await pg.evaluate(inside)]
        await pg.keyboard.press('Shift+Tab'); await pg.keyboard.press('Shift+Tab'); got['exec'].append(await pg.evaluate(inside))
        await pg.evaluate("() => { const v = lee.editors.get('exec'); LeeCM.setDoc(v, 'x = 1'); v.focus(); }")
        await pg.keyboard.press('Tab'); got['exec'].append(await pg.evaluate(inside))
        await pg.keyboard.press('Escape'); await pg.keyboard.press('Tab'); got['exec'].append(await pg.evaluate(inside))
        await pg.wait_for_timeout(1700)
        got['open'] = await pg.evaluate("""async () => { const t = performance.now(); leeAct('open_folder');
          while (!document.querySelector('.lee-modal input') && performance.now() - t < 3000) await new Promise(r => setTimeout(r, 10));
          return performance.now() - t; }""")
        return got
    got = asyncio.run(_on_page(go, roots=[str(d)]))
    assert 'empty' in got['empty'], got
    assert got['exec'] == [False, False, True, False], 'Tab passes through an empty box both ways; with code, Tab indents and Escape then Tab leaves'
    assert got['open'] < 500, f"⌘O asked after {got['open']:.0f} ms"

WSMENU = """async () => { await leeWorkspaceMenu(document.querySelector('#workspacepill'));
  const m = document.querySelector('.lee-ctxmenu'), s = [...m.querySelectorAll('.lee-menuitem small')];
  return {sideways: m.scrollWidth > m.clientWidth, oneLine: s.every(x => x.getBoundingClientRect().height < 22), titled: s.every(x => x.title),
    details: s.map(x => x.textContent)}; }"""

def test_the_folder_menu_keeps_a_long_path_on_one_line(tmp_path):
    "A folder deep under /private/var wrapped onto two lines in the workspace menu and gave it a sideways scroll bar."
    d = tmp_path/('a-very-long-folder-name-for-the-menu-' * 3)/'demo'; d.mkdir(parents=True)
    async def go(pg):
        await pg.set_viewport_size({'width': 1440, 'height': 900})
        return await pg.evaluate(WSMENU)
    got = asyncio.run(_on_page(go, roots=[str(d)]))
    assert not got['sideways'] and got['oneLine'] and got['titled'], got

BRAND = """() => { const box = e => { const r = document.createRange(); r.selectNodeContents(e); return r.getBoundingClientRect(); };
  const w = document.querySelector('.lee-wordmark'), n = document.querySelector('#workspacename'), m = document.querySelector('.lee-brand .lee-mark');
  const base = e => { const s = document.createElement('span'); s.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline'; e.appendChild(s);
    const y = s.getBoundingClientRect().top; s.remove(); return y; };
  const mb = m.getBoundingClientRect(), wb = box(w);
  const g = document.querySelector('#gitpill'), f = document.querySelector('.lee-menubar-btn'), h = document.querySelector('#header').getBoundingClientRect(), p = document.querySelector('#workspacepill').getBoundingClientRect();
  return {gap: Math.abs(base(w) - base(n)), row: Math.max(...[w, n, g, f].map(base)) - Math.min(...[w, n, g, f].map(base)), inside: p.top >= h.top && p.bottom <= h.bottom,
    cut: n.scrollWidth > n.clientWidth, mark: Math.abs((mb.top + mb.bottom) / 2 - (wb.top + wb.bottom) / 2)}; }"""

def test_the_brand_and_the_folder_share_a_baseline_and_the_folder_shows_whole(tmp_path):
    "The serif Leela and the folder sat 4 px above the branch and the menus, and a narrow window cut the folder name."
    d = tmp_path/'karma'; d.mkdir()
    async def go(pg):
        await pg.set_viewport_size({'width': 900, 'height': 600})
        return await pg.evaluate(BRAND)
    got = asyncio.run(_on_page(go, roots=[str(d)]))
    assert got['gap'] <= 1 and got['row'] <= 1 and got['inside'] and not got['cut'] and got['mark'] <= 3, 'Leela, the folder, the branch and File share one baseline'
