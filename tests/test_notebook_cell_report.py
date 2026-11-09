"The page tells the server which cell it is on; the next agent turn anchors on it without sending the id again."
from tests.test_modes import _nb, hcl, home  # noqa: F401


def test_the_cell_report_sets_the_anchor_for_the_next_turn(home, hcl):
    ws, cl = home, hcl
    assert cl.post('/nb/cell', json={'cell': 'c1'}).json() == {'ok': False, 'cell': ''}
    ws.open(str(_nb(ws.fs.roots[0])))
    assert cl.post('/nb/cell', json={'cell': 'c1'}).json() == {'ok': True, 'cell': 'c1'}
    assert ws.tab.cell == 'c1'
    r = cl.post('/nb/cell', json={'cell': 'gone'}); assert r.status_code == 409 and ws.tab.cell == 'c1'
    assert cl.post('/nb/cell', json=['c1']).status_code == 400
    seen = []
    ws.threads.active.runner.start = lambda q, att, reasoning, context, path, grounding: seen.append(context) or {'ok': True}
    cl.post('/agent/turn', json={'prompt': 'why?'})
    assert '<active-cell id="c1"' in seen[-1] and 'print("hi")' in seen[-1]
    cl.post('/nb/cell', json={'cell': 'c2'})
    cl.post('/agent/turn', json={'prompt': 'why?'})
    assert '<active-cell id="c2"' in seen[-1] and 'ZeroDivisionError' in seen[-1]
