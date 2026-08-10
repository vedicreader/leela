"""Tests for the notebook document, and for the prompt cell in particular.

Two things here are worth guarding closely. The first is that a prompt cell survives a
round trip through a file format that has no such cell type -- it is written as markdown
with its answer in metadata, and if either half of that drifts the answer is silently
lost. The second is `context()`, which decides what the assistant is told; too little and
it answers the wrong question, too much and it burns the window restating what it was
told a moment ago.
"""

import asyncio
import json

import pytest

from leela.blocks.nb.nb import CELL_TYPES, Cell, Notebook


def dialog():
    "A notebook with all three cell types, one prompt answered and one not."
    return Notebook([
        Cell(source='## Loading', cell_type='markdown', id='m1'),
        Cell(source='df = load()', cell_type='code', id='c1', execution_count=1,
             outputs=[{'output_type': 'execute_result', 'execution_count': 1, 'metadata': {},
                       'data': {'text/plain': 'a    6\ndtype: int64'}}]),
        Cell(source='why is the sum 6?', cell_type='prompt', id='p1',
             reply='Because 1+2+3 = 6.', calls=[{'tool': 'run_python', 'args': '{}'}]),
        Cell(source='df.mean()', cell_type='code', id='c2'),
        Cell(source='and the mean?', cell_type='prompt', id='p2'),
    ])


# -- round trip ------------------------------------------------------------
def test_a_prompt_cell_is_written_as_valid_markdown(tmp_path):
    "nbformat has no prompt cell, so plain Jupyter must still be able to open the file."
    p = tmp_path / 'd.ipynb'
    dialog().save(p)
    raw = json.loads(p.read_text())
    assert [c['cell_type'] for c in raw['cells']] == ['markdown', 'code', 'markdown', 'code', 'markdown']
    assert raw['cells'][2]['metadata']['leela']['kind'] == 'prompt'
    nbformat = pytest.importorskip('nbformat')
    nbformat.validate(nbformat.read(str(p), as_version=4))


def test_a_zero_byte_notebook_opens_as_a_new_document(tmp_path):
    """Creating `name.ipynb` through a generic file action used to open a JSONDecodeError."""
    p = tmp_path / 'new.ipynb'
    p.touch()
    nb = Notebook.load(p)
    assert len(nb) == 1 and nb[0].cell_type == 'code'
    nb.save()
    assert json.loads(p.read_text())['nbformat'] == 4


def test_project_execution_initializes_only_zero_byte_notebook_placeholders(tmp_path):
    from leela.workspace import Workspace
    good, empty, malformed = tmp_path/'good.ipynb', tmp_path/'empty.ipynb', tmp_path/'broken.ipynb'
    Notebook.blank(good).save(); empty.touch(); malformed.write_text('{not json')
    ws = Workspace(roots=[tmp_path])
    assert ws.initialize_empty_notebooks(tmp_path) == [str(empty)]
    assert json.loads(empty.read_text())['nbformat'] == 4
    assert malformed.read_text() == '{not json'


def test_creating_an_ipynb_by_filename_writes_valid_json(tmp_path):
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    p = tmp_path / 'new.ipynb'
    ws.create_document(p)
    raw = json.loads(p.read_text())
    assert raw['nbformat'] == 4
    assert Notebook.load(p)[0].cell_type == 'code'


def test_the_answer_survives_the_round_trip(tmp_path):
    p = tmp_path / 'd.ipynb'
    dialog().save(p)
    back = Notebook.load(p)
    assert [c.cell_type for c in back.cells] == ['markdown', 'code', 'prompt', 'code', 'prompt']
    assert back[2].reply == 'Because 1+2+3 = 6.'
    assert back[2].calls == [{'tool': 'run_python', 'args': '{}'}]
    assert back[1].text.startswith('a    6')          # code outputs still round-trip


def test_an_unanswered_prompt_round_trips_too(tmp_path):
    p = tmp_path / 'd.ipynb'
    dialog().save(p)
    assert Notebook.load(p)[4].reply == ''


def test_cell_run_persists_the_kernels_reconciled_display_updates():
    first = {'output_type': 'display_data', 'data': {'text/markdown': 'first'}, 'metadata': {}}
    final = {'output_type': 'display_data', 'data': {'text/markdown': 'final'}, 'metadata': {}}
    class Result:
        outputs = [final]
        execution_count = 2
    class Kernel:
        async def execute(self, source, on_output=None):
            on_output(first); on_output(final)
            return Result()
    nb = Notebook([Cell(source='display_stream(...)', cell_type='code')])
    asyncio.run(nb.run(0, Kernel()))
    assert nb[0].outputs == [final]
    assert nb[0].execution_ms is not None and nb[0].execution_ms >= 0


