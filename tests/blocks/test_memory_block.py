"Memory block: Vishalakshi vault shelves, remember/search, safe shelf ids."

import pytest

from leela.blocks.memory.memory import GLOBAL, Memory, safe_shelf
from leela.blocks.research.research import Doc
from leela.core.ctx import Ctx


def test_safe_shelf_normalises_folder_names():
    assert safe_shelf('my-repo') == safe_shelf('My.Repo') == 'my_repo'
    assert safe_shelf('') == safe_shelf(None) == 'main'


def test_remember_skips_unchanged_source(tmp_path):
    m = Memory(shelf='proj', path=tmp_path / 'v.db', offline=True)
    doc = Doc(title='Page', url='https://ex.ample/a', text='hello vault ' * 20, kind='page')
    a, b = m.remember(doc, query='q'), m.remember(doc, query='q')
    assert a and a.get('source') == 'https://ex.ample/a'
    assert b and (b.get('skipped') or b.get('doc_id'))


def test_agent_shelf_is_global(tmp_path):
    m = Memory(shelf='proj', path=tmp_path / 'v.db', offline=True)
    saved = m.remember_agent_note('Note', 'durable agent prose ' * 10)
    assert saved and saved.get('doc_id')
    assert m.shelf_name == 'proj' and GLOBAL == 'leela'


def test_memory_ctx_cap(ws):
    ctx = Ctx(ws, 'memory', caps=('memory',))
    assert ctx.memory is ws.memory
    with pytest.raises(AttributeError, match='without declaring it'): _ = ctx.search
