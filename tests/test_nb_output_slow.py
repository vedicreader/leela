"A notebook cell draws the rich output a kernel sends."

import asyncio, json
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_web_slow import _run   # noqa: E402
from test_completion_caret_slow import _real_page   # noqa: E402

# What fastprogress sends: a FastHTML object offers `text/html` and a fenced copy as `text/markdown`.
BAR = lambda v: {'output_type': 'display_data', 'metadata': {}, 'data': {
    'text/plain': f'<div><progress max="3" value="{v}"></progress></div>',
    'text/html': f'<div><progress max="3" value="{v}"></progress></div>',
    'text/markdown': f'```html\n<div><progress max="3" value="{v}"></progress></div>\n\n```'}}

PAINT = r"""(outputs) => {
  const c = lee.cells[0]; c.outputs = outputs; renderOutputs(c);
  const box = document.getElementById('out-' + c.id);
  const hosts = [...box.querySelectorAll('.lee-out')];
  const bars = hosts.map(h => h.shadowRoot && h.shadowRoot.querySelector('progress'));
  return {n: hosts.length, rendered: bars.every(Boolean), value: bars.map(b => b && b.value),
          code: box.querySelectorAll('.cm-content, pre, .lee-code-surface').length, text: box.textContent};
}"""


def test_a_display_offering_html_and_markdown_draws_the_html(tmp_path):
    """A progress bar arrived as `text/markdown` first, so the cell showed its source in an `html` code view."""
    p = tmp_path/'bars.ipynb'
    p.write_text(json.dumps({'cells': [{'cell_type': 'code', 'source': ['x'], 'metadata': {}, 'outputs': [], 'execution_count': None}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function("() => lee.cells && lee.cells.length && document.querySelector('.lee-cell')")
        await pg.evaluate(PAINT, [BAR(0)])
        return await pg.evaluate(PAINT, [BAR(3)])
    out = _run(go, roots=[tmp_path])
    assert out['n'] == 1 and out['rendered'], out
    assert out['value'] == [3], out
    assert out['code'] == 0 and 'edit as markdown' not in out['text'], out


def test_a_plotly_figure_draws_in_a_sandboxed_frame(tmp_path):
    """A plotly figure sends only its own mimetype, which drew nothing."""
    p = tmp_path/'fig.ipynb'
    p.write_text(json.dumps({'cells': [{'cell_type': 'code', 'source': ['x'], 'metadata': {}, 'outputs': [], 'execution_count': None}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    fig = {'data': [{'type': 'scatter', 'mode': 'markers', 'x': [1, 2], 'y': [3, 4]}], 'layout': {'height': 300}}
    html = {'output_type': 'display_data', 'metadata': {}, 'data': {'text/html': '<div id="a"></div><script>1</script>'}}
    PAINT_FRAMES = r"""(outputs) => {
      const c = lee.cells[0]; c.outputs = outputs; renderOutputs(c);
      return [...document.getElementById('out-' + c.id).querySelectorAll('iframe')].map(f => ({sandbox: f.getAttribute('sandbox'), srcdoc: f.srcdoc, height: f.style.height}));
    }"""
    async def go(pg):
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function("() => lee.cells && lee.cells.length && document.querySelector('.lee-cell')")
        a = await pg.evaluate(PAINT_FRAMES, [{'output_type': 'display_data', 'metadata': {}, 'data': {'application/vnd.plotly.v1+json': fig}}])
        return a, await pg.evaluate(PAINT_FRAMES, [html])
    a, b = _run(go, roots=[tmp_path])
    assert len(a) == 1 and a[0]['sandbox'] == 'allow-scripts' and a[0]['height'] == '300px', a
    assert 'Plotly.newPlot' in a[0]['srcdoc'] and '"x":[1,2]' in a[0]['srcdoc'], a
    assert len(b) == 1 and b[0]['sandbox'] == 'allow-scripts' and '<script>1</script>' in b[0]['srcdoc'], b


CHARTS = ['%matplotlib inline\nimport matplotlib.pyplot as plt\nplt.figure(figsize=(8, 4), dpi=150); plt.plot([1, 3, 2]); plt.show()',
          "%config InlineBackend.figure_format = 'retina'\nplt.figure(figsize=(8, 4), dpi=100); plt.plot([1, 3, 2]); plt.show()",
          "%config InlineBackend.figure_format = 'png'\nfor i in range(500): print(i)\nplt.figure(figsize=(8, 4), dpi=150); plt.plot([1, 3, 2]); plt.show()",
          'x']
# plotly is not installed in the test kernel, so the notebook carries its mimebundle as a saved output.
PLOTLY = {'output_type': 'display_data', 'metadata': {}, 'data': {'application/vnd.plotly.v1+json': {
    'data': [{'type': 'scatter', 'x': [1, 2, 3], 'y': [1, 3, 2]}], 'layout': {'width': 1400, 'height': 600}}}}
MEASURE = r"""() => lee.cells.map(c => [...document.getElementById('out-' + c.id).querySelectorAll('.lee-out')].map(o => {
  const i = o.querySelector('img'), f = o.querySelector('iframe'), r = i && i.getBoundingClientRect();
  return {kind: i ? 'img' : f ? 'frame' : 'text', meta: (c.outputs.find(x => x.data && x.data['image/png']) || {}).metadata,
          sh: o.scrollHeight, ch: o.clientHeight, sw: o.scrollWidth, cw: o.clientWidth,
          img: i && {w: r.width, h: r.height, nw: i.naturalWidth, nh: i.naturalHeight}, frame: f && f.getBoundingClientRect().height};
}))"""
SCROLLS = r"""() => { const e = document.documentElement;
  return {svg: !!document.querySelector('.main-svg'), sh: e.scrollHeight, ch: e.clientHeight, sw: e.scrollWidth, cw: e.clientWidth}; }"""


@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_a_chart_shows_whole_at_its_own_size_and_text_keeps_its_scroll(tmp_path, browser):
    """Every output scrolled past 420px, so a chart taller than that was clipped, and a retina figure drew at twice its size."""
    p = tmp_path/'charts.ipynb'
    cells = [{'cell_type': 'code', 'id': f'c{n}', 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': s} for n, s in enumerate(CHARTS)]
    cells[3]['outputs'] = [PLOTLY]
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    p.write_text(json.dumps({'cells': cells, 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate('p => leeOpenFile(p)', str(p))
        await pg.wait_for_function('() => lee.cells?.length === 4 && document.querySelectorAll(".lee-cell").length === 4')
        await pg.add_style_tag(content='[id^="out-c"] { width: 900px; }')
        for i in range(3): await pg.evaluate('i => runCell(i)', i)
        for _ in range(240):
            await pg.wait_for_timeout(500)
            f = await (await pg.wait_for_selector('.lee-out iframe')).content_frame()
            doc = f and await f.evaluate(SCROLLS)
            # the saved plotly output draws without the kernel, so wait for each run cell's image too
            ran = (await pg.evaluate(MEASURE))[:3]
            if doc and doc['svg'] and all(any(o['kind'] == 'img' and o['img']['nw'] for o in c) for c in ran): break
        await pg.wait_for_timeout(500)
        return await pg.evaluate(MEASURE), await f.evaluate(SCROLLS)
    (mpl, retina, both, fig), doc = asyncio.run(_real_page(go, tmp_path, browser))
    whole = lambda o: o['sh'] <= o['ch'] + 1 and o['sw'] <= o['cw'] + 1
    bad = {}
    for name, o in [('figure', mpl[0]), ('retina', retina[0]), ('image beside text', both[-1])]:
        im = o['img']
        if not (whole(o) and im['w'] <= o['cw'] and abs(im['w'] / im['h'] - im['nw'] / im['nh']) < .02): bad[name] = o
    if abs(retina[0]['img']['w'] - retina[0]['meta']['image/png']['width']) > 1: bad['retina width'] = retina[0]
    if both[0]['kind'] != 'text' or both[0]['sh'] <= both[0]['ch']: bad['stream'] = both[0]
    if abs(fig[0]['frame'] - 600) > 2 or not whole(fig[0]): bad['plotly'] = fig[0]
    if doc['sh'] > doc['ch'] + 1 or doc['sw'] > doc['cw'] + 1: bad['plotly document'] = doc
    assert not bad, f'{sorted(bad)} {bad}'
