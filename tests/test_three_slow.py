"A rupaka `scene` loads three.js from beside lee-rupaka.js and draws its canvas: in a notebook, in a real lesson, on the presenter's slide and in the audience window."
import asyncio, json, shutil, tempfile
from pathlib import Path
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

from test_web_slow import _free_port, _serve, _started, fake_model   # noqa: E402
from leela.workspace import Workspace   # noqa: E402

SHOTS = Path(__file__).parents[1]/'target'/'rupaka'
LESSON = Path('/Users/71293/code/personal/orgs/vedicreader/lessons/panchanga/01_sky_and_angles.ipynb')
SCENES = {16: ('equator-ecliptic-tilt', 'Tilt', 'In one straight line'), 17: ('two-zeros-one-moon', 'Moon', 'sidereal longitude gets 1° smaller')}
CELL = '.lee-cell[data-i="{}"] .lee-md-cell .lee-rupaka'
STAGE = '.lee-stage .lee-slide .lee-rupaka'
FACTS = r"""(s) => { const r = document.querySelector(s)?.shadowRoot, st = r?.querySelector('[data-rk-gl]'), cv = st?.querySelector('canvas.gl');
  return st && {gl: st.dataset.rkGl, canvas: !!cv, w: cv?.width || 0, px: cv?.toDataURL() || '', vis: !!st.getClientRects().length && st.getBoundingClientRect().height > 50, text: r.textContent, three: !!window.RupakaTHREE,
    src: [...document.scripts].map(x => x.src).find(x => /\/three\.js/.test(x))}; }"""
DRAWN = '(s) => ["ready", "error"].includes(document.querySelector(s)?.shadowRoot?.querySelector("[data-rk-gl]")?.dataset.rkGl)'
NUDGE = r"""([s, k]) => { const i = document.querySelector(s).shadowRoot.querySelector(`input[type=range][aria-label^="${k}"]`);
  i.value = String(+i.max); i.dispatchEvent(new Event('input', {bubbles: true})); return +i.value; }"""

async def _on(root, go, mp):
    from leela.blocks.memory.memory import Memory
    mp.setenv('VISHALAKSHI_VAULT', str(root/'vault.db'))
    ws = Workspace(roots=[str(root)], approvals='auto')
    mp.setattr(ws, 'memory', Memory(path=root/'vault.db', offline=True))
    fake_model(ws)
    port = _free_port(); srv = _serve(ws, port); await _started(srv)
    try:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(headless=True, args=['--mute-audio'])
            try:
                pg = await b.new_page(viewport={'width': 1280, 'height': 1800})
                await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                await pg.wait_for_function('window.lee && lee.keys.length')
                return await go(pg)
            finally: await b.close()
    finally:
        srv.should_exit = True
        ws.shutdown_now()

def _in_tmp(fn):
    root = Path(tempfile.mkdtemp()).resolve()
    try: return fn(root)
    finally: shutil.rmtree(root, ignore_errors=True)

async def _lock(pg, sel, ans):
    "Answer the demo's gate with `ans` and lock it in, which shows its scene and frees its knobs."
    h = pg.locator(sel)
    await h.scroll_into_view_if_needed()
    await h.locator('.rk-gate .opts button', has_text=ans).click()
    await h.get_by_role('button', name='Lock in').click()

async def _drawn(pg, sel, shot):
    await pg.locator(sel).scroll_into_view_if_needed()
    await pg.wait_for_function(DRAWN, arg=sel, timeout=30000)
    await pg.wait_for_timeout(1500)
    SHOTS.mkdir(parents=True, exist_ok=True)
    await pg.locator(sel).screenshot(path=str(SHOTS/shot))
    return await pg.evaluate(FACTS, sel)

async def _knob(pg, sel, k, shot):
    "The canvas before and after the scene's slider `k` moves to its max, at the scene's last step, where every body shows."
    nxt = pg.locator(sel).get_by_role('button', name='Next')
    while await nxt.count() and await nxt.is_enabled(): await nxt.click(); await pg.wait_for_timeout(900)
    await pg.wait_for_timeout(900)
    before = (await pg.evaluate(FACTS, sel))['px']
    await pg.evaluate(NUDGE, [sel, k]); await pg.wait_for_timeout(1500)
    await pg.locator(sel).screenshot(path=str(SHOTS/shot))
    return before != (await pg.evaluate(FACTS, sel))['px']

def _ok(f, where):
    assert f and 'did not load' not in f['text'] and 'could not load' not in f['text'], (where, f and f['text'][:300])
    assert f['three'] and '/leestatic/three.js?v=' in (f['src'] or ''), (where, f and f['src'])
    assert f['gl'] == 'ready' and f['vis'] and f['canvas'] and f['w'] > 0, (where, {k: v for k, v in f.items() if k != 'px'})

