"Presenting a notebook as RISE-style slides: grouping, settings, the routes that left, and every way in."

import importlib.util, json, shutil, subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
PRESENT_JS = ROOT/'leela'/'blocks'/'nb'/'present.js'

def _js(expr):
    "Evaluate `expr` with the deck module loaded, in node: its grouping and settings need no page."
    if not shutil.which('node'): pytest.skip('node is not installed')
    src = PRESENT_JS.read_text() + f'\nprocess.stdout.write(JSON.stringify({expr}));\n'
    out = subprocess.run(['node', '-'], input=src, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)

def _cell(t, src='x', kind='markdown', **kw):
    return {'cell_type': kind, 'source': src, 'extra': {} if t is None else {'slideshow': {'slide_type': t}}, **kw}

def test_cells_group_into_slides_the_way_rise_groups_them():
    typed = [_cell('slide', 'a'), _cell('-', 'b'), _cell('fragment', 'c'), _cell('-', 'd'), _cell('subslide', 'e'),
             _cell('notes', 'n1'), _cell('skip', 's'), _cell('slide', 'f'), _cell('fragment', 'g'),
             _cell('slide', 'ok?', approval={'tool': 'x'}), _cell('slide', ''), _cell('-', 'h')]
    S = lambda items, notes=(): {'items': [{'i': i, 'frag': f} for i, f in items], 'notes': list(notes)}
    got = _js(f'(() => {{ const d = presentSlides({json.dumps(typed)}); return {{d: d.map(s => s.map(x => ({{items: x.items, notes: x.notes}}))),'
              f'at: [6, 3, 9, 0].map(i => presentAt(d, i))}}; }})()')
    assert got['d'] == [[S([(0, -1), (1, -1), (2, 0), (3, 0)]), S([(4, -1)], [5])],
                        [S([(7, -1), (8, 0)])],
                        [S([(11, -1)])]], 'an empty slide cell still starts a slide, and an approval cell is no slide'
    assert got['at'] == [{'h': 0, 'v': 1, 'f': -1}, {'h': 0, 'v': 0, 'f': 0}, {'h': 1, 'v': 0, 'f': 0},
                         {'h': 0, 'v': 0, 'f': -1}], 'a skipped or notes cell opens at the visible cell above it'
    cases = {
        'leading': [_cell('fragment', 'a'), _cell('notes', 'n'), _cell('slide', 'b')],
        'notes_first': [_cell('notes', 'n'), _cell('slide', 'a')],
        'sub_first': [_cell('subslide', 'a'), _cell('-', 'b')],
        'untyped': [_cell(None, 'a', 'code'), _cell(None, '  ', 'code'), _cell(None, 'b')],
        'nothing': [_cell('skip', 'a'), _cell('-', ''), _cell(None, 'c', approval={})],
        'live_text': [_cell(None, '')],
    }
    got = _js('Object.fromEntries(Object.entries(' + json.dumps(cases) + ').map(([k, v]) => [k, '
              'presentSlides(v, k === "live_text" ? c => "typed but unsaved" : undefined)'
              '.map(s => s.map(x => ({items: x.items.map(y => y.i), notes: x.notes})))]))')
    assert got['leading'] == [[{'items': [0], 'notes': [1]}], [{'items': [2], 'notes': []}]]
    assert got['notes_first'] == [[{'items': [], 'notes': [0]}], [{'items': [1], 'notes': []}]]
    assert got['sub_first'] == [[{'items': [0, 1], 'notes': []}]]
    assert got['untyped'] == [[{'items': [0], 'notes': []}], [{'items': [2], 'notes': []}]]
    assert got['nothing'] == []
    assert got['live_text'] == [[{'items': [0], 'notes': []}]], 'the text read is the editor text, not the saved source'

def test_a_skip_or_notes_mark_alone_leaves_every_other_cell_its_own_slide():
    "Skipping one cell in a notebook with no slide boundaries made every other cell continue one slide, which then scrolled."
    cells = [_cell(None, 'a'), _cell('skip', 's'), _cell(None, 'b'), _cell('notes', 'n'), _cell(None, 'c'),
             _cell('fragment', 'f'), _cell('-', 'd')]
    got = _js(f'presentSlides({json.dumps(cells)}).map(s => s.map(x => ({{items: x.items.map(y => y.i), notes: x.notes}})))')
    assert got == [[{'items': [0], 'notes': []}], [{'items': [2], 'notes': [3]}], [{'items': [4, 5, 6], 'notes': []}]], got

