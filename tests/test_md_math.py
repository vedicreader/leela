"Math in Markdown: the four delimiter forms reach the page as carriers KaTeX can fill, and TeX cannot make a link."
import re
from pathlib import Path
import fast5ever
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace

def render(text):
    with TestClient(ide_app(Workspace(roots=[]))) as c:
        r = c.post('/markdown/render', json={'text': text})
    assert r.status_code == 200, r.text
    return r.json()['html']

def carriers(html):
    "`(tag, classes, text)` of every element carrying the `math` class."
    out = []
    def walk(ns):
        for n in ns:
            if not isinstance(n, fast5ever.Element): continue
            cls = str(dict(n.attrs).get('class') or '').split()
            if 'math' in cls: out.append((n.name, sorted(cls), n.to_text()))
            walk(n.children)
    walk(fast5ever.parse_fragment(html).children)
    return out

@pytest.mark.parametrize('src, want', [
    (r'so $a^2+b^2$ here', ('span', ['inline', 'math'], 'a^2+b^2')),
    (r'so \(a^2+b^2\) here', ('span', ['inline', 'math'], 'a^2+b^2')),
    ('$$\n\\int_0^1 x\\,dx\n$$', ('div', ['display', 'math'], '\\int_0^1 x\\,dx')),
    ('\\[\n\\int_0^1 x\\,dx\n\\]', ('div', ['display', 'math'], '\\int_0^1 x\\,dx')),
], ids=['dollar', 'paren', 'double-dollar', 'bracket'])
def test_each_delimiter_form_becomes_a_math_carrier_holding_the_tex(src, want):
    (tag, cls, text), = carriers(render(src))
    assert (tag, cls) == want[:2] and text.strip() == want[2]

def test_a_link_command_inside_math_is_only_text_to_the_server_and_no_link():
    html = render(r'$\href{javascript:alert(1)}{x}$')
    assert not [e for e in re.findall(r'href="([^"]*)"', html) if e.lower().startswith('javascript')], html

VENDOR = Path(__file__).parents[1]/'leela'/'vendor'
SHOTS = Path(__file__).parents[1]/'target'/'math'

def test_the_vendored_katex_is_the_version_and_the_files_the_readme_records():
    import hashlib
    readme = (VENDOR/'README').read_text()
    (named,) = re.findall(r'katex@(\d+\.\d+\.\d+)', readme)[:1] or [None]
    inside = re.search(r'version:"(\d+\.\d+\.\d+)"', (VENDOR/'katex'/'katex.min.js').read_text()).group(1)
    assert named == inside and inside.startswith('0.16.'), (named, inside)
    for f in ('katex.min.js', 'katex.min.css'):
        want = re.search(rf'katex/{re.escape(f)} SHA-256 ([0-9a-f]{{64}})', readme).group(1)
        assert hashlib.sha256((VENDOR/'katex'/f).read_bytes()).hexdigest() == want, f
    assert not (set((VENDOR/'katex'/'fonts').iterdir()) - set((VENDOR/'katex'/'fonts').glob('*.woff2')))

CELL = '.lee-cell[data-i="0"] .lee-md-cell'

def _notebook(tmp_path, source):
    import json
    p = tmp_path/'math.ipynb'
    p.write_text(json.dumps({'cells': [{'cell_type': 'markdown', 'id': 'c0', 'metadata': {}, 'source': [source]}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return p

@pytest.mark.slow
def test_a_markdown_cell_draws_katex_in_light_and_dark_and_tex_cannot_make_a_link(tmp_path):
    pytest.importorskip('playwright.async_api')
    from test_web_slow import _run
    p = _notebook(tmp_path, 'Inline $a^2+b^2$ and display:\n\n$$\\int_0^1 x\\,dx$$\n\nand $\\href{javascript:alert(1)}{x}$ done.\n')
    SHOTS.mkdir(parents=True, exist_ok=True)
    async def go(pg):
        out = {}
        await pg.evaluate("() => { document.documentElement.dataset.theme = 'leela'; document.documentElement.dataset.mode = 'light'; }")
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function(f'() => document.querySelectorAll({CELL!r} + " .katex").length >= 3')
        facts = f"""() => {{ const c = document.querySelector({CELL!r});
          return {{katex: c.querySelectorAll('.katex').length, display: c.querySelectorAll('.katex-display').length,
            dollars: c.textContent.includes('$'), links: [...c.querySelectorAll('a')].map(a => a.getAttribute('href')),
            colour: getComputedStyle(c.querySelector('.katex')).color, bg: getComputedStyle(document.body).backgroundColor,
            font: getComputedStyle(c.querySelector('.katex .mord')).fontFamily}}; }}"""
        out['light'] = await pg.evaluate(facts)
        await pg.locator(CELL).scroll_into_view_if_needed()
        await pg.screenshot(path=str(SHOTS/'light.png'))
        await pg.evaluate("() => { document.documentElement.dataset.mode = 'dark'; }")
        await pg.wait_for_function(f'(bg) => getComputedStyle(document.body).backgroundColor !== bg', arg=out['light']['bg'])
        out['dark'] = await pg.evaluate(facts)
        await pg.screenshot(path=str(SHOTS/'dark.png'))
        return out
    got = _run(go, roots=[tmp_path])
    for mode in ('light', 'dark'):
        f = got[mode]
        assert f['katex'] >= 3 and f['display'] == 1 and not f['dollars'], (mode, f)
        assert not [h for h in f['links'] if (h or '').lower().startswith('javascript')], (mode, f)
        assert 'KaTeX' in f['font'], (mode, f)
    assert got['dark']['colour'] != got['light']['colour'] or got['dark']['bg'] != got['light']['bg'], got

@pytest.mark.slow
def test_a_katex_that_will_not_load_leaves_the_tex_and_warns_once(tmp_path):
    pytest.importorskip('playwright.async_api')
    from test_web_slow import _run
    p = _notebook(tmp_path, 'Inline math: $a^2+b^2$ and \\(c\\) here.\n')
    async def go(pg):
        warnings = []
        pg.on('console', lambda m: warnings.append(m.text) if m.type == 'warning' and 'Leela math' in m.text else None)
        await pg.route('**/katex.min.js*', lambda route: route.abort())
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function(f'() => document.querySelector({CELL!r} + " .math")')
        await pg.wait_for_timeout(500)
        await pg.evaluate(f'() => renderMarkdown(document.querySelector({CELL!r}), lee.cells[0].source.join ? lee.cells[0].source.join("") : lee.cells[0].source, false)')
        await pg.wait_for_timeout(500)
        return {'warnings': warnings, 'tex': await pg.evaluate(f'() => [...document.querySelectorAll({CELL!r} + " .math")].map(e => e.textContent)'),
                'katex': await pg.evaluate(f'() => document.querySelectorAll({CELL!r} + " .katex").length')}
    got = _run(go, roots=[tmp_path])
    assert got['tex'] == ['a^2+b^2', 'c'] and got['katex'] == 0 and len(got['warnings']) == 1, got

def test_no_cdn_for_katex():
    root = Path(__file__).parents[1]/'leela'
    hits = [str(p) for p in root.rglob('*') if p.suffix in ('.py', '.js', '.html') and 'vendor' not in p.parts
            and 'cdn.jsdelivr.net' in p.read_text(errors='ignore')]
    assert hits == []
    assert (root/'vendor'/'katex'/'katex.min.js').is_file()
