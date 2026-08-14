"The notebook document: cells, outputs, images, diagnostics and languages."

import asyncio
import json
import pytest
from leela.blocks.nb.nb import CELL_TYPES, Cell, Notebook
import sys
from fastcore.all import Path
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.fs.app import SERVED_TYPES
from leela.workspace import IMAGE_EXTS, Tab, Workspace
ROOT = Path(__file__).resolve().parents[1]
from pathlib import Path
from leela.app import _python_diagnostics, ide_app
from leela.workspace import Workspace
from leela.blocks.fs.fs import lang_for
from tests.assets import EDITOR, JS as CLIENT

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
    "Creating `name.ipynb` through a generic file action used to open a JSONDecodeError."
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
    assert back[1].text.startswith('a    6')

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

def test_cycling_visits_every_type():
    nb = Notebook([Cell(source='x')])
    assert [nb.cycle_type(0).cell_type for _ in CELL_TYPES] == ['markdown', 'prompt', 'code']

def test_changing_type_discards_the_answer():
    "A prompt turned into prose is no longer an answered question."
    nb = dialog()
    assert nb.set_type(2, 'markdown').reply == ''

def test_context_carries_complete_cell_details_output_and_prose():
    ctx = dialog().context(2)
    assert '<cell id="m1" type="markdown" compact="auto">' in ctx and '## Loading' in ctx
    assert '<cell id="c1" type="code" compact="auto">' in ctx and 'df = load()' in ctx
    assert '<output>' in ctx and 'dtype: int64' in ctx

def test_every_cell_above_a_prompt_is_fresh_context():
    "The notebook, not stale backend history, is the inline agent's source of truth."
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

def test_source_text_marks_cells_by_type_and_id():
    "So a diff hunk can be traced back to the cell it came from."
    txt = dialog().source_text()
    assert '# %% markdown m1' in txt and '# %% code c1' in txt and '# %% prompt p1' in txt

def test_source_text_leaves_outputs_out():
    "It is a view of what was written, not of what was produced."
    assert 'dtype: int64' not in dialog().source_text()

def test_an_approval_cell_round_trips_as_plain_markdown(tmp_path):
    "The exchange between the agent and the person is saved with the work."
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

def notebook_json():
    "A notebook on disk, written the way nbformat writes one: a JSON string per source line."
    nb = Notebook([Cell(source='## Loading', cell_type='markdown', id='m1'),
                   Cell(source='import os\n\ndef alpha(x):\n    return x', id='c1'),
                   Cell(source='class Beta:\n    def gamma(self):\n        return alpha(1)', id='c2')])
    return nb

def test_a_cells_lines_are_found_in_the_file_that_holds_them(tmp_path):
    "The scan behind notebook blame and notebook search: which file lines are this cell's source."
    from leela.blocks.nb.nb import cell_lines, read_cells, source_spans
    notebook_json().save(p := tmp_path/'d.ipynb')
    text = p.read_text()
    cells = read_cells(text)
    spans = source_spans(text, cells)
    lines = text.splitlines()
    for cell, span in zip(cells, spans):
        held = [lines[n - 1] for n in range(span[0], span[1] + 1)]
        for source, raw in zip(cell_lines(cell), held):
            assert json.dumps(source) in raw, 'the span holds exactly this cell source line'

def test_a_file_line_maps_back_to_the_cell_and_the_line_inside_it(tmp_path):
    "The direction search needs: ripgrep reports a line of JSON and a reader needs a cell."
    from leela.blocks.nb.nb import cell_at
    notebook_json().save(p := tmp_path/'d.ipynb')
    text = p.read_text()
    line = next(i for i, raw in enumerate(text.splitlines(), 1) if 'def gamma' in raw)
    at = cell_at(text, line)
    assert (at['id'], at['index'], at['line']) == ('c2', 2, 2)
    assert at['file_line'] == line
    assert cell_at(text, 1) is None, 'a line of JSON that is nobody\'s source belongs to no cell'

def test_a_notebook_that_cannot_be_read_is_reported_rather_than_guessed_at(tmp_path):
    from leela.blocks.nb.nb import cell_at, cell_of, read_cells
    assert read_cells('not json at all') is None
    assert read_cells('{"nbformat": 4}') is None
    assert cell_at('not json at all', 3) is None
    notebook_json().save(p := tmp_path/'d.ipynb')
    text = p.read_text()
    assert cell_of(text, 'def gamma')['id'] == 'c2'
    assert cell_of(text, 'return') is None, 'two cells contain it, so neither is the answer'
    assert cell_of(text, 'nothing here') is None

sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder  # noqa: E402

PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4'
                    '890000000a49444154789c6300010000050001' '0d0a2db4' '0000000049454e44ae426082')

def test_every_image_tab_kind_can_actually_be_served():
    "A kind whose bytes `/file/raw` refuses is a tab that opens onto a broken image."
    assert IMAGE_EXTS <= set(SERVED_TYPES), sorted(IMAGE_EXTS - set(SERVED_TYPES))

def test_an_image_path_becomes_an_image_tab_not_a_text_one():
    for ext in sorted(IMAGE_EXTS):
        assert Tab(path=f'/tmp/a{ext}').kind == 'image', ext
        assert Tab(path=f'/tmp/a{ext.upper()}').kind == 'image', 'the extension is not case sensitive'
    assert Tab(path='/tmp/a.py').kind == 'text' and Tab(path='/tmp/a.pdf').kind == 'pdf'

