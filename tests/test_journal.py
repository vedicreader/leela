import pytest
from leela.blocks.fs.fs import Sandbox
from leela.core.journal import OperationJournal


def test_workspace_journal_persists_and_undoes_only_exact_outputs(tmp_path):
    root = tmp_path/'project'; root.mkdir(); path = root/'a.py'; path.write_text('before\n')
    journal = OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    path.write_text('after\n')
    op = journal.record('Save a.py', [(path, 'before\n', 'after\n')])
    assert OperationJournal(tmp_path/'journal.json', Sandbox([root])).rows()[0]['id'] == op['id']
    journal.undo(op['id']); assert path.read_text() == 'before\n'


def test_workspace_journal_redoes_only_the_exact_undone_output(tmp_path):
    root = tmp_path/'project'; root.mkdir(); path = root/'a.py'; path.write_text('before\n')
    journal = OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    path.write_text('after\n'); op = journal.record('Save a.py', [(path, 'before\n', 'after\n')])
    journal.undo(op['id']); journal.redo(op['id'])
    assert path.read_text() == 'after\n'
    journal.undo(op['id']); path.write_text('other\n')
    with pytest.raises(ValueError, match='changed after the undo'):
        journal.redo(op['id'])


def test_unnamed_redo_walks_back_up_the_stack_in_the_order_undo_came_down(tmp_path):
    """Two undos then two redos on one file.

    Undo peels newest-first, so the newest undone operation is the *last* one that can be
    redone; picking it first found the file at the older operation's `before` text and refused.
    """
    root = tmp_path/'project'; root.mkdir(); path = root/'a.py'; path.write_text('v0')
    journal = OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    first_op = journal.record('one', [(path, 'v0', 'v1')]); path.write_text('v1')
    second_op = journal.record('two', [(path, 'v1', 'v2')]); path.write_text('v2')
    journal.undo(); journal.undo()
    assert path.read_text() == 'v0'
    assert journal.redo()['id'] == first_op['id'] and path.read_text() == 'v1'
    assert journal.redo()['id'] == second_op['id'] and path.read_text() == 'v2'


def test_a_new_edit_ends_the_redo_branch(tmp_path):
    root = tmp_path/'project'; root.mkdir(); path = root/'a.py'; path.write_text('v0')
    journal = OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    journal.record('one', [(path, 'v0', 'v1')]); path.write_text('v1')
    journal.undo(); assert path.read_text() == 'v0'
    journal.record('branch', [(path, 'v0', 'w1')]); path.write_text('w1')
    assert not any(row['redoable'] for row in journal.rows())
    with pytest.raises(ValueError, match='no redoable'):
        journal.redo()


def test_workspace_journal_refuses_diverged_files_atomically(tmp_path):
    root = tmp_path/'project'; root.mkdir(); a=root/'a'; b=root/'b'; a.write_text('a1'); b.write_text('b1')
    journal=OperationJournal(tmp_path/'journal.json', Sandbox([root]))
    a.write_text('a2'); b.write_text('b2'); op=journal.record('two files',[(a,'a1','a2'),(b,'b1','b2')])
    b.write_text('newer')
    with pytest.raises(ValueError, match='changed after'):
        journal.undo(op['id'])
    assert a.read_text() == 'a2' and b.read_text() == 'newer'
