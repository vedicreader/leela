"A cell whose run stream breaks mid-run ends in the state its kernel left it in."

import asyncio, json
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_completion_caret_slow import _real_page   # noqa: E402

# The page's next run stream errors 800ms in, the way a dropped connection does, and lets the server see it go.
CUT = r"""() => {
  const real = window.fetch;
  window.fetch = async (url, opts) => {
    const r = await real(url, opts);
    if (!String(url).includes('/nb/run/stream')) return r;
    const reader = r.body.getReader();
    return new Response(new ReadableStream({async start(ctl) {
      setTimeout(() => { reader.cancel().catch(() => {}); ctl.error(new TypeError('network error')); }, 800);
      for (;;) { const {value, done} = await reader.read().catch(() => ({done: true})); if (done) return; ctl.enqueue(value); }
    }}), {status: r.status, headers: r.headers});
  };
}"""
STATE = "() => document.querySelector('#state-c1').className"

def test_a_run_stream_cut_mid_run_settles_the_cell_once_the_kernel_finishes(tmp_path):
    """A dropped run stream threw `network error` and marked a cell failed that was still running, and went on to finish."""
    p = tmp_path/'cut.ipynb'
    cell = {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': None, 'outputs': [],
            'source': 'import time; time.sleep(3); answer = 41 + 1'}
    p.write_text(json.dumps({'cells': [cell], 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function("() => lee.cells && lee.cells.length && document.querySelector('#state-c1')")
        await pg.evaluate(CUT)
        await pg.evaluate('() => { window.__ran = runCell(0); }')
        await pg.wait_for_timeout(2000)
        during = await pg.evaluate(STATE)
        res = await pg.evaluate('() => window.__ran')
        return during, res, await pg.evaluate(STATE), await pg.evaluate("() => document.querySelector('#g-c1').textContent")
    during, res, after, gutter = asyncio.run(_real_page(go, tmp_path))
    assert 'running' in during, during
    assert res['ok'] and 'done' in after and gutter.strip('[] '), (res, after, gutter)