def test_the_tab_payload_carries_no_bytes_and_the_raw_route_serves_them(tmp_path):
    "Base64ing a whole image into every tab switch is what the pdf kind already avoids."
    (tmp_path/'shot.png').write_bytes(PNG)
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        ws.open(tmp_path/'shot.png')
        st = c.get('/tab/state').json()
        assert st['kind'] == 'image' and st['path'].endswith('shot.png')
        assert 'text' not in st and 'cells' not in st
        raw = c.get('/file/raw/shot.png', params={'path': str(tmp_path/'shot.png')})
        assert raw.status_code == 200 and raw.headers['content-type'] == 'image/png'
        assert raw.content == PNG

def test_an_image_tab_is_never_saved_over():
    "`saveTab` writes the editor's buffer; an image tab has none, so it must refuse before that."
    js = builder.OUT.read_text()
    assert "lee.kind === 'pdf' || lee.kind === 'image'" in js
    assert 'function mountImage' in js and "st.kind === 'image'" in js

def test_markdown_figures_are_resolved_against_the_document_not_the_page():
    js = builder.OUT.read_text()
    block = js[js.index('function resolveMarkdownImages'):js.index('function renderMarkdown')]
    assert "/^(https?:|data:|blob:|\\/file\\/raw)/" in block, 'an absolute or already-resolved src is left alone'
    assert "data-md-base" in js, 'the surfaces say which folder the document came from'
    assert "loading = 'lazy'" in block

def test_the_research_space_can_browse_the_vault():
    "The vault beside the web: what you already kept, in the column where sources go."
    js = builder.OUT.read_text()
    block = js[js.index('function researchWorkspace'):js.index('function webSearch')]
    assert 'data-mode="vault"' in block, 'the vault is a research mode'
    assert "elid=researchvault" in block, 'its fragment gets its own id, not the panel\'s'
    assert "activeMode === 'vault'" in block
    assert 'if (!query) return;' in block and block.index("activeMode === 'vault'") < block.index('if (!query) return;')

def test_opening_a_file_recovers_a_tab_bar_a_failed_swap_destroyed():
    "`#tabbar` is an htmx `outerHTML` target for tab select, vault open and every `htmxPost`."
    js = builder.OUT.read_text()
    block = js[js.index('async function leeOpenFile'):js.index('async function leeOpenFile') + 2200]
    assert "$('#header')?.insertBefore(fresh" in block, 'a destroyed tab bar is put back'
    assert "doc.querySelector('.lee-err')?.textContent" in block, 'the server said why; show that'

EDITOR_editor = (ROOT / 'frontend/editor.js').read_text()
PACKAGE = (ROOT / 'frontend/package.json').read_text()

def test_python_compiler_reports_precise_syntax_errors():
    source = 'answer = 1\nif True print(answer)\n'
    diagnostics = _python_diagnostics(source, 'draft.py')
    assert len(diagnostics) == 1
    error = diagnostics[0]
    assert error['severity'] == 'error'
    assert error['source'] == 'Python'
    assert error['code'] == 'SyntaxError'
    assert error['message'] == 'invalid syntax'
    assert source[error['from']:error['to']]
    assert error['from'] >= source.index('if True')

def test_python_compiler_reports_warnings_and_never_executes_source():
    warnings = _python_diagnostics('value is 1\nraise RuntimeError("must not run")\n')
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning['severity'] == 'warning'
    assert warning['code'] == 'SyntaxWarning'
    assert 'Did you mean "=="?' in warning['message']

def test_lint_endpoint_checks_unsaved_python_without_an_external_linter():
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        response = client.post('/lint', json={'lang': 'python', 'code': 'if True print(1)'})
    assert response.status_code == 200
    assert response.json()['diagnostics'][0]['severity'] == 'error'

def test_codemirror_lint_source_covers_errors_warnings_and_readonly_surfaces():
    assert '"@codemirror/lint"' in PACKAGE
    assert 'import {linter, forEachDiagnostic} from "@codemirror/lint"' in EDITOR_editor
    assert 'node.type.isError' in EDITOR_editor
    assert 'severity: "error"' in EDITOR_editor
    assert 'data.diagnostics' in EDITOR_editor
    assert 'readOnly || !lang' in EDITOR_editor
    assert 'return linter(source, {delay: 400})' in EDITOR_editor

def test_common_project_languages_are_detected_from_paths():
    expected = {
        'pyproject.toml': 'toml', 'app.js': 'javascript', 'worker.mjs': 'javascript',
        'view.jsx': 'jsx', 'app.ts': 'typescript', 'view.tsx': 'tsx',
        'config.yaml': 'yaml', 'data.json': 'json', 'settings.jsonc': 'json',
        'main.rs': 'rust', 'main.go': 'go', 'Main.java': 'java', 'lib.cpp': 'cpp',
        'layout.xml': 'xml', 'local.properties': 'properties', 'script.sh': 'bash',
        'Dockerfile': 'bash', 'Cargo.lock': 'toml',
    }
    assert {name: lang_for(name) for name in expected} == expected

def test_codemirror_bundle_declares_every_detected_syntax_family():
    for language in ('toml', 'javascript', 'typescript', 'jsx', 'tsx', 'yaml', 'json',
                     'bash', 'rust', 'go', 'java', 'cpp', 'xml', 'properties'):
        assert language in EDITOR
    assert 'StreamLanguage.define(toml)' in EDITOR
    assert 'StreamLanguage.define(shell)' in EDITOR

def test_tagged_markdown_fences_support_non_python_languages_without_becoming_executable():
    assert "toml: 'toml'" in CLIENT and "yml: 'yaml'" in CLIENT and "jsonc: 'json'" in CLIENT
    assert '!CODE_LANGS[named]' in CLIENT
    assert "python && el.classList.contains('lee-reply')" in CLIENT
