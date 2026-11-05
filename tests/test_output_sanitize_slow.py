"Rich HTML output runs no script in the IDE page, and a table, an image, an SVG and KaTeX still draw."

import json
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_web_slow import _run   # noqa: E402

PUSH = "(window.top.__pwn=window.top.__pwn||[]).push"
HTML = lambda h, mime='text/html': {'output_type': 'display_data', 'metadata': {}, 'data': {mime: h, 'text/plain': 'x'}}
PAYLOADS = {
    'img': HTML(f'<img src=x onerror="{PUSH}(\'img\')">'),
    'route': HTML(f"<img src=x onerror=\"fetch('/').then(r => {PUSH}('route' + r.status))\">"),
    'svg-html': HTML(f'<svg onload="{PUSH}(\'svg-html\')"><rect width=5 height=5></rect></svg>'),
    'svg-mime': HTML(f'<svg xmlns="http://www.w3.org/2000/svg" onload="{PUSH}(\'svg-mime\')"><rect width="5" height="5"/></svg>', 'image/svg+xml'),
    'details': HTML(f'<details open ontoggle="{PUSH}(\'details\')"><summary>s</summary>d</details>'),
    'iframe-src': HTML(f'<iframe src="javascript:{PUSH}(\'iframe-src\')"></iframe>'),
    'iframe-srcdoc': HTML(f'<iframe srcdoc="<img src=x onerror={PUSH}(&quot;iframe-srcdoc&quot;)>"></iframe>'),
    'object': HTML(f'<object data="javascript:{PUSH}(\'object\')"></object>'),
    'embed': HTML(f'<embed src="javascript:{PUSH}(\'embed\')">'),
    'link': HTML(f'<a class="go" href="javascript:{PUSH}(\'link\')">go</a>'),
    'svg-link': HTML(f'<svg><a class="go" href="javascript:{PUSH}(\'svg-link\')"><text y="10">go</text></a></svg>'),
    'svg-set': HTML(f'<svg><a class="go"><set attributeName="href" to="javascript:{PUSH}(\'svg-set\')"/><text y="10">go</text></a></svg>'),
    'form': HTML(f'<form action="javascript:{PUSH}(\'form\')"><button class="go">go</button></form>'),
    'formaction': HTML(f'<form><button class="go" formaction="javascript:{PUSH}(\'formaction\')">go</button></form>'),
    'focus': HTML(f'<input autofocus onfocus="{PUSH}(\'focus\')">'),
    'script-slash': HTML(f'<script/x>{PUSH}("script-slash")</script>'),
    'math-link': HTML(f'<math><mi class="go" href="javascript:{PUSH}(\'math-link\')">x</mi></math>'),
    'list': HTML([f'<img src=x ', f'onerror="{PUSH}(\'list\')">']),
    'list-script': HTML(['<scr', f'ipt>{PUSH}("list-script")</script>']),
}
#: Markup that would make the page ask Leela for a URL by itself; `/hit-` marks each request.
FETCHES = {
    'img-rel': '<img src="/hit-img-rel">', 'img-host': '<img src="{base}hit-img-host">', 'img-loop': '<img src="http://127.0.0.1:{port}/hit-img-loop">',
    'srcset': '<img srcset="/hit-srcset 1x">', 'style-attr': '<div style="background:url(/hit-style-attr);width:9px;height:9px"></div>',
    'style-esc': '<div style="background:u\\72l(/hit-style-esc);width:9px;height:9px"></div>',
    'import': '<style>@import "/hit-import";div{background:url(/hit-sheet)}</style><div style="width:9px;height:9px">x</div>',
    'image-set': '<div style="background-image:image-set(\'/hit-image-set\' 1x);width:9px;height:9px"></div>',
    'svg-image': '<svg><image href="/hit-svg-image" width="9" height="9"/></svg>', 'svg-use': '<svg><use href="/hit-svg-use#a"/></svg>',
    'svg-fill': '<svg><rect width="9" height="9" fill="url(/hit-svg-fill#a)"/></svg>', 'link': '<link rel="stylesheet" href="/hit-link">',
    'video': '<video src="/hit-video" poster="/hit-poster"></video>',
}
#: Every output in a cell, then each `.go` clicked in its shadow root; what landed in `window.__pwn`.
FIRE = r"""async (outputs) => {
  window.__pwn = [];
  const c = lee.cells[0]; c.outputs = outputs; renderOutputs(c);
  await new Promise(r => setTimeout(r, 400));
  for (const h of document.getElementById('out-' + c.id).querySelectorAll('.lee-out'))
    for (const a of (h.querySelector('.lee-out-rich')?.shadowRoot || h).querySelectorAll('.go')) a.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
  await new Promise(r => setTimeout(r, 600));
  return window.__pwn;
}"""
DRAW = r"""async (outputs) => {
  const c = lee.cells[0]; c.outputs = outputs; renderOutputs(c);
  await new Promise(r => setTimeout(r, 300));
  return [...document.getElementById('out-' + c.id).querySelectorAll('.lee-out')].map(h => {
    const r = h.querySelector('.lee-out-rich')?.shadowRoot || h, q = s => r.querySelector(s);
    return {td: r.querySelectorAll('td').length, style: !!q('style'), trStyle: q('tr[style]')?.getAttribute('style'),
            img: q('img')?.getAttribute('src')?.slice(0, 22), svg: !!q('svg rect'), path: !!q('svg path'), math: !!q('math annotation'),
            katex: !!q('.katex .katex-html'), link: q('a')?.getAttribute('href'), cls: q('table')?.className};
  });
}"""
PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
KATEX = ('<span class="katex"><span class="katex-mathml"><math xmlns="http://www.w3.org/1998/Math/MathML"><semantics><mrow><mi>x</mi></mrow>'
         '<annotation encoding="application/x-tex">x</annotation></semantics></math></span><span class="katex-html" aria-hidden="true">'
         '<span class="base"><span class="mord mathnormal" style="margin-right:0.04em">x</span></span>'
         '<svg width="10" height="10" viewBox="0 0 10 10"><path d="M0 0L10 10"/></svg></span></span>')

