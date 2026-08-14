"Search block: Kosha/litesearch façade over a workspace folder."

import pytest

from leela.core.block import Ctx

def test_search_finds_workspace_file(ws):
    hits = list(ws.search.search('block fixture', limit=5) or [])
    assert hits or ws.search.note
    assert isinstance(ws.search.note, str)

def test_search_ctx_cap(ws):
    ctx = Ctx(ws, 'search', caps=('search',))
    assert ctx.search is ws.search
    with pytest.raises(AttributeError, match='without declaring it'): _ = ctx.research
