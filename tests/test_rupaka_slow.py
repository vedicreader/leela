"A rupaka demo in a notebook: drawn from a fence and from the mime, in the page's theme, with the keyboard its own."
import json
from pathlib import Path
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_web_slow import _run   # noqa: E402

DEMO = Path('/Users/71293/code/personal/orgs/rupaka/rupaka/demos/softmax-temperature.json')
SHOTS = Path(__file__).parents[1]/'target'/'rupaka'
MIME = 'application/vnd.rupaka+json'
MD = '.lee-cell[data-i="0"] .lee-md-cell .lee-rupaka'
OUT = '#out-c1 .lee-rupaka'
OPT = ' button[role=radio]'
STATE = r"""() => ({ex: lee.cells[1].execution_count, outputs: lee.cells[1].outputs.length,
  editing: document.querySelectorAll('.lee-cell[data-md-edit]').length,
  inside: !!document.activeElement?.closest('.lee-rupaka'), focused: window.__rkFocus})"""
FACTS = r"""(sel) => { const h = document.querySelector(sel), r = h.shadowRoot, i = r.firstElementChild, rk = i.querySelector('.rk');
  return {ready: i.dataset.rkReady, styled: !!r.adoptedStyleSheets.length || !!r.querySelector('style'), hostH: h.getBoundingClientRect().height,
    innerH: rk.getBoundingClientRect().height, fixed: h.style.height, bg: getComputedStyle(rk).getPropertyValue('--rk-bg').trim(),
    checked: [...r.querySelectorAll('button[role=radio]')].map(b => b.getAttribute('aria-checked')), verdict: [...r.querySelectorAll('.verdict')].some(v => !v.hidden)}; }"""
KEEP = r"""(sel) => { window.__rkHost = document.querySelector(sel); window.__rkInner = window.__rkHost.shadowRoot.firstElementChild; }"""
KEPT = r"""(sel) => { const h = document.querySelector(sel); return {host: h === window.__rkHost, inner: h?.shadowRoot.firstElementChild === window.__rkInner}; }"""
REPAINT = r"""async () => { const el = document.querySelector('.lee-cell[data-i="0"]'), m = el.querySelector('.lee-md-cell');
  const done = new Promise(res => m.addEventListener('lee-markdown-rendered', res, {once: true}));
  paintMarkdownCell(el, lee.cells[0], true); await done; }"""


def test_a_rupaka_demo_draws_from_a_fence_and_from_the_mime_and_leaves_the_notebook_alone(tmp_path):
    if not DEMO.is_file(): pytest.skip('the rupaka checkout is not beside this one')
    spec = json.loads(DEMO.read_text())
    cells = [{'cell_type': 'markdown', 'id': 'c0', 'metadata': {}, 'source': ['A fence:\n\n```rupaka\n' + json.dumps(spec) + '\n```\n']},
             {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': 7, 'source': ['1'],
              'outputs': [{'output_type': 'display_data', 'metadata': {},
                           'data': {MIME: spec, 'text/html': '<p>fallback</p><script>window.__fallbackRan = 1</script>', 'text/plain': 'demo'}}]}]
    p = tmp_path/'demo.ipynb'
    p.write_text(json.dumps({'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    SHOTS.mkdir(parents=True, exist_ok=True)

    async def go(pg):
        out = {}
        await pg.add_init_script("""window.__rkFocus = []; const f = HTMLElement.prototype.focus;
          HTMLElement.prototype.focus = function (...a) { if (this.getRootNode().host?.classList?.contains('lee-rupaka')) window.__rkFocus.push(this.tagName); return f.apply(this, a); };""")
        await pg.goto(pg.url, wait_until='networkidle')
        await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.evaluate("() => { document.documentElement.dataset.theme = 'leela'; document.documentElement.dataset.mode = 'light'; }")
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        for sel in (MD, OUT): await pg.wait_for_function(f'(s) => document.querySelector(s)?.shadowRoot?.firstElementChild?.dataset.rkReady === "1"', arg=sel)
        out['md'], out['mime'] = await pg.evaluate(FACTS, MD), await pg.evaluate(FACTS, OUT)
        out['iframes'] = await pg.evaluate('() => document.querySelectorAll("#out-c1 iframe").length')
        out['fallback_ran'] = await pg.evaluate('() => !!window.__fallbackRan')
        out['start'] = await pg.evaluate(STATE)
        await pg.evaluate(KEEP, MD)
        await pg.screenshot(path=str(SHOTS/'light.png'))
        await pg.evaluate("() => { document.documentElement.dataset.mode = 'dark'; }")
        await pg.wait_for_function(f'([s, was]) => getComputedStyle(document.querySelector(s).shadowRoot.querySelector(".rk")).getPropertyValue("--rk-bg").trim() !== was', arg=[MD, out['md']['bg']])
        out['dark'] = await pg.evaluate(FACTS, MD); out['dark_kept'] = await pg.evaluate(KEPT, MD)
        await pg.screenshot(path=str(SHOTS/'dark.png'))
        first = pg.locator(MD + OPT).first
        await first.focus(); await pg.keyboard.press('Enter')
        out['enter'] = await pg.evaluate(FACTS, MD); out['enter_state'] = await pg.evaluate(STATE)
        await pg.evaluate(REPAINT)
        out['repaint'] = await pg.evaluate(FACTS, MD); out['repaint_kept'] = await pg.evaluate(KEPT, MD)
        await pg.evaluate(KEEP, OUT)
        await pg.locator(OUT + OPT).first.focus(); await pg.keyboard.press('Enter'); await pg.keyboard.press('Meta+Enter')
        out['gate'] = await pg.evaluate(FACTS, OUT); out['gate_state'] = await pg.evaluate(STATE)
        await pg.evaluate('() => renderOutputs(lee.cells[1])')
        out['out_kept'] = await pg.evaluate(KEPT, OUT); out['out_again'] = await pg.evaluate(FACTS, OUT)
        return out
    got = _run(go, roots=[tmp_path])
    for k in ('md', 'mime'):
        f = got[k]
        assert f['ready'] == '1' and f['styled'] and not f['fixed'], got[k]
        assert abs(f['hostH'] - f['innerH']) < 2 and f['hostH'] > 50, f'{k} is not its natural height: {f}'
    assert got['iframes'] == 0 and not got['fallback_ran'], 'the text/html fallback ran'
    assert got['start']['focused'] == [] and not got['start']['inside'], got['start']
    assert got['dark']['bg'] != got['md']['bg'] and got['dark_kept'] == {'host': True, 'inner': True}, (got['md']['bg'], got['dark'])
    assert got['enter']['checked'][0] == 'true', 'Enter on a demo control did not reach the demo'
    assert got['enter_state']['editing'] == 0 and got['enter_state']['ex'] == 7, got['enter_state']
    assert got['repaint_kept'] == {'host': True, 'inner': True} and got['repaint']['checked'][0] == 'true', got['repaint']
    assert got['gate']['verdict'] and got['gate_state']['ex'] == 7 and got['gate_state']['outputs'] == 1, got['gate_state']
    assert got['out_kept'] == {'host': True, 'inner': True} and got['out_again']['verdict'], got['out_again']