CASES = json.loads((ROOT/'tests'/'data'/'rise_cases.json').read_text())
_LINE = 'cs => presentLine(presentSlides(cs, c => c.live ?? String(c.source || ""))).map(s => ({...s, items: s.items.map(x => [x.i, x.frag])}))'

def _lines(cases):
    "Each case's flat line and its start places, from the page's own grouping."
    return _js(f'''Object.fromEntries(Object.entries({json.dumps(cases)}).map(([k, c]) => {{
      const l = presentLine(presentSlides(c.cells, x => x.live ?? String(x.source || "")));
      return [k, {{line: ({_LINE})(c.cells), place: (c.place || []).map(([i]) => {{ const p = presentPlace(l, i); return [i, p.slide, p.step]; }})}}];
    }}))''')

def test_the_slide_line_follows_the_case_table():
    got = _lines(CASES)
    for k, c in CASES.items():
        assert got[k]['line'] == c['line'], k
        assert got[k]['place'] == c.get('place', []), k

def test_the_case_table_holds_cells_the_way_the_editor_writes_them():
    "The editor's `none` removes `slide_type`; only a file holds `-`, and an approval cell takes no slide type from the editor."
    from leela.blocks.nb.nb import Cell, Notebook
    for k, c in CASES.items():
        nb = Notebook([Cell(cell_type=x['cell_type'], source=x['source'], outputs=list(x.get('outputs', [])), reply=x.get('reply', ''),
                            approval=x.get('approval')) for x in c['cells']])
        for i, x in enumerate(c['cells']):
            t = x['extra'].get('slideshow', {}).get('slide_type')
            if t == '-' or 'approval' in x: nb.cells[i].extra = json.loads(json.dumps(x['extra']))
            elif t: nb.set_slide([i], t)
            else: nb.set_slide([i], 'slide'); nb.set_slide([i], 'none')
        page = [{**cl.dict(), 'live': x.get('live')} for cl, x in zip(nb.cells, c['cells'])]
        assert [p['extra'] for p in page] == [x['extra'] for x in c['cells']], k
        assert _js(f'({_LINE})({json.dumps(page, default=str)})') == c['line'], k

def test_h2_cuts_slides_only_without_slide_metadata():
    plain = [_cell(None, '## A\ntext'), _cell(None, 'x', 'code'), _cell(None, '## B'), _cell(None, 'y')]
    typed = [_cell('slide', '## A'), _cell(None, '## B')]
    marks = [_cell(None, '## A'), _cell('fragment', 'f'), _cell('notes', '## n'), _cell('skip', '## s'), _cell(None, '## B')]
    got = _js(f'[{json.dumps(plain)}, {json.dumps(typed)}, {json.dumps(marks)}].map(c => presentLine(presentSlides(c)).map(s => s.items.map(x => x.i)))')
    assert got == [[[0, 1], [2, 3]], [[0, 1]], [[0, 1], [4]]]

def test_move_and_place_walk_fragments_in_one_line():
    cells = [_cell('slide', 'a'), _cell('fragment', 'b'), _cell('subslide', 'c'), _cell('notes', 'n'), _cell('slide', 'd')]
    got = _js(f'''(() => {{ const l = presentLine(presentSlides({json.dumps(cells)})), m = presentMove;
      let a = {{slide: 0, step: 0}}, walk = [a];
      for (const d of [1, 1, 1, 1, -1, -1, -1, -1]) walk.push(a = m(l, a, d));
      return {{n: l.length, walk, place: [1, 3, 4].map(i => presentPlace(l, i))}}; }})()''')
    assert got['n'] == 3
    assert [(w['slide'], w['step']) for w in got['walk']] == [(0, 0), (0, 1), (1, 0), (2, 0), (2, 0), (1, 0), (0, 1), (0, 0), (0, 0)]
    assert got['place'] == [{'slide': 0, 'step': 0}, {'slide': 1, 'step': 0}, {'slide': 2, 'step': 0}]
    walk = _js(f'''(() => {{ const l = presentLine(presentSlides({json.dumps(CASES["frags_subs"]["cells"])})); let a = {{slide: 0, step: 0}}, w = [];
      for (const d of [1, 1, 1, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1, -1]) w.push(a = presentMove(l, a, d)); return w.map(x => [x.slide, x.step]); }})()''')
    assert walk == [[0, 1], [0, 2], [1, 0], [1, 1], [2, 0], [2, 1], [2, 2], [2, 2], [2, 1], [2, 0], [1, 1], [1, 0], [0, 2], [0, 1]]
    assert _js('[presentPlace([], 3), presentMove([], {slide: 0, step: 0}, 1)]') == [{'slide': 0, 'step': 0}] * 2

