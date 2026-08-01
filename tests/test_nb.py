"""Tests for the notebook document, and for the prompt cell in particular.

Two things here are worth guarding closely. The first is that a prompt cell survives a
round trip through a file format that has no such cell type -- it is written as markdown
with its answer in metadata, and if either half of that drifts the answer is silently
lost. The second is `context()`, which decides what the assistant is told; too little and
it answers the wrong question, too much and it burns the window restating what it was
told a moment ago.
"""

import json

import pytest

from leela.nb import CELL_TYPES, Cell, Notebook


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


# -- cell types ------------------------------------------------------------
def test_cycling_visits_every_type():
    nb = Notebook([Cell(source='x')])
    assert [nb.cycle_type(0).cell_type for _ in CELL_TYPES] == ['markdown', 'prompt', 'code']


def test_changing_type_discards_the_answer():
    "A prompt turned into prose is no longer an answered question."
    nb = dialog()
    assert nb.set_type(2, 'markdown').reply == ''


# -- context ---------------------------------------------------------------
def test_context_carries_code_output_and_prose():
    ctx = dialog().context(2)
    assert '<note>' in ctx and '## Loading' in ctx
    assert '<code id="c1">' in ctx and 'df = load()' in ctx
    assert '<output>' in ctx and 'dtype: int64' in ctx


def test_context_starts_after_the_last_answered_prompt():
    """The assistant keeps one conversation, so the earlier stretch has already been sent.

    Re-sending it would burn the window restating what the model was just told.
    """
    nb = dialog()
    assert nb.prompt_start(4) == 3
    ctx = nb.context(4, since=nb.prompt_start(4))
    assert 'df.mean()' in ctx
    assert '## Loading' not in ctx and 'why is the sum 6?' not in ctx


def test_an_earlier_prompt_reads_from_the_top():
    nb = dialog()
    assert nb.prompt_start(2) == 0


def test_context_includes_earlier_questions_and_answers():
    ctx = dialog().context(4, since=0)
    assert '<asked>' in ctx and 'why is the sum 6?' in ctx
    assert '<answered>' in ctx and 'Because 1+2+3 = 6.' in ctx


def test_context_clips_a_runaway_output():
    "One `df.describe()` can be thousands of tokens, so outputs are clipped per cell."
    assert len(dialog().context(4, since=0, out_chars=5)) < len(dialog().context(4, since=0))


def test_context_drops_the_front_when_too_long():
    "The cell just above the question is the one it is most likely about, so the tail is kept."
    ctx = dialog().context(4, since=0, max_chars=40)
    assert ctx.startswith('…')
    assert 'df.mean()' in ctx


def test_context_of_the_first_cell_is_empty():
    assert dialog().context(0) == ''


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
    from leela.nb import Cell, Notebook
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


def test_ordinary_cells_carry_no_approval_metadata(tmp_path):
    from leela.nb import Cell, Notebook
    nb = Notebook([Cell(source='x = 1')])
    nb.save(p := tmp_path/'d.ipynb')
    assert Notebook.load(p)[0].approval is None
    assert 'leela' not in json.loads(p.read_text())['cells'][0]['metadata']
