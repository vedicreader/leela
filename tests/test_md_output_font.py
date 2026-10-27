"A markdown output reads like a markdown cell: prose in the body font, code in the mono font."
import json, re
import pytest

def _notebook(tmp_path):
    p = tmp_path/'out.ipynb'
    md = 'Some **prose** with `code` in it.'
    p.write_text(json.dumps({'cells': [
        {'cell_type': 'markdown', 'id': 'c0', 'metadata': {}, 'source': [md]},
        {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': 1, 'source': ['from IPython.display import Markdown\nMarkdown("x")'],
         'outputs': [{'output_type': 'execute_result', 'execution_count': 1, 'metadata': {}, 'data': {'text/markdown': md, 'text/plain': '<Markdown>'}}]}],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return p

@pytest.mark.slow
def test_a_markdown_output_uses_the_markdown_cells_fonts(tmp_path):
    "`.lee-out` sets the mono font for text outputs, and a markdown output kept it, so its prose read as code."
    pytest.importorskip('playwright.async_api')
    from test_web_slow import _run
    p = _notebook(tmp_path)
    cell, out = '.lee-cell[data-i="0"] .lee-md-cell', '.lee-cell[data-i="1"] .lee-md-output'
    async def go(pg):
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function(f'() => document.querySelector({out!r} + " p") && document.querySelector({cell!r} + " p")')
        return await pg.evaluate(f"""() => {{ const f = s => getComputedStyle(document.querySelector(s)).fontFamily;
          const z = s => getComputedStyle(document.querySelector(s)).fontSize;
          return {{cell: f({cell!r} + ' p'), out: f({out!r} + ' p'), cellSize: z({cell!r} + ' p'), outSize: z({out!r} + ' p'),
                   cellCode: f({cell!r} + ' code'), outCode: f({out!r} + ' code')}}; }}""")
    got = _run(go, roots=[tmp_path])
    assert got['out'] == got['cell'] and got['outSize'] == got['cellSize'], got
    assert got['outCode'] == got['cellCode'] != got['cell'], got


def _rules(css):
    "Every `(selectors, body)` pair of the top-level rules in `css`, comments removed."
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return [(s.strip(), b) for s, b in re.findall(r'([^{}@][^{}]*)\{([^{}]*)\}', css)]

def _decls(css, sel):
    "The declarations of every rule whose selector list names exactly `sel`."
    return ' '.join(b for s, b in _rules(css) if sel in [x.strip() for x in s.split(',')])

def test_font_values_are_named_variables_defined_once_in_root():
    "The owner changes a font later in one place: the :root block beside `--lee-mono` and `--lee-code-size`."
    from assets import read
    css = read('leela/static/lee-ide.css')
    root = _decls(css, ':root')
    for v in ('--lee-mono', '--lee-code-size', '--lee-sans', '--lee-sans-cursor', '--lee-size-min', '--lee-md-output-weight'):
        assert len(re.findall(rf'(?<![\w-]){v}\s*:', root)) == 1, v
    assert re.search(r'--lee-size-min:\s*10px', root)

def test_links_in_markdown_surfaces_use_the_accent():
    from assets import read
    css = read('leela/static/lee-ide.css')
    sels = ['.lee-md a', '.lee-md-cell a', '.lee-md-output a', '.lee-reply a']
    hit = [b for s, b in _rules(css) if all(x in [y.strip() for y in s.split(',')] for x in sels)]
    assert hit and 'color: var(--lee-accent)' in hit[0], hit

def test_no_chrome_font_size_is_below_ten_pixels():
    "Text under 10px is unreadable in the chrome and agent pane; each such site names `--lee-size-min`."
    from assets import read
    css = read('leela/static/lee-ide.css')
    small = [(s, m) for s, b in _rules(css) for m in re.findall(r'font(?:-size)?:\s*(?:[\w.]+\s+)*?(\d*\.?\d+)px', b) if float(m) < 10]
    assert not small, small[:8]
    js = read('leela/blocks/agent/approvals.js')
    assert not re.search(r'font:\s*[0-9.]+px', js.split('REVISION_NOTE =')[1].split(chr(10))[0].replace('10px', '').replace('11px', '')), 'REVISION_NOTE'

def test_agent_prose_inherits_the_body_family_and_code_stays_mono():
    from assets import read
    css = read('leela/static/lee-ide.css')
    for sel in ('.lee-reply', '.lee-agent-welcome', '.lee-user-message-body'):
        assert 'var(--lee-sans)' in _decls(css, sel), sel
    assert 'var(--lee-mono)' in _decls(css, '.lee-reply code')
    assert 'var(--lee-mono)' in _decls(css, '.lee-agentlog')

def test_output_uses_the_code_size_and_markdown_output_weight_is_400():
    from assets import read
    css = read('leela/static/lee-ide.css')
    assert 'font-size: var(--lee-code-size)' in _decls(css, '.lee-out')
    assert 'font-weight: var(--lee-md-output-weight)' in _decls(css, '.lee-out.lee-md-output')
    assert re.search(r'--lee-md-output-weight:\s*400', _decls(css, ':root'))
    assert css.index('.lee-out.lee-md-output {') > css.index('.lee-out.result {')

def test_the_cursor_theme_and_state_pane_use_the_body_stack_variables():
    from assets import read
    css = read('leela/static/lee-ide.css')
    assert '--lee-sans: var(--lee-sans-cursor)' in _decls(css, ':root[data-theme="cursor"]')
    assert 'system-ui' not in css and 'var(--lee-sans)' in _decls(css, '.lee-state-ref-pane.lee-md')

def test_reveal_themes_fetch_no_web_fonts():
    "A theme that imports Google Fonts needs the network, so presenting offline fell back unpredictably."
    from assets import ROOT
    themes = ('sky', 'night', 'simple', 'league', 'moon', 'beige', 'blood', 'solarized')
    bad = [t for t in themes if 'fonts.googleapis.com' in (ROOT/f'leela/vendor/reveal/theme/{t}.css').read_text() or '@import' in (ROOT/f'leela/vendor/reveal/theme/{t}.css').read_text()]
    assert not bad, bad

def test_the_terminal_reads_the_code_size_variable():
    from assets import read
    term = read('frontend/term.js')
    assert "--lee-code-size" in term and 'fontSize: 13' not in term
    assert '--lee-code-size' in read('leela/vendor/lee-term.js'), 'run npm run build:term in frontend/'