def test_a_scene_demo_loads_three_js_and_draws_a_canvas(monkeypatch):
    import rupaka
    spec = json.loads((Path(rupaka.__file__).parent/'blocks/scene/example.json').read_text())
    def run(root):
        nb = root/'scene.ipynb'
        nb.write_text(json.dumps({'cells': [{'cell_type': 'markdown', 'id': 'c0', 'metadata': {}, 'source': ['```rupaka\n' + json.dumps(spec) + '\n```\n']}],
                                  'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
        async def go(pg):
            await pg.evaluate(f'leeOpenFile({str(nb)!r})')
            return await _drawn(pg, CELL.format(0), 'scene.png')
        return asyncio.run(_on(root, go, monkeypatch))
    _ok(_in_tmp(run), 'example')

def test_the_panchanga_lesson_scenes_draw_and_follow_their_knob_in_the_lesson_and_in_present_mode(monkeypatch):
    "The owner's lesson, copied: both scenes in the notebook, on the presenter's slide and in the audience window."
    if not LESSON.is_file(): pytest.skip('the vedicreader checkout is not beside this one')
    def run(root):
        nb = root/LESSON.name
        shutil.copyfile(LESSON, nb)
        async def go(pg):
            out = {}
            await pg.evaluate(f'leeOpenFile({str(nb)!r})')
            await pg.wait_for_function('() => document.querySelectorAll(".lee-cell").length === 22')
            for i, (slug, k, ans) in SCENES.items():
                await _lock(pg, CELL.format(i), ans)
                out[f'lesson-{slug}'] = await _drawn(pg, CELL.format(i), f'lesson-{slug}.png')
                out[f'lesson-{slug}-knob'] = await _knob(pg, CELL.format(i), k, f'lesson-{slug}-knob.png')
            await pg.evaluate('() => { selectCell(16); focusCell(16); }')
            await pg.keyboard.press('Alt+KeyR')
            await pg.wait_for_function('() => document.querySelector(".lee-present[data-ready]")', timeout=30000)
            hosts = '.lee-present .lee-slide .lee-rupaka'
            await pg.wait_for_function(f'() => document.querySelectorAll("{hosts}").length >= 2', timeout=30000)
            idx = await pg.evaluate(f'''() => [...document.querySelectorAll("{hosts}")].map(h => h.shadowRoot.querySelector('[data-rk-id], .rk')?.closest('[data-rk-id]')?.dataset.rkId || h.shadowRoot.textContent.slice(0, 40))''')
            out['present-ids'] = idx
            n = await pg.evaluate(f'() => document.querySelectorAll("{hosts}").length')
            scenes = [j for j in range(n) if await pg.evaluate(f'(j) => !!document.querySelectorAll("{hosts}")[j].shadowRoot.querySelector("[data-rk-gl]")', j)]
            for j, (_, _, ans) in zip(scenes, SCENES.values()):
                await pg.evaluate(f'(j) => document.querySelectorAll("{hosts}")[j].id = "rk-pres-" + j', j)
                await _lock(pg, f'#rk-pres-{j}', ans)
                out[f'present-{j}'] = await _drawn(pg, f'#rk-pres-{j}', f'present-{j}.png')
            out['present-knob'] = await _knob(pg, f'#rk-pres-{scenes[0]}', 'Tilt', 'present-knob.png')
            async with pg.context.expect_page() as pop: await pg.click('.lee-present-strip [data-audience]')
            aud = await pop.value
            await aud.set_viewport_size({'width': 1280, 'height': 720})
            await aud.wait_for_function(f'() => document.querySelectorAll("{STAGE}").length >= 1', timeout=30000)
            m = await aud.evaluate(f'() => document.querySelectorAll("{STAGE}").length')
            for j in range(m):
                if not await aud.evaluate(f'(j) => !!document.querySelectorAll("{STAGE}")[j].shadowRoot.querySelector("[data-rk-gl]")', j): continue
                await aud.evaluate(f'(j) => document.querySelectorAll("{STAGE}")[j].id = "rk-aud-" + j', j)
                out[f'audience-{j}'] = await _drawn(aud, f'#rk-aud-{j}', f'audience-{j}.png')
            await aud.screenshot(path=str(SHOTS/'audience.png')); await pg.screenshot(path=str(SHOTS/'presenter.png'))
            return out
        return asyncio.run(_on(root, go, monkeypatch))
    out = _in_tmp(run)
    for k, f in out.items():
        if isinstance(f, dict): _ok(f, k)
    assert all(out[f'lesson-{s}-knob'] for s, _, _ in SCENES.values()), 'a lesson scene does not follow its knob'
    assert out['present-knob'], 'the presenter scene does not follow its knob'
    assert sum(k.startswith('present-') and isinstance(v, dict) for k, v in out.items()) >= 2, out['present-ids']
    assert sum(k.startswith('audience-') for k in out) >= 2, [k for k in out]
    assert 'tilted 40°' in next(v['text'] for k, v in out.items() if k.startswith('audience-')), 'the audience scene does not follow the presenter knob'
