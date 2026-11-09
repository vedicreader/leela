import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

from pathlib import Path
from tests.test_learn_surface_talk_slow import _env, _open, _watch
from tests.test_learn_tab_pages_slow import _env as _check_env, _run

OUT = str(Path(__file__).resolve().parents[1]/'target')
HIT = """() => {
  const st = document.querySelector('#status'), was = st.hidden; st.hidden = false;
  const box = e => { const r = e.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom} };
  const vis = s => { const e = document.querySelector(s); return e && getComputedStyle(e).display !== 'none' ? [s, box(e)] : null };
  const guards = [vis('.restore-left'), vis('.restore-right'), vis('.restore-bottom')].filter(Boolean);
  const clip = document.querySelector('.lee-learn-tab > .abh').getBoundingClientRect(), tab = document.querySelector('.lee-learn-tab');
  const bad = [];
  for (const e of tab.querySelectorAll('*')) {
    if (e.closest('[hidden]') || getComputedStyle(e).display === 'none') continue;
    let r = box(e); if (e.closest('.abh')) r = {l: Math.max(r.l, clip.left), t: Math.max(r.t, clip.top), r: Math.min(r.r, clip.right), b: Math.min(r.b, clip.bottom)};
    if (r.r - r.l < 1 || r.b - r.t < 1) continue;
    for (const [n, g] of guards) if (r.l < g.r && g.l < r.r && r.t < g.b && g.t < r.b) bad.push([n, e.tagName + '.' + e.className + '#' + e.id, r, g]);
  }
  st.hidden = was;
  return {guards: guards.map(g => g[0]), bad: bad.slice(0, 5)};
}"""
ROWS = "() => { const r = [...document.querySelector('#modebar').children].filter(e => e.offsetParent).map(e => e.getBoundingClientRect()); return Math.max(...r.map(x => x.top)) < Math.min(...r.map(x => x.bottom)) }"


def test_learn_page_clears_the_dock_handles_and_the_status_pill(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, tid = _env(monkeypatch)
    async def scenario(pg, ws, port):
        bad = _watch(pg)
        pages = [('step', f'/w/{jid}/0', '.abh #check .check'), ('graph', '/graph', '.abh #graph canvas'), ('talk', f'/t/{tid}', '.abh main'), ('overview', f'/w/{jid}', '.abh main')]
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')")
            for name, path, sel in pages:
                await _open(pg, ws, path, sel)
                assert 10 < (await pg.locator('#modebar').bounding_box())['height'] < 45
                hit = await pg.evaluate(HIT)
                assert not {'.restore-left', '.restore-bottom'} & set(hit['guards']), hit
                assert not hit['bad'], (name, hit['bad'])
                await pg.screenshot(path=f'{OUT}/f1-{name}-{mode}.png')
                assert await pg.evaluate(ROWS), name
        await _open(pg, ws, '/graph', '.abh #graph canvas')
        assert await pg.locator('.lee-learn-chips .lee-learn-chip').count() >= 1
        await pg.set_viewport_size(dict(width=860, height=900)); await pg.wait_for_timeout(500)
        assert not (await pg.evaluate(HIT))['bad']
        await pg.screenshot(path=f'{OUT}/f1-narrow-light.png')
        assert not bad, bad
        await pg.set_viewport_size(dict(width=1500, height=900)); await pg.wait_for_timeout(500)
        await pg.locator('.lee-tab', has_text='lesson.py').click(); await pg.wait_for_timeout(500)
        assert (await pg.locator('#toolbar').bounding_box())['height'] > 10
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_a_step_swapping_in_never_takes_the_focus_from_the_agent_prompt(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _check_env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await _open(pg, ws, f'/w/{jid}/0', '.abh #ans')
        await pg.evaluate("() => { window.seen = []; document.addEventListener('keydown', e => window.seen.push(document.activeElement.id), true) }")
        await pg.locator('#agentprompt').click(); await pg.locator('#agentprompt').fill('')
        swaps = pg.evaluate("async j => { for (const i of [1, 0, 1, 0, 1]) { await leeLearnNav(`/w/${j}/${i}`); await new Promise(r => setTimeout(r, 120)) } }", jid)
        text = 'typing while the walk swaps in'
        await pg.keyboard.type(text, delay=45)
        await swaps; await pg.wait_for_timeout(400)
        assert await pg.locator('#agentprompt').input_value() == text
        assert set(await pg.evaluate('window.seen')) == {'agentprompt'}
        assert await pg.evaluate('document.activeElement.id') == 'agentprompt'
    _run(tmp_path, scenario, dict(width=1500, height=900))
