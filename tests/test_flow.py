import sys, pytest
from fastcore.all import first
from kosha.graph import CodeGraph
from leela.blocks.canvas.change import snip, snip_root
from leela.blocks.canvas.doc import Canvas
from leela.blocks.canvas.flow import build, flow, flow_path, resolve, slice_, trace, unrun

CORE = r'''import os

class Box:
    def size(self, x): return x * 2

def leaf(x):
    if x > 1:
        y = x + 1
    else:
        y = 0
    return os.path.join('a', str(y))

def mid(x):
    Box().size(x)
    label('x' * 300)
    return leaf(x)

def top(x): return mid(x)

def label(s): return s[:3]

def setup(): return 1

def logged(f):
    import functools
    @functools.wraps(f)
    def inner(*a, **kw): return f(*a, **kw)
    return inner

@logged
def wrapped(x):
    if x:
        return x + 1
    return 0

async def fetch(x):
    import asyncio
    await asyncio.sleep(0)
    if x > 5:
        return 'big'
    return 'small'
'''

TEST = r'''from pkg.core import setup, top

def test_top():
    setup()
    assert top(3) == 'a/4'

def test_more():
    import asyncio
    from pkg.core import fetch, wrapped
    assert wrapped(2) == 3 and asyncio.run(fetch(2)) == 'small'
'''

def _pkg(tmp):
    (tmp/'pkg').mkdir(); (tmp/'pkg'/'__init__.py').write_text('')
    (tmp/'pkg'/'core.py').write_text(CORE)
    (tmp/'tests').mkdir(); (tmp/'tests'/'test_core.py').write_text(TEST)
    return tmp, CodeGraph().from_dir(tmp/'pkg')

def test_a_flow_walks_what_the_entry_calls_inside_its_package_and_cites_each_function(tmp_path):
    root, g = _pkg(tmp_path)
    assert resolve(g, 'top') == ('pkg.core.top', []), 'a bare tail that names one function resolves to it'
    rows = slice_(g, 'pkg.core.top')
    names = [r['node'] for r in rows]
    assert names[:2] == ['pkg.core.top', 'pkg.core.mid'] and set(names[2:]) == {'pkg.core.Box', 'pkg.core.leaf', 'pkg.core.label'}, names
    assert all(n.startswith('pkg.') for n in names), 'os.path.join is outside the package'
    assert {r['node']: r['parent'] for r in rows}['pkg.core.leaf'] == 'pkg.core.mid'
    doc = Canvas.parse(build('top', rows, root).md())
    snips = {b.attrs['symbol']: b for b in doc.of('snippet')}
    assert {'top', 'mid', 'leaf'} <= set(snips) and len(doc.of('snippet')) == len(rows)
    assert snip(snips['mid'], root).startswith('def mid'), 'the brick cites the real source, relative to the root'
    assert not doc.of('note', 'code'), 'nothing is claimed about a run that did not happen'

def test_a_trace_records_the_calls_one_test_made_and_the_lines_it_skipped(tmp_path):
    root, g = _pkg(tmp_path)
    t = trace(sys.executable, root, 'tests/test_core.py::test_top')
    assert t['ok'], t.get('error')
    q = [c['qualname'] for c in t['calls']]
    assert q.index('top') < q.index('mid') < q.index('leaf') and 'test_top' not in q, q
    by = {c['qualname']: c for c in t['calls']}
    assert by['top']['args'] == {'x': '3'} and by['top']['ret'] == "'a/4'"
    assert by['leaf']['parent'] == by['mid']['id'] and by['Box.size']['parent'] == by['mid']['id']
    leaf = by['leaf']
    assert unrun(leaf['file'], 'leaf', t['lines'][f"{leaf['file']}::leaf"]) == [10], 'only the else branch did not run'
    r = flow(g, root, 'pkg.core.top', python=sys.executable, test='tests/test_core.py::test_top')
    assert r['ok'] and r['traced'] and not r['note'], r
    doc = Canvas.parse(r['canvas'].md())
    notes = ' '.join(b.body for b in doc.of('note'))
    assert 'Lines not run in this trace: 10.' in notes and "returned `'a/4'`" in notes and 'returned `6`' in notes
    assert any(b.body.strip() == 'from pkg.core import top\ntop(x=3)' for b in doc.of('code')), 'a literal call can be run again'
    cited = [b.attrs['symbol'] for b in doc.of('snippet')]
    assert 'Box.size' in cited, 'a method the run reached is on the canvas'
    assert {b.attrs['path'] for b in doc.of('snippet')} == {'../pkg/core.py'}, 'frozen stdlib modules are not the project'
    (root/'flows').mkdir()
    assert snip(doc.of('snippet')[0], snip_root(r['path'])).startswith('def top'), 'cited from where the canvas will look, outside git too'
    assert 'setup' not in cited, 'what the test did before calling the entry is not part of its flow'
    assert 'label' in cited and not any('import label' in b.body for b in doc.of('code')), 'a cut-off argument is never replayed'