def _nb(p):
    p.write_text(json.dumps({'cells': [{'cell_type': 'code', 'id': 'c1', 'source': ['x'], 'metadata': {}, 'outputs': [], 'execution_count': None}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))

async def _open(pg, p):
    await pg.evaluate(f'leeOpenFile({str(p)!r})')
    await pg.wait_for_function("() => lee.cells && lee.cells.length && document.querySelector('.lee-cell')")

def test_rich_html_output_runs_no_script_in_the_ide_page(tmp_path):
    """An `onerror`, `onload`, `javascript:` URL or frame in rich HTML output ran in the IDE origin, so it could call any route."""
    p = tmp_path/'x.ipynb'; _nb(p)
    async def go(pg):
        await _open(pg, p)
        return {k: await pg.evaluate(FIRE, [o]) for k, o in PAYLOADS.items()}
    ran = {k: v for k, v in _run(go, roots=[tmp_path]).items() if v}
    assert not ran, f'script ran in the IDE page: {ran}'

def test_rich_html_output_sends_no_request_to_leela(tmp_path):
    """An image, a stylesheet or an SVG reference in an output is a GET to a Leela route, sent with the person's cookies."""
    p = tmp_path/'x.ipynb'; _nb(p)
    async def go(pg):
        await _open(pg, p)
        base = await pg.evaluate('location.href'); port = await pg.evaluate('location.port')
        await pg.evaluate(FIRE, [HTML(h.replace('{base}', base).replace('{port}', port)) for h in FETCHES.values()])
        return await pg.evaluate("performance.getEntriesByType('resource').map(e => e.name).filter(n => n.includes('/hit-'))")
    assert _run(go, roots=[tmp_path]) == []

CONTAIN = r"""async (outputs) => {
  const c = lee.cells[0]; c.outputs = outputs; renderOutputs(c);
  await new Promise(r => setTimeout(r, 300));
  const host = document.getElementById('out-' + c.id).querySelector('.lee-out'), r = host.querySelector('.lee-out-rich').shadowRoot;
  const box = host.getBoundingClientRect(), hit = document.elementFromPoint(5, 5);
  return {cls: [...r.querySelectorAll('[class]')].map(e => e.className), a: r.querySelector('a').target, pop: r.querySelector('[popover]'),
          af: r.querySelector('[autofocus]'), covers: hit === host || host.contains(hit), w: box.width < innerWidth, list: r.textContent};
}"""

def test_an_output_cannot_cover_the_ide_or_borrow_its_class_names(tmp_path):
    p = tmp_path/'x.ipynb'; _nb(p)
    out = HTML(['<style>:host{position:fixed!important;inset:0!important;z-index:99999!important}div{position:fixed;inset:0}</style>',
                '<div class="lee-modal cm-editor ok" popover autofocus>cover</div><a href="https://example.com/">x</a>'])
    async def go(pg):
        await _open(pg, p)
        return await pg.evaluate(CONTAIN, [out])
    got = _run(go, roots=[tmp_path])
    assert got['cls'] == ['ok'] and got['a'] == '_blank' and got['pop'] is None and got['af'] is None, got
    assert not got['covers'], got
    assert ',' not in got['list'], 'a list-form value is joined, not drawn with commas'

def test_a_pandas_table_an_image_an_svg_and_katex_still_draw(tmp_path):
    pd = pytest.importorskip('pandas')
    p = tmp_path/'x.ipynb'; _nb(p)
    outs = [HTML(pd.DataFrame({'a': [1, 2], 'b': ['x', 'y']})._repr_html_()),
            HTML(f'<p><img src="data:image/png;base64,{PNG}"> <a href="https://example.com/">site</a></p>'),
            HTML('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><style>rect{fill:red}</style><rect width="5" height="5"/></svg>', 'image/svg+xml'),
            HTML(KATEX)]
    async def go(pg):
        await _open(pg, p)
        return await pg.evaluate(DRAW, outs)
    t, i, s, k = _run(go, roots=[tmp_path])
    assert t['td'] == 4 and t['style'] and t['trStyle'] == 'text-align: right;' and t['cls'] == 'dataframe', t
    assert i['img'] == 'data:image/png;base64,' and i['link'] == 'https://example.com/', i
    assert s['svg'] and s['style'], s
    assert k['math'] and k['katex'] and k['path'], k

SINKS = r"""async () => {
  window.__pwn = [];
  const out = document.body.appendChild(document.createElement('div'));
  drawTurnMedia(out, [{mime: 'image/png', url: 'x" onerror="window.__pwn.push(\'media\')'}, {mime: 'image/png', url: 'data:image/png;base64,AAAA'}]);
  const git = gitDiffNotebookHtml('', {path: '<img src=x onerror="window.__pwn.push(\'git\')">'});
  await new Promise(r => setTimeout(r, 300));
  return {pwn: window.__pwn, media: [...document.querySelectorAll('.lee-agent-media img')].map(i => i.getAttribute('src')), git};
}"""

def test_agent_media_and_a_git_path_are_not_markup(tmp_path):
    """A tool's mime type picked the data URL, and a file name went into the diff view, both as markup."""
    got = _run(lambda pg: pg.evaluate(SINKS))
    assert got['pwn'] == [] and got['media'] == ['data:image/png;base64,AAAA'], got
    assert '&lt;img' in got['git'] and '<img' not in got['git'], got