def test_49_fragment_groups_fit_and_the_rest_show_with_the_49th():
    def go(n): return _js(f'''(() => {{ const l = presentLine(presentSlides({json.dumps([_cell('slide', 'a')] + [_cell('fragment', f'f{i}') for i in range(n)] + [_cell('slide', 'z')])}));
      return {{s: l[0], last: presentPlace(l, {n}), end: presentMove(l, {{slide: 0, step: 49}}, 1), back: presentMove(l, {{slide: 1, step: 0}}, -1)}}; }})()''')
    full, over, far = go(49), go(50), go(52)
    assert (full['s']['groups'], full['s']['warn']) == (49, False)
    assert [x['frag'] for x in full['s']['items']] == list(range(-1, 49))
    for g, n in ((over, 50), (far, 52)):
        assert (g['s']['groups'], g['s']['warn']) == (49, True), n
        assert [x['frag'] for x in g['s']['items']] == list(range(-1, 49)) + [48]*(n - 49), n
        assert g['last'] == {'slide': 0, 'step': 48} and g['back'] == {'slide': 0, 'step': 49}, n
        assert g['end'] == {'slide': 1, 'step': 0}, n

def test_rise_settings_keep_only_the_start():
    "Task 4 on purpose: reveal.js left, so `rise.theme` and every reveal option are dropped (decision 6); only where to start is read."
    got = _js('[riseConfig({theme: "black", transition: "linear", width: "100%", header: "<b>h</b>", start_slideshow_at: "beginning"}),'
              ' riseConfig("rise"), riseConfig([1]), riseConfig(null), riseConfig({start_slideshow_at: "x", theme: "night"})]')
    assert got == [{'start': 'beginning'}] + [{'start': 'selected'}] * 4

def test_the_text_size_moves_in_tenths_between_half_and_two_and_a_half():
    assert _js('[presentStep(1, 1), presentStep(1, -1), presentStep(1.2, 1), presentStep(.5, -1), presentStep(2.5, 1), presentStep(.7000001, 1)]') \
        == [1.1, .9, 1.3, .5, 2.5, .8]

STARTS = '''const log = []; let release;
globalThis.lee = {kind: 'notebook', cells: [{id: 'a', cell_type: 'markdown', source: '# A', extra: {}}], sel: 0, path: 'd.ipynb'};
globalThis.status = () => {}; globalThis.mdSource = c => c.source;
globalThis.post = url => { log.push(url); return url === '/present/end' ? new Promise(r => { release = () => r({ok: true}); }) : Promise.resolve({key: 'k' + log.length}); };
%s
presentOpen = r => { log.push('open ' + r.key); lee.present = {chain: Promise.resolve(), key: r.key}; };
closePresentation = () => { lee.present = null; };
const ticks = () => new Promise(r => setTimeout(r, 10));
(async () => {
  presentEnd({chain: Promise.resolve(), key: 'old'}); presentNotebook(); presentNotebook(); await ticks();
  const held = [...log]; release(); await ticks();
  process.stdout.write(JSON.stringify([held, log]));
})();'''