def test_a_trace_sees_through_decorators_and_across_awaits(tmp_path):
    root, g = _pkg(tmp_path)
    t = trace(sys.executable, root, 'tests/test_core.py::test_more')
    assert t['ok'], t.get('error')
    by = {c['qualname']: c for c in t['calls']}
    assert by['wrapped']['parent'] == by['logged.<locals>.inner']['id'] and by['wrapped']['ret'] == '3'
    assert by['fetch']['args'] == {'x': '2'} and by['fetch']['ret'] == "'small'", 'the result survives the suspension at await'
    at = lambda s: CORE.splitlines().index(s) + 1
    f = by['fetch']['file']
    assert unrun(f, 'wrapped', t['lines'][f'{f}::wrapped']) == [at('    return 0')]
    assert unrun(f, 'fetch', t['lines'][f'{f}::fetch']) == [at("        return 'big'")]
    r = flow(g, root, 'pkg.core.fetch', python=sys.executable, test='tests/test_core.py::test_more')
    assert r['ok'] and r['traced'], r
    doc = Canvas.parse(r['canvas'].md())
    assert "returned `'small'`" in ' '.join(b.body for b in doc.of('note'))
    assert not any('fetch(' in b.body for b in doc.of('code')), 'a coroutine is not replayed as if it returned its result'

def test_a_flow_that_cannot_run_or_resolve_answers_in_a_sentence(tmp_path):
    root, g = _pkg(tmp_path)
    t = trace(sys.executable, root, 'tests/test_core.py::nope')
    assert not t['ok'] and isinstance(t['error'], str) and t['error']
    r = flow(g, root, 'pkg.core.top', python=sys.executable, test='tests/test_core.py::nope')
    assert r['ok'] and not r['traced'] and 'static call graph' in r['note'], 'a failed trace still builds the static flow'
    miss = flow(g, root, 'nothing_like_this')
    assert not miss['ok'] and 'no single function' in miss['error']
    p = flow_path(root, 'Pkg Core.top')
    assert p == str(root/'flows'/'pkg-core-top.canvas.md')
    (root/'flows').mkdir(); (root/'flows'/'pkg-core-top.canvas.md').write_text('')
    assert flow_path(root, 'Pkg Core.top') == str(root/'flows'/'pkg-core-top-2.canvas.md'), 'an existing file is never the target'
    for bad in (str(root.parent/'out'), '../out', '.'):
        with pytest.raises(ValueError): flow_path(root, 'x', bad)
    assert not flow(g, root, 'pkg.core.top', path='/tmp/out')['ok'], 'a path outside the project is refused, not written'

def test_the_agent_is_offered_flow_canvas_with_no_canvas_open_and_can_take_its_write_back(tmp_path):
    from leela.workspace import Workspace
    root, _ = _pkg(tmp_path)
    CodeGraph(root/'.kosha'/'graph.db').from_dir(root/'pkg')
    ai = Workspace(roots=[root]).ai
    ai.tools
    tool = first(t for t in ai.registry.tools if t.__name__ == 'flow_canvas')
    assert tool is not None, 'it makes a canvas, so it cannot wait for one to be open'
    ai.registry.fire('before_tool', ai, 'flow_canvas', {'entry': 'pkg.core.top'})
    said = tool(entry='pkg.core.top')
    p = root/'flows'/'pkg-core-top.canvas.md'
    assert said.startswith('wrote flows/pkg-core-top.canvas.md (static call graph)') and p.exists(), said
    was, now = ai.changes()[str(p)]
    assert was == '' and 'symbol=mid' in now, 'undo sees the new file, predicted by the rule the tool wrote by'
    assert 'no single function' in tool(entry='nothing_like_this')
    before = p.read_text()
    assert 'already exists' in tool(entry='pkg.core.mid', path='flows/pkg-core-top') and p.read_text() == before, 'a named path never overwrites'
    from starlette.testclient import TestClient
    from leela.app import ide_app
    client = TestClient(ide_app(ai.ws))
    mid = first(b for b in Canvas.load(p).of('snippet') if b.attrs['symbol'] == 'mid')
    got = client.get('/canvas/snip', params={'path': str(p), 'id': mid.id}).json()
    assert got['ok'] and got['code'].startswith('def mid'), 'the live canvas shows the cited source'
    evil = root/'flows'/'evil.canvas.md'
    evil.write_text("```canvas snippet id=e1 path=../../../../../../etc/hosts\n```\n")
    got = client.get('/canvas/snip', params={'path': str(evil), 'id': 'e1'}).json()
    assert not got['ok'] and 'code' not in got, 'a document cannot read outside the open folders'
    out = tmp_path.parent/f'{tmp_path.name}-secret.py'; out.write_text('SECRET = 1\n')
    (evil.parent/'plain.py').write_text('PLAIN = 1\n'); (evil.parent/'link.py').symlink_to(out)
    evil.write_text("```canvas snippet id=e2 path=link.py\n```\n\n```canvas snippet id=e3 path=plain.py\n```\n")
    assert client.get('/canvas/snip', params={'path': str(evil), 'id': 'e3'}).json()['code'] == 'PLAIN = 1\n'
    got = client.get('/canvas/snip', params={'path': str(evil), 'id': 'e2'}).json()
    assert not got['ok'] and 'code' not in got, 'nor through a symlink inside them'