def test_saved_execution_is_historical_until_it_runs_in_the_current_kernel(tmp_path):
    p = tmp_path/'previous.ipynb'
    nb = Notebook([Cell(source='x = 1', execution_count=3, execution_ms=42, fresh=True)])
    nb.save(p)
    assert Notebook.load(p)[0].fresh is False

    class Result:
        outputs = []
        execution_count = 1
    class Kernel:
        async def execute(self, source, on_output=None): return Result()
    asyncio.run(nb.run(0, Kernel()))
    assert nb[0].fresh is True


def test_execution_time_survives_the_notebook_round_trip(tmp_path):
    p = tmp_path/'timed.ipynb'
    nb = Notebook([Cell(source='1 + 1', execution_count=1, execution_ms=127.4),
                   Cell(source='explain it', cell_type='prompt', reply='two', execution_ms=2048.2)])
    nb.save(p)
    back = Notebook.load(p)
    assert back[0].execution_ms == pytest.approx(127.4)
    assert back[1].execution_ms == pytest.approx(2048.2)


# -- cell types ------------------------------------------------------------
def test_cycling_visits_every_type():
    nb = Notebook([Cell(source='x')])
    assert [nb.cycle_type(0).cell_type for _ in CELL_TYPES] == ['markdown', 'prompt', 'code']


def test_changing_type_discards_the_answer():
    "A prompt turned into prose is no longer an answered question."
    nb = dialog()
    assert nb.set_type(2, 'markdown').reply == ''


# -- context ---------------------------------------------------------------
def test_context_carries_complete_cell_details_output_and_prose():
    ctx = dialog().context(2)
    assert '<cell id="m1" type="markdown" compact="auto">' in ctx and '## Loading' in ctx
    assert '<cell id="c1" type="code" compact="auto">' in ctx and 'df = load()' in ctx
    assert '<output>' in ctx and 'dtype: int64' in ctx


def test_every_cell_above_a_prompt_is_fresh_context():
    """The notebook, not stale backend history, is the inline agent's source of truth."""
    nb = dialog()
    assert nb.prompt_start(4) == 0
    ctx = nb.context(4, since=nb.prompt_start(4))
    assert 'df.mean()' in ctx
    assert '## Loading' in ctx and 'why is the sum 6?' in ctx


def test_an_earlier_prompt_reads_from_the_top():
    nb = dialog()
    assert nb.prompt_start(2) == 0


def test_context_includes_earlier_questions_and_answers():
    ctx = dialog().context(4, since=0)
    assert 'type="prompt"' in ctx and 'why is the sum 6?' in ctx
    assert '<answer>' in ctx and 'Because 1+2+3 = 6.' in ctx


def test_context_does_not_clip_outputs_by_default():
    nb = dialog()
    nb[1].outputs[0]['data']['text/plain'] = 'x' * 5000
    assert 'x' * 5000 in nb.context(4)
    assert len(nb.context(4, out_chars=5)) < len(nb.context(4))


def test_explicit_context_compaction_preserves_keep_and_drops_discard_first():
    nb = dialog()
    nb[0].context_mode = 'keep'
    nb[1].context_mode = 'discard'
    ctx = nb.context(4, since=0, max_chars=180)
    assert '## Loading' in ctx
    assert 'df = load()' not in ctx


def test_context_of_the_first_cell_is_empty():
    assert dialog().context(0) == ''


def test_cell_operations_can_be_undone_and_redone():
    nb = Notebook([Cell(source='keep', id='a'), Cell(source='restore me', id='b')])
    deleted = nb.delete(1)
    assert deleted.id == 'b' and [c.id for c in nb.cells] == ['a']

    assert nb.undo() == 1
    assert [(c.id, c.source) for c in nb.cells] == [('a', 'keep'), ('b', 'restore me')]
    assert nb.redo() == 0
    assert [c.id for c in nb.cells] == ['a']


def test_new_cell_operation_clears_redo_history():
    nb = Notebook([Cell(source='a'), Cell(source='b')])
    nb.delete(1)
    nb.undo()
    nb.insert(2, Cell(source='c'))
    assert nb.redo() is None


def test_deleting_the_only_cell_is_undoable():
    nb = Notebook([Cell(source='do not lose this', id='only')])
    nb.delete(0)
    assert len(nb) == 1 and nb[0].source == ''
    nb.undo()
    assert len(nb) == 1 and nb[0].id == 'only' and nb[0].source == 'do not lose this'