def test_a_page_sends_one_start_at_a_time_after_the_last_end():
    "The server keeps the start it reads last and refuses one an end overtakes, so two quick starts after End once opened nothing."
    if not shutil.which('node'): pytest.skip('node is not installed')
    out = subprocess.run(['node', '-'], input=STARTS % PRESENT_JS.read_text(), capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [['/present/end'], ['/present/end', '/present/start', 'open k2']]

def _nb(path, meta, cells=None):
    cells = cells or [{'cell_type': 'markdown', 'id': 'm1', 'metadata': {'slideshow': {'slide_type': 'slide'}}, 'source': '# hi'}]
    path.write_text(json.dumps({'cells': cells, 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))
    return path

def test_a_notebook_tab_carries_its_rise_settings_and_each_cells_slide_type(tmp_path):
    metas = {'both.ipynb': ({'livereveal': {'theme': 'night', 'width': 1000}, 'rise': {'width': '100%'}}, {'theme': 'night', 'width': '100%'}),
             'odd.ipynb': ({'rise': 'big', 'livereveal': {'theme': 'sky'}}, {'theme': 'sky'}),
             'none.ipynb': ({}, {})}
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        for name, (meta, want) in metas.items():
            p = _nb(tmp_path/name, meta)
            ws.open(p)
            st = c.get('/tab/state', params={'path': str(p)}).json()
            assert st['rise'] == want, name
            assert st['cells'][0]['extra'] == {'slideshow': {'slide_type': 'slide'}}

def test_present_is_one_action_with_the_same_name_everywhere_it_appears():
    from leela.core.keys import DEFAULTS, _dupes, lookup
    from leela.core.ui import BUTTONS
    from leela.blocks.keys.menus import BAR, web_menus
    from leela.app import _toolbar
    k = lookup('present_notebook')
    assert (k.key, k.scope, k.label) == ('alt+r', 'global', 'present notebook as slides')
    assert lookup('present_from_cell').label == 'present from this cell'
    assert _dupes(DEFAULTS) == []
    menus = web_menus()
    assert 'present_notebook' in [r.get('action') for r in menus['tab']]
    assert 'present_from_cell' in [r.get('action') for r in menus['cell']]
    assert 'present_notebook' in [getattr(r, 'action', None) for name, rows in BAR if name == 'View' for r in rows]
    assert any(b.action == 'present_notebook' and b.bar == 'toolbar' for b in BUTTONS)
    from fasthtml.common import to_xml
    assert 'data-action="present_notebook"' in to_xml(_toolbar())
    js = (ROOT/'leela'/'static'/'js'/'actions.js').read_text()
    assert 'present_notebook:' in js and 'present_from_cell:' in js

def test_the_notes_page_and_its_routes_are_gone(tmp_path):
    "Task 4 on purpose: the notes drawer replaces the notes page, and the room stream replaces `/present/state` and `/present/nav`."
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as c:
        for m, p in (('get', '/present/notes'), ('get', '/present/state'), ('post', '/present/state'), ('post', '/present/nav')):
            assert getattr(c, m)(p).status_code in (404, 405), p
    assert not (ROOT/'leela'/'static'/'present-notes.html').exists() and not (ROOT/'leela'/'vendor'/'reveal').exists()

def _setup(rel):
    spec = importlib.util.spec_from_file_location(f'pkg_{Path(rel).parent.name}', ROOT/rel)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

AUDIENCE = ('leela/static/present-audience.html', 'leela/static/lee-slides.css', 'leela/static/lee-slides.js')

@pytest.mark.parametrize('rel', ['packaging/macos/setup.py', 'packaging/windows/setup.py'])
def test_the_desktop_builds_carry_the_audience_page_and_no_reveal(rel):
    "Task 4 on purpose: reveal.js and the notes page left; the audience page and the shared renderer replace them."
    shipped = {str(Path(f).relative_to(ROOT)) for _, fs in _setup(rel).DATA_FILES for f in fs}
    for f in AUDIENCE: assert f in shipped, f
    assert not [f for f in shipped if f.startswith('leela/vendor/reveal/') or f.endswith('present-notes.html')]

def test_the_wheel_carries_the_audience_page_and_no_reveal():
    import zipfile
    wheels = sorted((ROOT/'dist').glob('leela-*.whl'))
    if not wheels: pytest.skip('no wheel in dist/ — run python -m build --wheel first')
    with zipfile.ZipFile(wheels[-1]) as z: names = set(z.namelist())
    for f in AUDIENCE: assert f in names, f
    assert not [f for f in names if f.startswith('leela/vendor/reveal/') or f.endswith('present-notes.html')]
