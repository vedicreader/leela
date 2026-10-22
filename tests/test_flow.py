import sys
from kosha.graph import CodeGraph
from leela.blocks.canvas.change import snip, snip_root
from leela.blocks.canvas.doc import Canvas
from leela.blocks.canvas.flow import flow, trace, unrun

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
    assert '10' in notes and "'a/4'" in notes
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
    assert "'small'" in ' '.join(b.body for b in doc.of('note'))
    assert not any('fetch(' in b.body for b in doc.of('code')), 'a coroutine is not replayed as if it returned its result'


