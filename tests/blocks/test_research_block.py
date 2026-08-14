"Research block: fossick search/read/dig through Sandbox, optional vault remember."

from types import SimpleNamespace

import pytest

from leela.blocks.fs.fs import Sandbox
from leela.blocks.memory.memory import Memory
from leela.blocks.research.research import Research
from leela.core.block import Ctx

def test_research_search_passes_n_to_fossick(monkeypatch, tmp_path):
    seen = {}
    def search(q, category='text', n=10, **kw):
        seen.update(dict(q=q, n=n, category=category))
        return [dict(title='A', href='https://a.example') for _ in range(n)]
    r = Research(Sandbox([tmp_path]))
    monkeypatch.setattr(r, '_fossick', lambda: SimpleNamespace(search=search))
    hits = r.search('widgets', n=3)
    assert seen == dict(q='widgets', n=3, category='text')
    assert len(hits) == 3

def test_research_dig_files_into_memory(monkeypatch, tmp_path):
    body = 'cited paragraph ' * 80
    def research(q, n=5, **kw):
        return dict(query=q, sources=[dict(title='One', href='https://one.example', md=body)],
            digest=f'## One\nhttps://one.example\n\n{body}', dropped=[], plan=[q])
    mem = Memory(shelf='proj', path=tmp_path / 'vault.db', offline=True)
    r = Research(Sandbox([tmp_path]), memory=mem)
    monkeypatch.setattr(r, '_fossick', lambda: SimpleNamespace(research=research))
    docs, digest = r.dig('widgets', n=1)
    assert docs and docs[0].memory_id
    assert 'One' in digest
    assert mem.note.startswith('remembered') or 'already' in mem.note

def test_research_ctx_exposes_only_research_cap(ws):
    ctx = Ctx(ws, 'research', caps=('research',))
    assert ctx.research is ws.research
    with pytest.raises(AttributeError, match='without declaring it'): _ = ctx.memory
