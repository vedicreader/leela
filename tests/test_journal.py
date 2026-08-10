import pytest
from leela.fs import Sandbox
from leela.core.journal import OperationJournal


def test_workspace_journal_persists_and_undoes_only_exact_outputs(tmp_path):
    root = tmp_path/'project'; root.mkdir(); path = root/'a.py'; path.write_text('before\n')
    journal = OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    path.write_text('after\n')
    op = journal.record('Save a.py', [(path, 'before\n', 'after\n')])
    assert OperationJournal(tmp_path/'journal.json', Sandbox([root])).rows()[0]['id'] == op['id']
    journal.undo(op['id']); assert path.read_text() == 'before\n'


def test_workspace_journal_refuses_diverged_files_atomically(tmp_path):
    root = tmp_path/'project'; root.mkdir(); a=root/'a'; b=root/'b'; a.write_text('a1'); b.write_text('b1')
    journal=OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    a.write_text('a2'); b.write_text('b2'); op=journal.record('two files',[(a,'a1','a2'),(b,'b1','b2')])
    b.write_text('newer')
    with pytest.raises(ValueError, match='changed after'):
        journal.undo(op['id'])
    assert a.read_text() == 'a2' and b.read_text() == 'newer'
