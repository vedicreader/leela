"Setting a cell's RISE slide type: the edit route, undo, the saved file, and the actions that reach it."

import json

from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace

ACTS = [f'slide_{t}' for t in ('none', 'slide', 'subslide', 'fragment', 'skip', 'notes')]

def _nb(path):
    cell = lambda i, meta: {'cell_type': 'markdown', 'id': i, 'metadata': meta, 'source': f'# {i}'}
    cells = [cell('a', {}), cell('b', {'slideshow': {'slide_type': '-', 'data': {'x': 1}}}), cell('c', {'slideshow': 'odd'}),
             cell('d', {'tags': ['t']})]
    path.write_text(json.dumps({'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return path

def test_a_slide_type_is_set_undone_saved_and_removed_through_the_edit_route(tmp_path):
    p, ws = _nb(tmp_path/'deck.ipynb'), Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        ws.open(p)
        edit = lambda **d: c.post('/nb/edit', json=d)
        shows = lambda r: [x['extra'].get('slideshow') for x in r.json()['cells']]
        r = edit(op='slide', i=0, indices=[2, 0, 1], type='fragment')
        assert shows(r) == [{'slide_type': 'fragment'}, {'slide_type': 'fragment', 'data': {'x': 1}}, {'slide_type': 'fragment'}, None]
        assert shows(edit(op='slide', i=0, type='notes'))[0] == {'slide_type': 'notes'}, 'no indices means cell i'
        assert shows(edit(op='undo', i=0))[0] == {'slide_type': 'fragment'}, 'undo restores the type before'
        assert c.post('/nb/save', json={'path': str(p), 'cells': []}).json()['ok']
        disk = json.loads(p.read_text())['cells']
        assert [x['metadata'].get('slideshow', {}).get('slide_type') for x in disk] == ['fragment'] * 3 + [None]
        assert disk[3]['metadata'] == {'tags': ['t']}
        r = edit(op='slide', i=0, indices=[0, 1, 3], type='none')
        assert [x['extra'] for x in r.json()['cells']] == [{}, {'slideshow': {'data': {'x': 1}}},
                                                         {'slideshow': {'slide_type': 'fragment'}}, {'tags': ['t']}]
        for bad in ({'type': 'title'}, {'indices': [9]}, {'indices': [-1]}, {'indices': ['x']}):
            assert edit(op='slide', i=0, **{'type': 'slide', **bad}).status_code == 400, bad
        assert shows(edit(op='undo', i=0))[0] == {'slide_type': 'fragment'}, 'a refused edit left an undo step'
        edit(op='redo', i=0)
        assert c.post('/nb/save', json={'path': str(p), 'cells': []}).json()['ok']
        assert 'slideshow' not in json.loads(p.read_text())['cells'][0]['metadata']

def test_slide_types_are_cell_menu_and_palette_actions_with_the_rise_chords():
    from leela.core.keys import DEFAULTS, _dupes, lookup
    from leela.blocks.keys.menus import web_menus
    assert _dupes(DEFAULTS) == []
    assert [lookup(a).key for a in ACTS] == ['', 'shift+i', 'shift+b', 'shift+g', '', '']
    assert all(lookup(a).scope == 'editor' and lookup(a).label.startswith('slide type: ') for a in ACTS)
    rows = [r.get('action') for r in web_menus()['cell']]
    assert rows[rows.index(ACTS[0]):rows.index(ACTS[0]) + 6] == ACTS, 'one group in the cell menu'