def test_cell_ranges_move_copy_and_delete_as_single_undoable_operations():
    nb = Notebook(cells=[Cell(source=x) for x in ('a', 'b', 'c', 'd')])
    at = nb.move_many([1, 2], 4)
    assert at == 2 and [c.source for c in nb.cells] == ['a', 'd', 'b', 'c']
    nb.undo(); assert [c.source for c in nb.cells] == ['a', 'b', 'c', 'd']
    copied = [nb.detached(1), nb.detached(2)]
    pasted = nb.paste_many(4, copied)
    assert [c.source for c in pasted] == ['b', 'c'] and len({c.id for c in nb.cells}) == len(nb.cells)
    nb.undo(); assert len(nb.cells) == 4
    nb.delete_many([1, 2]); assert [c.source for c in nb.cells] == ['a', 'd']
    nb.undo(); assert [c.source for c in nb.cells] == ['a', 'b', 'c', 'd']


def test_duplicate_cell_keeps_content_and_output_but_gets_a_fresh_identity():
    nb = Notebook([Cell(source='x = 1', id='original', execution_count=3,
                        outputs=[{'output_type': 'stream', 'name': 'stdout', 'text': 'one\n'}])])
    duplicate = nb.duplicate(0)
    assert [c.source for c in nb.cells] == ['x = 1', 'x = 1']
    assert duplicate.outputs == nb[0].outputs and duplicate.outputs is not nb[0].outputs
    assert duplicate.id != nb[0].id and not duplicate.running and nb.dirty


def test_detached_cell_can_be_pasted_between_notebooks_repeatedly():
    source = Notebook([Cell(source='answer = 42', cell_type='code', id='source-cell',
                            execution_count=2, outputs=[{'output_type': 'stream', 'text': '42\n'}])])
    target = Notebook([Cell(source='# destination', cell_type='markdown', id='destination')])
    clipboard = source.detached(0)
    first = target.paste(1, clipboard)
    second = target.paste(2, clipboard)
    assert [c.source for c in target.cells] == ['# destination', 'answer = 42', 'answer = 42']
    assert first.outputs == source[0].outputs and first.outputs is not source[0].outputs
    assert len({source[0].id, clipboard.id, first.id, second.id}) == 4
    assert not first.running and not first.fresh and target.dirty


def test_moving_a_cell_multiple_places_preserves_the_order_between():
    from leela.blocks.nb.nb import Cell, Notebook
    nb = Notebook([Cell(source=x) for x in 'abcd'])
    assert nb.move(0, 2) == 2
    assert [c.source for c in nb.cells] == ['b', 'c', 'a', 'd']
    assert nb.dirty


# -- diffable source -------------------------------------------------------
def test_source_text_marks_cells_by_type_and_id():
    "So a diff hunk can be traced back to the cell it came from."
    txt = dialog().source_text()
    assert '# %% markdown m1' in txt and '# %% code c1' in txt and '# %% prompt p1' in txt


def test_source_text_leaves_outputs_out():
    "It is a view of what was written, not of what was produced."
    assert 'dtype: int64' not in dialog().source_text()


# ---------------------------------------------------------------------------
# approval and compaction cells
# ---------------------------------------------------------------------------
def test_an_approval_cell_round_trips_as_plain_markdown(tmp_path):
    """The exchange between the agent and the person is saved with the work.

    Written as markdown carrying its structure in metadata -- the same trick a prompt cell
    uses, and for the same reason: the file stays valid nbformat and legible in plain
    Jupyter, where the negotiation simply reads as prose.
    """
    from leela.blocks.nb.nb import Cell, Notebook
    nb = Notebook([Cell(source='fix the bug', cell_type='prompt')])
    c = Cell(source='**🔐 approval needed — `edit_file`**', cell_type='markdown')
    c.approval = {'kind': 'approval', 'id': 'ab12', 'tool': 'edit_file', 'state': 'refused'}
    nb.insert(1, c)
    p = tmp_path/'d.ipynb'
    nb.save(p)

    import nbformat
    nbformat.validate(nbformat.read(str(p), as_version=4))

    back = Notebook.load(p)
    assert back[1].cell_type == 'markdown'
    assert back[1].is_approval
    assert back[1].approval['tool'] == 'edit_file'
    assert back[1].approval['state'] == 'refused'
    assert not back[0].is_approval


def test_cell_context_policy_survives_the_notebook_round_trip(tmp_path):
    nb = dialog()
    nb[0].context_mode, nb[1].context_mode = 'keep', 'discard'
    nb.save(p := tmp_path/'d.ipynb')
    back = Notebook.load(p)
    assert [back[0].context_mode, back[1].context_mode, back[2].context_mode] == ['keep', 'discard', 'auto']


def test_ordinary_cells_carry_no_approval_metadata(tmp_path):
    from leela.blocks.nb.nb import Cell, Notebook
    nb = Notebook([Cell(source='x = 1')])
    nb.save(p := tmp_path/'d.ipynb')
    assert Notebook.load(p)[0].approval is None
    assert 'leela' not in json.loads(p.read_text())['cells'][0]['metadata']
