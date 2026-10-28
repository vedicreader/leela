import pytest
from leela.blocks.learn.learn import lookup, pkg_names, scratch_cell
from leela.blocks.nb.lesson import lesson_notebook

# the shape of a real `env_context` row: kosha has already parsed `metadata`
ROW = dict(rowid=7, rank=-1.5, _rrf_score=.03, package='pydantic_ai',
           content='def run_sync(self, prompt):\n    "Run the agent."\n' + 'x = 1\n' * 30,
           metadata=dict(name='run_sync', path='pydantic_ai/agent.py', lineno=40, docstring='Run the agent.\n\nMore.', mod_name='pydantic_ai.agent'))

class FakeKosha:
    def __init__(self, have=('pydantic_ai', 'jupyter_server', 'Jinja2', 'yt-dlp')): self.calls, self.have = [], have
    def env_context(self, q, **kw): self.calls.append((q, kw)); return [ROW]
    def pkgs2consider(self, sys_wide=True): return dict.fromkeys(self.have).keys()

def test_lookup_rows_and_package_filter():
    k = FakeKosha()
    rows = lookup(k, 'run sync', packages=['pydantic-ai'])
    assert rows == [dict(name='run_sync', package='pydantic_ai', path='pydantic_ai/agent.py', line=40,
                         doc='Run the agent.', snippet='\n'.join(ROW['content'].splitlines()[:12]))]
    assert k.calls[0] == ('run sync', dict(limit=8, where="(package='pydantic_ai')"))
    assert lookup(k, '') == [] and lookup(None, 'x') == []
    lookup(k, 'x')
    assert k.calls[-1][1]['where'] is None

def test_package_names_match_the_form_kosha_indexed():
    k = FakeKosha()
    for given, stored in [('jupyter-server', 'jupyter_server'), ('jinja2', 'Jinja2'), ('YT_DLP==1.0', 'yt-dlp'), ('pydantic-ai-slim[openai]==1.0.2', 'pydantic-ai-slim')]:
        lookup(k, 'x', packages=[given])
        assert k.calls[-1][1]['where'] == f"(package='{stored}')"
    lookup(k, 'x', packages=['httpx', 'jinja2'])
    assert k.calls[-1][1]['where'] == "(package='Jinja2')"

def test_package_names_are_base_names():
    assert pkg_names(['pydantic-ai-slim[openai]==1.0.2', 'httpx', 'httpx>=0.27']) == ['httpx', 'pydantic-ai-slim']
    assert pkg_names([]) == []

@pytest.mark.parametrize('bad', [list('abcdef'), ["x' OR 1=1 --"], ['a"b'], ['-e .'], ['--index-url=https://x'], ['https://x/p.whl'],
                                 ['../p'], ['/tmp/p'], ['p; rm -rf ~'], ['p @ file:///x'], ['git+https://x'], ['']])
def test_package_names_refuse_everything_else(bad):
    k = FakeKosha()
    with pytest.raises(ValueError): pkg_names(bad)
    with pytest.raises(ValueError): lookup(k, 'x', packages=bad)
    assert k.calls == []

SPEC = dict(task='Double it.', fname='double', stub='def double(x): pass',
            tests=[dict(say='doubles 2', test='assert double(2) == 4', shown=True)])

def test_scratch_never_touches_the_graded_cell():
    nb = lesson_notebook('Doubling', SPEC)
    graded = next(c for c in nb.cells if 'tests' in c.extra.get('exercise', {}))
    before, extra, n = graded.source, repr(graded.extra), len(nb.cells)
    c = scratch_cell(nb, 'from pydantic_ai import Agent')
    assert nb.cells[-1] is c and c.extra == {'lesson': {'role': 'scratch'}} and c.cell_type == 'code' and c.source == 'from pydantic_ai import Agent'
    assert graded.source == before and repr(graded.extra) == extra and len(nb.cells) == n + 1 and nb.dirty
