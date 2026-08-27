"The web IDE surface: project tools, movement, tabs, cells and workspaces."

from fasthtml.common import to_xml
from leela.blocks.term.term import TerminalGate
from leela.app import _shell
from leela.workspace import Workspace
from tests.assets import read
from pathlib import Path
from leela.blocks.runtime.kernels import bootstrap_src, project_python
ROOT = Path(__file__).resolve().parents[1]
import json
from starlette.testclient import TestClient
from leela.app import ide_app
import asyncio
import time
from unittest.mock import Mock
import pytest
from leela.blocks.runtime.kernels import RuntimeBroker, KernelPool
from leela.hub import (OPEN_PATH, LoopbackHostGuard, WorkspaceHub, WorkspaceSite,
                       assign_slugs, workspace_slug, workspace_slugs)

def test_the_shell_paints_status_theme_and_layout():
    from leela.app import _asset
    assert _asset('lee-ide.css').startswith('/leestatic/lee-ide.css?v=')
    from leela.core.web import IDE_BUNDLES
    for name in IDE_BUNDLES: assert _asset(name).startswith(f'/leestatic/{name}?v=')


def test_header_leads_with_workspace_branch_and_named_menus_without_starting_a_kernel(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'id="workspacepill"' in html and 'leeWorkspaceMenu(this)' in html
    assert 'id="gitpill"' in html and 'leeBranchMenu(this)' in html
    assert '>File</button>' in html and '>Tools</button>' in html and '>Debug</button>' in html
    assert 'id="themepill"' not in html and 'id="cwdpill"' not in html


def test_every_tab_reports_pending_saving_saved_and_failed_autosave(tmp_path):
    from leela.app import _tab_bar
    p = tmp_path/'notes.py'; p.write_text('answer = 42\n')
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    saved = to_xml(_tab_bar(ws))
    assert 'lee-save-state saved' in saved and 'saved on disk' in saved
    tab.dirty = True
    pending = to_xml(_tab_bar(ws))
    assert 'lee-save-state pending' in pending and 'changes waiting for autosave' in pending

def test_modified_files_and_lines_are_visible_before_opening_source_control(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'id="gitpill"' in html


def test_left_activity_bar_has_a_pycharm_style_file_structure(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'data-left="symbols"' in html and 'id="symbols"' in html


def test_agent_model_and_reasoning_live_below_the_growing_prompt(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert html.index('id="agentprompt"') < html.index('id="agentmodel"')
    assert 'id="agentreasoning"' in html and 'lee-composer-footer' in html


def test_agent_vocabulary_exposes_commands_tools_and_project_skills(tmp_path):
    skill = tmp_path/'.agents/skills/notebook-tests/SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: notebook-tests\ndescription: How this project tests notebooks.\n---\n\nDo it carefully.\n')
    with TestClient(ide_app(Workspace(roots=[tmp_path], model='sonnet'))) as client:
        vocabulary = client.get('/agent/commands').json()
    assert {'commands', 'tools', 'skills'} <= vocabulary.keys()
    assert any(x['name'] == 'research' for x in vocabulary['tools'])
    assert any(x['name'] == 'notebook-tests' for x in vocabulary['skills'])


def test_pyproject_dependencies_get_runtime_version_pills(tmp_path):
    p = tmp_path/'pyproject.toml'
    p.write_text('[project]\nname="demo"\nversion="0.1"\nkeywords=["package-that-does-not-exist"]\n'
                 'dependencies=[\n  "pytest>=1", # a deliberately long comment after the declaration\n]\n'
                 '[project.optional-dependencies]\ndev=["package-that-does-not-exist>=9", "pytest>=1"]\n')
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    with TestClient(ide_app(ws)) as client:
        data = client.get('/editor/packages', params={'path': str(p)}).json()
    rows = {r['name']: r for r in data['packages']}
    assert rows['pytest']['installed'] and rows['pytest']['compatible'] is True
    assert rows['package-that-does-not-exist']['installed'] is None
    assert rows['package-that-does-not-exist']['line'] == 9
    assert len({r['column'] for r in data['packages'] if r['line'] == 9}) == 2
    assert data['summary']['missing'] == 1

def test_a_pyproject_is_annotated_from_the_venv_beside_it(tmp_path):
    """One interpreter answered for every open project at once.

    With two checkouts open, the pills on the second one's pyproject were read out of the first
    one's environment, so a checkout holding a newer release of a shared dependency was reported at
    the older one's version. The formatter picked its ruff the same way.
    """
    import os, sys
    roots = []
    for name in ('one', 'two'):
        root = tmp_path/name
        (root/'.venv'/'bin').mkdir(parents=True)
        os.symlink(sys.executable, root/'.venv'/'bin'/'python')
        (root/'pyproject.toml').write_text('[project]\nname="%s"\nversion="0.1"\ndependencies=["pytest>=1"]\n' % name)
        roots.append(root)
    ws = Workspace(roots=roots)
    with TestClient(ide_app(ws)) as client:
        for root in roots:
            d = client.get('/editor/packages', params={'path': str(root/'pyproject.toml')}).json()
            assert d['summary']['python'] == str(root/'.venv'/'bin'/'python'), \
                "the pills came from another project's environment"


def test_workspace_panes_can_minimise_and_restore_independently(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert html.count('lee-pane-min') >= 3 and html.count('lee-pane-restore') == 3
    for label, side in (('files', 'left'), ('tools', 'right'), ('terminal / exec', 'bottom')):
        assert f'>{label}</button>' in html and f'leePane("{side}", true)' in html


def test_the_file_and_agent_panes_can_be_pinned_or_left_to_auto_close(tmp_path):
    "Unpinned, a pane closes when you work elsewhere; pinned is the default and the old behaviour."
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    for pane in ('left', 'right'):
        assert f'data-pane-pin="{pane}"' in html, pane
        assert f'leePinPane(&quot;{pane}&quot;)' in html or f"leePinPane(\"{pane}\")" in html, pane
    assert html.count('lee-pane-min') >= 4, 'the file pane gained its own minimise'

def test_git_is_a_first_class_vertical_project_tab(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'lee-activity' in html and 'data-left="files"' in html and 'data-left="git"' in html
    assert 'id="gitpanel"' in html and 'lee-source-control' in html


def test_blame_is_reachable_from_anywhere_and_groups_a_notebook_into_cells():
    "Two separate things it needs to be useful."
    assert "Key('git_blame'" in read('leela/core/keys.py'), 'so it has a chord and a palette entry'
    assert read('leela/blocks/keys/menus.py').count("S('git_blame')") >= 4, 'file, editor, cell and tab'


def test_panels_refresh_themselves_and_keep_secrets_server_side():
    assert 'def pipeline_socket(' in read('leela/core/web.py')
    first = workspace_slug('My Project')
    second = workspace_slug('My Project', [first])
    assert first == 'my-project' and second == 'my-project-2'

def test_the_tree_hides_dotfiles_until_the_toggle_asks_for_them(tmp_path):
    "`.gitignore` is a file you edit; `.venv` is not, and one control must not conflate them."
    (tmp_path/'.gitignore').write_text('build/\n')
    (tmp_path/'.venv').mkdir(); (tmp_path/'sub').mkdir()
    (tmp_path/'app.py').write_text('x = 1\n')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        ask = lambda **kw: client.get('/tree', params={'path': str(tmp_path), **kw},
                                      headers={'HX-Request': 'true'}).text
        plain, shown = ask(), ask(hidden=True)
    assert '.gitignore' not in plain and '.gitignore' in shown
    assert '.venv' not in plain and '.venv' not in shown, 'the skip list is not what this toggles'
    assert 'hidden=1' in shown and 'hidden=1' not in plain, 'a folder opened from here keeps showing them'
    assert "Btn('show_hidden'" in read('leela/core/ui.py'), 'and the files bar can turn it on'

def test_a_window_is_pointed_at_the_host_the_server_will_answer_to(tmp_path):
    "`serve_ide` slugs resolved roots, so a symlinked folder must not be slugged by its link."
    from leela.hub import workspace_urls
    (tmp_path/'real-name').mkdir()
    (tmp_path/'link').symlink_to(tmp_path/'real-name')
    assert workspace_urls([tmp_path/'link'], 5001) == ['http://real-name.localhost:5001/']


def test_every_git_failure_reaches_the_log_not_only_the_status_line():
    "The detail of a refusal is the point of it, and a toast cannot hold it."
    for name in ('git/cwd', 'git/state', 'git/views', 'git/conflictfiles', 'git/branchbar',
                 'git/panel', 'editor/gutter'):
        assert "status(e.message || String(e), 'err')" not in read(f'leela/blocks/{name}.js'), \
            f'{name} reports a failure without logging its detail'


def test_a_pdf_opens_in_the_browsers_own_viewer(tmp_path):
    "We are in a browser, so the viewer already exists -- the feature is handing the bytes over."
    pdf = tmp_path/'paper.pdf'
    pdf.write_bytes(b'%PDF-1.4\ntrailer\n%%EOF\n')
    ws = Workspace(roots=[tmp_path])
    tab = ws.open(pdf)
    assert tab.kind == 'pdf' and tab.private_kernel is False
    with TestClient(ide_app(ws)) as c:
        st = c.get('/tab/state', params={'path': str(pdf)}).json()
        assert st['kind'] == 'pdf' and 'text' not in st, 'the bytes are fetched by the viewer, not inlined'
        r = c.get('/file/raw', params={'path': str(pdf)})
        assert r.status_code == 200 and r.content.startswith(b'%PDF')
        assert r.headers['content-type'] == 'application/pdf'
        assert 'inline' in r.headers['content-disposition'], 'inline, or the browser downloads it'
        assert r.headers['x-content-type-options'] == 'nosniff'
        down = c.get('/file/raw', params={'path': str(pdf), 'download': 'true'})
        assert 'attachment' in down.headers['content-disposition']
        (tmp_path/'x.py').write_text('x = 1\n')
        assert c.get('/file/raw', params={'path': str(tmp_path/'x.py')}).json()['error']
        assert c.get('/file/raw', params={'path': '/etc/passwd'}).json()['error']


def test_a_markdown_file_gets_the_same_change_hunks_as_code(tmp_path):
    "The gutter popup is language-agnostic; this pins that markdown really does feed it."
    import subprocess
    def git(*a): subprocess.run(['git', *a], cwd=tmp_path, check=True, capture_output=True)
    git('init', '-q', '-b', 'main', '.')
    git('config', 'user.email', 'tests@leela.local'); git('config', 'user.name', 'Leela tests')
    (tmp_path/'readme.md').write_text('# Title\n\nfirst para\n')
    git('add', '.'); git('commit', '-qm', 'init')
    (tmp_path/'readme.md').write_text('# Title\n\nfirst para edited\n')
    from leela.blocks.git.git import GitRepo
    fc = GitRepo.at(tmp_path).file_changes('readme.md')
    assert fc['ranges'] == [{'from': 3, 'to': 3, 'kind': 'modified'}]
    hunk = fc['hunks'][0]
    assert hunk['old'] == 'first para\n' and 'first para edited' in hunk['new']
    assert hunk['patch'].startswith('diff --git'), 'so revert and commit-this-change work on prose too'


def _md_render(text):
    "One document through the real renderer, exactly as the browser asks for it."
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        r = client.post('/markdown/render', json={'text': text, 'allow_raw': False})
    assert r.status_code == 200, r.text
    return r.json()['html']

def _md_carriers(html):
    "The top-level nodes the browser counts as block carriers, mirroring `markdownCarriers`."
    import fast5ever
    out = []
    for n in fast5ever.parse_fragment(html).children:
        if isinstance(n, fast5ever.Text): continue
        if isinstance(n, fast5ever.Element) and n.name == 'section' \
           and 'footnotes' in (n.attrs.get('class') or ''): continue
        out.append(n.name)
    return out

def _md_align(html, blocks):
    "`alignMarkdownBlocks`, in Python: the pairs, or None where the browser draws nothing."
    nodes, pairs, at = _md_carriers(html), [], 0
    for b in blocks:
        if b.get('status') == 'removed': pairs.append((b, None)); continue
        if not b['renders']: continue
        if at >= len(nodes): return None
        node = nodes[at]; at += 1
        if b['tags'] and node not in b['tags']: return None
        pairs.append((b, node))
    return pairs if at == len(nodes) else None

README = '''# rishi

<!-- a note to the reader -->

Prose with `code`, a [link][home] and a footnote[^1].

```bash
uv add rishi
```

## Install

- one
- two

| a | b |
|---|---|
| 1 | 2 |

> a quotation

---

![a picture](p.png)

[home]: https://example.com
[^1]: the note
'''

def test_every_markdown_block_maps_to_the_element_it_rendered_as():
    from leela.core.text import md_blocks
    blocks = md_blocks(README)
    pairs = _md_align(_md_render(README), blocks)
    assert pairs is not None, 'a rendered diff of an ordinary README can be marked'
    assert [n for _, n in pairs] == ['h1', '#comment', 'p', 'pre', 'h2', 'ul', 'table',
                                     'blockquote', 'hr', 'figure']
    assert [b['type'] for b in blocks if not b['renders']] == ['link_ref', 'footnote_def']
    fence = next(b for b in blocks if b['type'] == 'code_block')
    assert (fence['from'], fence['to']) == (7, 9) and fence['code'] == 'uv add rishi\n'

def test_markdown_diffs_map_blocks_onto_the_elements_they_rendered():
    from leela.core.text import md_blocks
    doc = 'para one\n\n<p>a</p><p>b</p>\n\n## heading\n'
    assert _md_align(_md_render(doc), md_blocks(doc)) is None
    assert _md_align('<p>only</p>', md_blocks('para\n\npara two\n')) is None, 'a block with no element'
    assert _md_align('<p>a</p><p>b</p>', md_blocks('para\n')) is None, 'an element no block claimed'


def test_a_markdown_diff_pairs_blocks_and_refuses_to_pair_across_types():
    from leela.core.text import md_block_diff
    old = '# t\n\nold prose\n\n```sh\nold cmd\n```\n\ngone entirely\n'
    new = '# t\n\nnew prose\n\n```sh\nnew cmd\n```\n\n## Install\n\nfresh\n'
    d = md_block_diff(old, new)
    rows = [(r['status'], r['type']) for r in d['blocks']]
    assert rows[:3] == [('equal', 'heading'), ('modified', 'paragraph'), ('modified', 'code_block')]
    assert ('modified', 'heading') not in rows, 'a paragraph did not become a heading'
    assert ('added', 'heading') in rows
    assert (d['blocks'][-1]['status'], d['blocks'][-1]['old']) == ('modified', 'gone entirely')
    fence = next(r for r in d['blocks'] if r['type'] == 'code_block')
    assert fence['old_code'] == 'old cmd\n' and fence['code'] == 'new cmd\n'
    assert d['changed'] and (d['added'], d['removed']) == (5, 3)

def test_the_diff_records_still_line_up_with_the_document_being_read():
    "The records the rendered view actually receives, against the rendering it actually gets."
    from leela.core.text import md_block_diff
    old = README.replace('## Install', 'A paragraph that this change deletes.\n\n## Setup')
    d = md_block_diff(old, README)
    pairs = _md_align(_md_render(README), d['blocks'])
    assert pairs is not None
    assert [n for _, n in pairs if n] == ['h1', '#comment', 'p', 'pre', 'h2', 'ul', 'table',
                                          'blockquote', 'hr', 'figure']
    heading = next(b for b, n in pairs if n == 'h2')
    assert heading['status'] == 'modified' and heading['old'] == '## Setup'
    gone = [b for b in d['blocks'] if b['status'] == 'removed']
    assert [b['source'] for b in gone] == ['A paragraph that this change deletes.']

def test_a_line_range_from_git_lands_on_the_block_that_holds_it():
    from leela.core.text import md_blocks, md_change_kinds
    blocks = md_blocks('# t\n\nprose\n\n```sh\na\nb\n```\n')
    kinds = md_change_kinds(blocks, [{'from': 3, 'to': 3, 'kind': 'added'},
                                     {'from': 6, 'to': 6, 'kind': 'deleted'}])
    assert kinds == [None, 'added', 'removed']
    both = md_change_kinds(blocks, [{'from': 1, 'to': 8, 'kind': 'modified'}])
    assert both == ['modified', 'modified', 'modified']
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        got = client.post('/markdown/blocks', json={'text': '# t\n\nprose\n',
                                                    'ranges': [{'from': 3, 'to': 3, 'kind': 'added'}]}).json()
        diff = client.post('/markdown/diff', json={'left': '# t\n', 'right': '# t\n\nnew\n'}).json()
    assert got['kinds'] == [None, 'added'] and got['blocks'][1]['tags'] == ['p']
    assert [b['status'] for b in diff['blocks']] == ['equal', 'added']


def test_a_pdf_is_served_under_its_own_name_and_fills_the_pane(tmp_path):
    'Two things were wrong with the viewer: it was short, and every document was called "raw".'
    pdf = tmp_path/'2306.14881.pdf'; pdf.write_bytes(b'%PDF-1.4\n%%EOF\n')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as c:
        named = c.get('/file/raw/2306.14881.pdf', params={'path': str(pdf)})
        assert named.status_code == 200 and named.headers['content-type'] == 'application/pdf'
        assert 'inline; filename="2306.14881.pdf"' in named.headers['content-disposition']
        assert c.get('/file/raw', params={'path': str(pdf)}).status_code == 200, 'both spellings'
        assert c.get('/leestatic/lee-ide.css').status_code == 200
        assert c.get('/file/raw/passwd.pdf', params={'path': '/etc/passwd'}).status_code == 400


def test_the_compressor_leaves_every_event_stream_alone():
    "GZip went on the app for the cold load. Buffering the streams would have paid for it."
    from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES
    assert 'text/event-stream' in DEFAULT_EXCLUDED_CONTENT_TYPES, \
        'below starlette 1.6 this list has no streams in it and /fs/events arrives at the end'


def _fake_venv(root):
    py = root/'.venv'/'bin'/'python'
    py.parent.mkdir(parents=True)
    py.write_text('')
    return py

def test_project_venv_is_the_default_runtime_without_moving_leela(tmp_path):
    py = _fake_venv(tmp_path)
    assert project_python([tmp_path]) == str(py)
    ws = Workspace(roots=[tmp_path])
    assert ws.pool.default_python == str(py)

def test_adding_the_first_folder_adopts_its_venv(tmp_path):
    py = _fake_venv(tmp_path)
    ws = Workspace(roots=[])
    ws.add_root(tmp_path)
    assert ws.pool.default_python == str(py)


def test_variables_and_runtimes_follow_the_active_tab():
    src = bootstrap_src()
    assert 'sys.path.append(_p)' in src
    assert 'import dhrishti.serving as ls' in src
    assert src.index('sys.path.append(_p)') < src.index('import dhrishti.serving as ls')
    from leela.app import _vars_panel
    html = str(_vars_panel(Workspace(roots=[])))
    assert '>agent</button>' in html and 'leeScope("agent")' in html


def test_one_keyboard_router_reaches_every_panel():
    from leela.core.keys import lookup
    for action, panel in (('panel_git', 'git'), ('panel_releases', 'releases'), ('panel_deploys', 'deploys')):
        key = lookup(action)
        assert key.scope == 'global' and key.keys, f'{action} is bound'


def test_editor_extensions_are_live_preferences():
    assert (ROOT/'leela/vendor/lee-cm6.js').stat().st_size > 100_000


def test_editor_toolbar_keeps_contextual_actions_and_moves_the_rest_to_kebab():
    from leela.app import _toolbar
    html = to_xml(_toolbar())
    assert 'data-action="run_cell"' in html and 'data-action="run_file"' in html
    assert 'data-action="run_all"' not in html
    assert 'leeEditorMenu(this)' in html and 'more editor actions' in html

def test_agent_teleprompter_exposes_control_modes_and_editable_tool_calls():
    from leela.app import _agent_panel
    html = to_xml(_agent_panel(Workspace(roots=[])))
    assert 'id="agentcontrol"' in html
    assert 'id="agenttoolbudget"' in html and 'id="agentbudgetstatus"' in html
    assert all(f'value="{mode}"' in html for mode in ('autopilot', 'guided', 'directed'))


def test_the_agent_panel_streams_steps_approvals_and_usage():
    from leela.app import _agent_panel
    html=str(_agent_panel(Workspace(roots=[])))
    ws = Workspace(roots=[])
    assert ws.inline_model == 'gpt-mini'
    assert ws.completion_model == 'gpt-4.1'
    assert ws.ai.routing.name_for('completion') == 'gpt-4.1'


def test_tool_schema_only_marks_read_only_calls_as_rerunnable(tmp_path):
    from leela.blocks.agent.turns import tool_schemas as _tool_schemas
    rows = {row['name']: row for row in _tool_schemas(Workspace(roots=[tmp_path]).ai)}
    assert rows['run_shell']['changes_state'] and not rows['run_shell']['retryable']
    assert not rows['view_file']['changes_state'] and rows['view_file']['retryable']


def test_agent_control_route_changes_checkpoint_policy_without_starting_a_model(tmp_path):
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/agent/control', json={'control': 'directed'})
        bad = client.post('/agent/control', json={'control': 'reckless'})
        # read inside: leaving the client ends the server's lifespan, which ends the session
        assert ws.approvals.control == 'directed'
    body = r.json()
    assert body['ok'] and body['control'] == 'directed'
    assert body['thread'], 'and it says which conversation the policy was set on'
    assert bad.status_code == 400

def test_agent_and_variables_share_the_right_tabs_while_exec_and_terminal_share_the_bottom():
    html = to_xml(_shell(Workspace(roots=[]), TerminalGate()))
    assert 'lee-righttabs' in html and 'data-right="agent"' in html and 'data-right="vars"' in html
    assert 'lee-docktabs' in html and 'data-dock="exec"' in html and 'data-dock="term"' in html


def test_screen_capture_route_rejects_oversized_payloads_before_decoding(tmp_path):
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        response = client.post('/screen', json={'data_url': 'data:image/png;base64,' + 'A' * 12_000_001})
    assert response.status_code == 413
    assert 'larger than 9 MB' in response.json()['error']


def test_one_static_prefix_serves_both_the_authored_and_vendored_asset_trees(tmp_path):
    "`/leestatic` spans `leela/static` and `leela/vendor` as if they were one folder."
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        authored = client.get('/leestatic/lee-ide.css')
        vendored = client.get('/leestatic/lee-cm6.js')
        font = client.get('/leestatic/fonts/jetbrains-mono-latin-wght-normal.woff2')
        missing = client.get('/leestatic/no-such-asset.js')
    assert authored.status_code == vendored.status_code == font.status_code == 200
    assert b'@font-face' in authored.content and b'/leestatic/fonts/' in authored.content
    assert missing.status_code == 404


def test_selection_help_uses_summary_and_completion_jobs_without_editing(tmp_path, monkeypatch):
    ws = Workspace(roots=[tmp_path])
    calls = []
    class FakeAI:
        note = ''
        routing = type('Routing', (), {'name_for': lambda self, job: 'fake-' + job})()
        def summarise(self, text, sp): calls.append(('summary', text, sp)); return 'short summary'
        def oneshot(self, prompt, sp, job, max_tokens): calls.append((job, prompt, sp)); return 'rewritten text'
    ws._ai = FakeAI()
    with TestClient(ide_app(ws)) as client:
        summary = client.post('/complete/selection', json={'text': 'long source', 'mode': 'summary'}).json()
        rewrite = client.post('/complete/selection', json={'text': 'rough source', 'mode': 'instruction',
                                                            'instruction': 'make clearer', 'lang': 'markdown'}).json()
    assert summary['text'] == 'short summary' and summary['model'] == 'fake-summary'
    assert rewrite['text'] == 'rewritten text' and rewrite['model'] == 'fake-completion'
    assert [c[0] for c in calls] == ['summary', 'completion']

def test_untrusted_markdown_cannot_execute_raw_html(tmp_path):
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        raw = '```{=html}\n<img src=x onerror=alert(1)>\n```'
        safe = client.post('/markdown/render', json={'text': raw, 'allow_raw': False}).json()['html']
        trusted = client.post('/markdown/render', json={'text': raw, 'allow_raw': True}).json()['html']
    assert 'onerror=' not in safe and 'language-html' in safe
    assert 'onerror=' in trusted


def test_model_discovery_does_not_block_shell_render_or_editor_mount():
    from leela.app import _agent_panel
    html = str(_agent_panel(Workspace(roots=[])))
    assert html.count('loading…') == 3


def test_terminal_bundle_loads_only_when_the_terminal_opens():
    from leela.app import _asset, _shell
    html = str(_shell(Workspace(roots=[]), TerminalGate()))
    assert f'<script src="{_asset("lee-term.js")}">' not in html


def test_mdhtml_rendering_is_paste_safe_and_reports_unclosed_constructs():
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        response = client.post('/markdown/render', json={
            'text': '<style>body{display:none}</style>\n\n<script>alert(1)</script>\n\n# visible'})
        assert response.status_code == 200
        html = response.json()['html']
        assert '&lt;style&gt;' in html and '&lt;script&gt;' in html
        assert '<style>' not in html and '<script>' not in html
        assert '<h1>visible</h1>' in html

def test_mdhtml_keeps_explicit_html_passthrough_deliberate():
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        response = client.post('/markdown/render', json={'text': '```{=html}\n<kbd>explicit</kbd>\n```'})
        assert response.status_code == 200
        assert '<kbd>explicit</kbd>' in response.json()['html']


def test_history_groups_turns_by_context_session_without_rendering_every_turn():
    from leela.blocks.agent.turns import history_sessions as _history_sessions
    turns = [
        {'session': 'agent-a', 'at': 10, 'prompt': 'one'},
        {'session': 'agent-a', 'at': 20, 'prompt': 'two'},
        {'session': 'agent-b', 'at': 30, 'prompt': 'three'},
    ]
    groups = _history_sessions(turns, [{'id': 'agent-a', 'code': 4}])
    assert [g['id'] for g in groups] == ['agent-b', 'agent-a']
    assert groups[0]['models'] == [] and groups[1]['models'] == []
    assert [x['prompt'] for x in groups[1]['turns']] == ['one', 'two']
    assert groups[1]['context_continues'] and groups[1]['code'] == 4

def test_resuming_a_history_session_puts_its_turns_back_into_the_model_context(tmp_path):
    "History showed the turns and left the model with none of them."
    ws = Workspace(roots=[tmp_path])
    model = ws.ai.model.name
    turns = [{'session': 'agent-a', 'at': 1, 'model': model, 'prompt': 'remember cedar', 'reply': 'noted'},
             {'session': 'agent-a', 'at': 2, 'model': model, 'prompt': 'what was it?', 'reply': 'cedar'}]
    # a resumed thread builds its own assistant and reads the log, so the session has to be in it
    import json as _json
    path = ws.ai.history_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(_json.dumps(t) for t in turns) + '\n')
    ws.ai.history = list(turns)
    with TestClient(ide_app(ws)) as client:
        d = client.post('/agent/resume', json={'session': 'agent-a'}).json()
        missing = client.post('/agent/resume', json={'session': 'legacy-1'})
        # read inside: leaving the client ends the server's lifespan, which ends the session
        assert ws.ai.session_id == 'agent-a'
        assert ws.ai.backend._resume_hist[-1] == {'role': 'assistant', 'content': 'cedar'}
    assert d['session'] == 'agent-a' and [t['prompt'] for t in d['turns']] == ['remember cedar', 'what was it?']
    assert missing.status_code == 400

def test_routing_popover_closes_on_outside_click_and_escape():
    from leela.app import _agent_panel
    html = str(_agent_panel(Workspace(roots=[])))
    assert 'lee-dismissable' in html

def test_agent_pane_has_model_history_and_expand_controls():
    from leela.app import _agent_panel
    html = str(_agent_panel(Workspace(roots=[])))
    assert 'agentmodel' in html and 'leeAgentModel' in html
    assert 'localmultimodal' in html and 'leeLocalMultimodal' in html
    assert 'workspace-repo-writes' in html and 'leeWorkspaceRepoWrites' in html
    assert 'leeAgentHistory' in html and 'leeAgentExpand' in html
    assert html.count('>transcript</button>') == 0
    assert 'id="agentprompt"' in html and '<textarea' in html

def test_agent_state_refresh_uses_current_project_evidence(tmp_path):
    from leela.blocks.agent.turns import project_state_context as _project_state_context
    (tmp_path/'pyproject.toml').write_text('[project]\nname = "current-code"\n')
    (tmp_path/'module.py').write_text('def current_api():\n    return 1\n')
    context = _project_state_context(Workspace(roots=[tmp_path]))
    assert 'pyproject.toml' in context and 'module.py' in context and 'current-code' in context


def test_model_picker_shows_older_models_by_default(monkeypatch):
    from leela.agent import core as models
    from leela.app import _agent_panel, ide_app
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(models, '_oai_cache', (float('inf'), ['gpt-4.1', 'gpt-5.6-luna']))
    ws = Workspace(roots=[])
    assert 'id="legacymodels"' in str(_agent_panel(ws)) and 'checked' in str(_agent_panel(ws))
    with TestClient(ide_app(ws)) as client:
        values = {row['value'] for row in client.get('/agent/models').json()['models']}
    assert 'openai/gpt-4.1' in values

def test_model_selector_endpoint_exposes_sources_not_secrets(monkeypatch):
    from leela.agent import core as models
    monkeypatch.setenv('OPENAI_API_KEY', 'top-secret')
    monkeypatch.setattr(models, '_oai_cache', (float('inf'), ['gpt-5.4']))
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        data = client.get('/agent/models').json()
    assert any(m['value'] == 'openai/gpt-5.4' for m in data['models'])
    assert data['auth']['openai']['source'] == 'OPENAI_API_KEY'
    assert 'top-secret' not in str(data)

def test_every_model_choice_is_saved_and_restored(tmp_path):
    path = tmp_path/'workspace.json'
    ws = Workspace(roots=[]); ws._state_path = path
    with TestClient(ide_app(ws)) as client:
        assert client.post('/agent/model', json={'target': 'agent', 'model': 'gemma-12b'}).json()['ok']
        assert client.post('/agent/model', json={'target': 'inline', 'model': 'gemma-e2b'}).json()['ok']
        assert client.post('/agent/model', json={'target': 'completion', 'model': 'gemma-e4b'}).json()['ok']
    restored = Workspace.load(path)
    assert (restored.model, restored.inline_model, restored.completion_model) == ('gemma-12b', 'gemma-e2b', 'gemma-e4b')

def test_the_jobs_without_a_control_of_their_own_are_still_choosable(tmp_path):
    "A sub-agent runs on a model somebody chose; the only way to say which was the environment."
    path = tmp_path/'workspace.json'
    ws = Workspace(roots=[]); ws._state_path = path
    with TestClient(ide_app(ws)) as client:
        fresh = client.get('/agent/models').json()['jobs']
        assert 'subagent' in fresh and 'summary' in fresh and ws._ai is None
        assert client.post('/agent/model', json={'target': 'subagent', 'model': 'gemma-e2b'}).json()['ok']
        refused = client.post('/agent/model', json={'target': 'nonsense', 'model': 'gemma-e2b'}).json()
        assert refused['ok'] is False and 'nonsense' in refused['error']
        jobs = client.get('/agent/models').json()['jobs']
    assert jobs['subagent'] == 'gemma-e2b' and 'summary' in jobs, 'reported chosen or not'
    assert Workspace.load(path).job_models == {'subagent': 'gemma-e2b'}


def test_configured_agent_does_not_offer_setup_again():
    from leela.app import _agent_panel
    ws = Workspace(roots=[])
    ws.agent_state_layers['project']['text'] = '# Goal\n\nMaintain this project.'
    html = str(_agent_panel(ws))
    assert 'state active' in html
    assert 'Set up agent state' not in html

def test_agent_memory_api_selects_notes_per_surface_and_rebriefs(tmp_path):
    ws = Workspace(roots=[tmp_path]); ws._state_path = tmp_path/'workspace.json'
    with TestClient(ide_app(ws)) as client:
        saved = client.post('/agent/memory/save', json={
            'title': 'Completion conventions', 'text': 'Prefer pathlib and preserve public APIs.',
            'targets': ['agent', 'inline', 'completion']}).json()
        note_id = saved['id']
        data = client.get('/agent/memory').json()
    assert data['selected'] == {'agent': [note_id], 'inline': [note_id], 'completion': [note_id]}
    assert data['notes'][0]['text'] == 'Prefer pathlib and preserve public APIs.'
    assert 'Prefer pathlib' in ws.ai.system_prompt()
    assert 'Prefer pathlib' in ws.inline_ai.system_prompt()
    assert '<user_memory>' in ws.completer._prompt('x = ', 4, 'python')

def test_local_multimodal_setting_is_persisted_from_the_ui(tmp_path):
    ws = Workspace(roots=[])
    ws._state_path = tmp_path/'workspace.json'
    with TestClient(ide_app(ws)) as client:
        data = client.post('/agent/settings', json={'local_multimodal': True}).json()
    assert data['ok'] and ws.local_multimodal is True
    assert ws._state_path.read_json()['local_multimodal'] is True


def _nb(path, source):
    path.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [{
        'cell_type': 'code', 'source': source, 'metadata': {}, 'outputs': [],
        'execution_count': None, 'id': path.stem,
    }]}))

def test_explicit_reload_invalidates_the_notebook_cache_and_reads_agent_changes(tmp_path):
    a = tmp_path/'a.ipynb'; _nb(a, 'value = "before"')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "before"'
        _nb(a, 'value = "agent edit"')
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "before"'
        assert client.post('/tab/reload', json={'path': str(a)}).json()['ok']
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "agent edit"'


def test_browser_watch_detects_an_external_file_write(tmp_path):
    a = tmp_path/'a.py'; a.write_text('before = True\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        before = client.get('/tab/watch').json()
        a.write_text('after = True\n')
        after = client.get('/tab/watch').json()
    assert before['path'] == str(a)
    assert before['disk_version'] != after['disk_version']

def test_same_named_files_in_different_roots_keep_absolute_identity(tmp_path):
    one,two=tmp_path/'ramabana',tmp_path/'rishi';one.mkdir();two.mkdir()
    a,b=one/'00_core.ipynb',two/'00_core.ipynb';_nb(a,'RAMABANA');_nb(b,'RISHI')
    ws=Workspace(roots=[one,two])
    with TestClient(ide_app(ws)) as client:
        client.post('/tab/open',params={'path':str(a)})
        client.post('/tab/open',params={'path':str(b)})
        assert client.get('/tab/state').json()['cells'][0]['source']=='RISHI'
        client.post('/tab/open',params={'path':str(a)})
        assert client.get('/tab/state').json()['cells'][0]['source']=='RAMABANA'
    assert len(ws.tabs)==2 and {t.path for t in ws.tabs}=={str(a.resolve()),str(b.resolve())}
    from leela.app import _tab_bar
    tabs=to_xml(_tab_bar(ws));assert 'ramabana/00_core.ipynb' in tabs and 'rishi/00_core.ipynb' in tabs

def test_split_state_reads_an_inactive_file_without_changing_active_tab(tmp_path):
    a,b=tmp_path/'a.py',tmp_path/'b.py';a.write_text('A');b.write_text('B')
    ws=Workspace(roots=[tmp_path]);ws.open(a);ws.open(b);ws.activate(0)
    with TestClient(ide_app(ws)) as client:
        state=client.get('/tab/state',params={'path':str(b)}).json()
    assert state['text']=='B' and ws.tab.path==str(a.resolve())

def test_tab_state_reuses_the_live_notebook_instead_of_reloading_disk(tmp_path):
    a, b = tmp_path/'a.ipynb', tmp_path/'b.py'
    _nb(a, 'value = "live buffer"')
    b.write_text('pass\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "live buffer"'
        client.post('/tab/open', params={'path': str(b)})
        _nb(a, 'value = "changed on disk"')
        client.post('/tab/select', params={'i': 0})
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "live buffer"'

def test_remove_root_route_never_deletes_the_folder(tmp_path):
    root = tmp_path/'project'; root.mkdir(); kept = root/'keep.py'; kept.write_text('x = 1\n')
    ws = Workspace(roots=[root])
    with TestClient(ide_app(ws)) as client:
        assert client.post('/fs/remove-root', json={'path': str(root)}).json()['ok']
    assert root.exists() and kept.read_text() == 'x = 1\n'
    assert root not in ws.fs.roots


def test_save_refuses_to_overwrite_a_disk_change_after_the_draft_started(tmp_path):
    a = tmp_path/'a.py'; a.write_text('before = True\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        state = client.get('/tab/state').json()
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'text', 'text': 'browser = True\n',
                                         'base_disk_version': state['disk_version']})
        a.write_text('external = True\n')
        refused = client.post('/nb/save', json={'text': 'browser = True\n',
                                                'base_disk_version': state['disk_version']})
        assert refused.status_code == 409
        assert a.read_text() == 'external = True\n'
        forced = client.post('/nb/save', json={'text': 'browser = True\n',
                                               'base_disk_version': state['disk_version'], 'force': True})
        assert forced.status_code == 200
    assert a.read_text() == 'browser = True\n'

def test_unsaved_text_file_buffer_survives_a_tab_round_trip(tmp_path):
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('disk = True\n'); b.write_text('pass\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'text', 'text': 'unsaved = True\n'})
        client.post('/tab/open', params={'path': str(b)})
        client.post('/tab/select', params={'i': 0})
        assert client.get('/tab/state').json()['text'] == 'unsaved = True\n'
    assert a.read_text() == 'disk = True\n'

def test_save_all_persists_inactive_tab_buffers(tmp_path):
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('old_a = True\n'); b.write_text('old_b = True\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a); ws.open(b)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'text', 'text': 'new_a = True\n'})
        client.post('/tab/buffer', json={'path': str(b), 'kind': 'text', 'text': 'new_b = True\n'})
        response = client.post('/tabs/save-all')
        assert response.status_code == 200 and response.json()['saved'] == 2
    assert a.read_text() == 'new_a = True\n'
    assert b.read_text() == 'new_b = True\n'


def test_cell_runs_carry_document_and_cell_identity_and_reject_stale_positions(tmp_path):
    notebook = tmp_path/'ordered.ipynb'; _nb(notebook, 'class Definition: pass')
    ws = Workspace(roots=[tmp_path]); ws.open(notebook)
    with TestClient(ide_app(ws)) as client:
        state = client.get('/tab/state').json()
        response = client.post('/nb/run/stream', json={
            'path': str(notebook), 'i': 0, 'id': 'a-cell-that-moved', 'source': 'pass',
        })
    assert response.status_code == 409

def test_a_tab_can_be_dragged_to_a_new_position_and_the_same_document_stays_active(tmp_path):
    "The strip is the user's arrangement of their own work, so the order is server state."
    a, b, c = (tmp_path/f'{n}.py' for n in 'abc')
    for p in (a, b, c): p.write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    for p in (a, b, c): ws.open(p)
    ws.activate(0)
    with TestClient(ide_app(ws)) as client:
        assert client.post('/tab/move?i=0&j=2').status_code == 200
    assert [t.title for t in ws.tabs] == ['b.py', 'c.py', 'a.py']
    assert ws.tab.title == 'a.py', 'the dragged tab is still the one being edited'

def test_moving_a_tab_nowhere_or_out_of_range_is_a_no_op(tmp_path):
    a, b = (tmp_path/f'{n}.py' for n in 'ab')
    for p in (a, b): p.write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    for p in (a, b): ws.open(p)
    before = list(ws.tabs)
    ws.move_tab(1, 1); ws.move_tab(9, 0); ws.move_tab(0, 9)
    assert [t.title for t in ws.tabs] == [t.title for t in ([before[1], before[0]])], 'only the clamped move applied'


def test_the_tab_menu_offers_the_bulk_closes_and_they_run_right_to_left():
    from leela.blocks.keys.menus import MENUS
    actions = [i.action for i in MENUS['tab']]
    assert actions[-3:] == ['close_others', 'close_right', 'close_saved']


def _notebook(path):
    path.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'cell_type': 'code', 'source': f'value_{i} = {i}', 'metadata': {}, 'outputs': [],
         'execution_count': None, 'id': f'cell-{i}'} for i in range(12)
    ]}))

def test_type_change_accepts_all_live_sources_in_one_request(tmp_path):
    p = tmp_path/'work.ipynb'; _notebook(p)
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        sources = [{'i': i, 'source': f'edited_{i} = {i}'} for i in range(12)]
        d = client.post('/nb/edit', json={'op': 'type', 'i': 7, 'cycle': True,
                                          'sources': sources}).json()
    assert d['cells'][7]['cell_type'] == 'markdown'
    assert d['cells'][0]['source'] == 'edited_0 = 0'
    assert d['cells'][11]['source'] == 'edited_11 = 11'


def test_cell_clipboard_survives_tabs_and_pastes_full_cells_with_new_ids(tmp_path):
    a = tmp_path/'a.ipynb'; b = tmp_path/'b.ipynb'; _notebook(a); _notebook(b)
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        payload = client.post('/nb/edit', json={'op': 'paste', 'i': 1, 'cell': {
            'source': 'moved = True', 'cell_type': 'code', 'id': 'old-id',
            'outputs': [{'output_type': 'stream', 'text': 'yes\n'}], 'execution_count': 4,
        }}).json()
    pasted = payload['cells'][1]
    assert pasted['source'] == 'moved = True' and pasted['outputs'][0]['text'] == 'yes\n'
    assert pasted['id'] != 'old-id' and pasted['running'] is False


def test_workspace_hub_dispatches_by_localhost_subdomain():
    seen = []
    async def app_a(scope, receive, send): seen.append(('a', scope['leela.workspace_id']))
    async def app_b(scope, receive, send): seen.append(('b', scope['leela.workspace_id']))
    hub = WorkspaceHub([WorkspaceSite('alpha', 'Alpha', '/a', app_a),
                        WorkspaceSite('beta', 'Beta', '/b', app_b)], 5001)
    scope = {'type': 'http', 'headers': [(b'host', b'beta.localhost:5001')]}
    asyncio.run(hub(scope, Mock(), Mock()))
    assert seen == [('b', 'beta')]
    assert hub.catalog()[0]['url'] == 'http://alpha.localhost:5001/'

def test_a_prompt_cell_owns_its_approval_listener(tmp_path):
    "The prompt-cell frontend listens until its workspace shuts down."
    ws = Workspace(roots=[tmp_path])
    approvals = ws._notebook_approvals
    assert approvals.listeners == 1
    a = approvals.request('create_file', {'path': str(tmp_path/'x.py'), 'text': 'x = 1\n'}, timeout=0.05)
    assert a.note != 'nothing is listening for interventions, so this could not be asked'
    import threading
    held = {}
    t = threading.Thread(target=lambda: held.setdefault('a', approvals.request(
        'create_file', {'path': str(tmp_path/'y.py'), 'text': 'y = 1\n'}, timeout=10)))
    t.start()
    for _ in range(200):
        if approvals.pending: break
        time.sleep(0.01)
    assert approvals.pending is not None
    asyncio.run(ws.shutdown())
    t.join(1)
    assert not t.is_alive() and held['a'].note == 'the turn was cancelled'
    assert approvals.listeners == 0
    asyncio.run(ws.shutdown())
    assert approvals.listeners == 0

def test_the_pane_sees_and_answers_a_prompt_cell_approval(tmp_path):
    "A prompt cell runs on the inline assistant, which the pane could not otherwise see or answer."
    import threading
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        assert client.get('/agent/approval').json()['pending'] is None
        held = {}
        def ask():
            held['a'] = ws._notebook_approvals.request('create_file',
                {'path': str(tmp_path/'x.py'), 'text': 'x = 1\n'}, timeout=10)
        t = threading.Thread(target=ask); t.start()
        for _ in range(200):
            d = client.get('/agent/approval').json()
            if d['pending']: break
            time.sleep(0.02)
        assert d['pending'], 'the pane is where a person is looking'
        assert d['surface'] == 'notebook', 'and it says which surface raised it'
        answered = client.post('/agent/approve', json={'id': d['pending']['id'], 'ok': False,
                                                       'note': 'use the other file'}).json()
        assert answered['ok'] is not False or 'note' in str(answered), answered
        t.join(5)
        assert held['a'].note == 'use the other file', 'answered where it was raised'

def test_a_file_can_be_named_relatively_or_absolutely(tmp_path):
    """Copying a path is for giving it to somebody: relative for a colleague in the same repository,
    absolute for a shell here. Only the server knows which open folder a path is under."""
    root = tmp_path/'proj'; (root/'pkg').mkdir(parents=True)
    (root/'pkg'/'mod.py').write_text('x = 1\n')
    ws = Workspace(roots=[root])
    with TestClient(ide_app(ws)) as client:
        d = client.get(f"/fs/paths?path={root/'pkg'/'mod.py'}").json()
        assert d['ok'] and d['relative'] == 'pkg/mod.py'
        assert d['absolute'] == str(root/'pkg'/'mod.py')
        assert client.get('/fs/paths?path=').json()['ok'] is False, 'no path is not an empty answer'
        folder = client.get(f"/fs/paths?path={root/'pkg'}").json()
        assert folder['relative'] == 'pkg', 'a folder is named the same way'
        at_root = client.get(f'/fs/paths?path={root}').json()
        assert at_root['relative'] == '.', 'the open folder itself is its own root'

def test_copying_a_path_is_offered_wherever_a_file_is_named():
    "The tree, its folders and the tab strip all name a file, so all three offer it."
    from leela.blocks.keys.menus import MENUS
    from leela.core.keys import lookup
    for surface in ('file', 'folder', 'tab'):
        actions = [i.action for i in MENUS[surface]]
        assert 'copy_rel_path' in actions and 'copy_abs_path' in actions, surface
    assert 'copy_abs_path' in [i.action for i in MENUS['root']], 'a root has no relative form'
    for action in ('copy_rel_path', 'copy_abs_path'):
        assert lookup(action).keys, f'{action} has a chord of its own'

def test_the_prompt_cell_model_is_the_saved_one_not_the_routing_default(tmp_path):
    """`inline` is in `JOBS` and `**jobs` is spread last, so the routing default for the job
    overwrote the saved prompt-cell model every time. The choice was saved correctly and always
    came back reading as the turn model, which is what looked like shutdown reverting it."""
    ws = Workspace(roots=[tmp_path], inline_model='gpt-4.1-nano')
    with TestClient(ide_app(ws)) as client:
        picked = client.get('/agent/models').json()['selected']
    assert picked['inline'].endswith('gpt-4.1-nano'), picked['inline']
    assert picked['inline'] != picked['agent'], 'the prompt cell has a field of its own'
    assert 'summary' in picked and 'classify' in picked, 'the routed jobs are still reported'

def test_naming_a_folder_keeps_the_settings_the_last_session_saved(tmp_path):
    """Naming a folder built a fresh workspace carrying three model names, so a per-job model, a
    budget or a charter chosen yesterday was gone today -- which reads as shutting down having
    reverted it."""
    state = tmp_path/'state.json'
    first = Workspace(roots=[tmp_path]); first._state_path = state
    first.job_models = {'summary': 'gpt-4.1-mini', 'classify': 'gpt-4.1-nano'}
    first.inline_model = 'gpt-mini'
    first.tool_budget, first.step_budget = 120, 24
    first.subagent_writes = first.agent_read_outside = True
    first.compact_strategy = 'aggressive'
    first.agent_state = 'ship the montage'
    first.save()
    remembered = json.loads(state.read_text())
    again = Workspace(roots=[tmp_path], inline_model=remembered['inline_model']).restore_settings(remembered)
    assert again.job_models == {'summary': 'gpt-4.1-mini', 'classify': 'gpt-4.1-nano'}
    assert (again.tool_budget, again.step_budget) == (120, 24)
    assert again.subagent_writes and again.agent_read_outside
    assert again.compact_strategy == 'aggressive' and again.inline_model == 'gpt-mini'
    assert again.agent_state_layers['task']['text'] == 'ship the montage'
    assert Workspace(roots=[tmp_path]).restore_settings(None).job_models == {}, 'and nothing saved is no error'

def test_the_journal_follows_the_folders_that_are_open(tmp_path):
    """Built once in `__init__`, a workspace that started with no folders kept the key for *no*
    folders after one was opened, so every project a desktop launch touched wrote into one shared
    file. That is how a single journal reached gigabytes."""
    a, b = tmp_path/'a', tmp_path/'b'
    a.mkdir(); b.mkdir()
    ws = Workspace(roots=[])
    empty = ws._journal_key
    assert empty == 'no-folder', 'and the empty set is its own bucket, not the hash of nothing'
    ws.add_root(a)
    assert ws._journal_key != empty, 'opening a folder moves it off the scratch bucket'
    with_a = ws._journal_key
    ws.add_root(b)
    assert ws._journal_key not in (empty, with_a), 'and a second folder is a different workspace'
    ws.drop_root(b)
    assert ws._journal_key == with_a, 'closing it goes back to the one it had'
    assert ws.journal.history is ws.history and ws.history.pinned == ws.journal.blobs

def test_a_save_conflict_says_who_wrote_the_version_on_disk(tmp_path):
    """`load disk version` read the same whether another process had written the file or Leela had
    written it and the browser draft was holding a base from before that save. They need different
    answers, and the dialog could not tell them apart."""
    f = tmp_path/'notes.py'; f.write_text('one\n')
    ws = Workspace(roots=[tmp_path]); ws.open(f)
    with TestClient(ide_app(ws)) as client:
        client.get(f'/tab/state?path={f}')                       # the version Leela read it at
        stale = '0:0'
        f.write_text('written by something else\n')
        outside = client.post('/nb/save', json={'text': 'mine\n', 'base_disk_version': stale}).json()
        assert 'another process wrote it' in outside['error'], outside
        assert f'Draft base {stale}' in outside['error'], 'and what it compared'
        saved = client.post('/nb/save', json={'text': 'two\n'}).json()
        assert saved['ok'], saved
        again = client.post('/nb/save', json={'text': 'three\n',
                                             'base_disk_version': stale}).json()
        assert 'Leela wrote that version itself' in again['error'], again
    assert f.read_text() == 'two\n', 'and neither refusal wrote anything'

def test_the_hub_gives_the_lifespan_to_every_workspace_not_just_the_default():
    """Lifespan carries no Host header. Dispatched by host it reached one workspace, so the others
    never heard the shutdown and never stopped their kernels, terminals or dev servers."""
    down = []
    def site(slug):
        async def app(scope, receive, send):
            assert scope['type'] == 'lifespan'
            while True:
                m = await receive()
                if m['type'] == 'lifespan.shutdown': down.append(slug); return
        return WorkspaceSite(slug, slug, '/' + slug, app)
    hub = WorkspaceHub([site('alpha'), site('beta')], 5001)
    sent, inbox = [], asyncio.Queue()
    for m in ({'type': 'lifespan.startup'}, {'type': 'lifespan.shutdown'}): inbox.put_nowait(m)
    asyncio.run(hub({'type': 'lifespan'}, inbox.get, lambda m: sent.append(m) or asyncio.sleep(0)))
    assert sorted(down) == ['alpha', 'beta']
    assert [m['type'] for m in sent] == ['lifespan.startup.complete', 'lifespan.shutdown.complete'], \
        'and the server is answered once, not once per workspace'

def test_the_app_tears_its_workspace_down_when_the_server_stops(tmp_path):
    "Nothing called `shutdown`, so a closed window left kernels, terminals and pyright running."
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client: client.get('/health')
    assert ws._down, 'leaving the lifespan is what ends the session'

def test_shutdown_runs_once_and_no_failed_step_skips_a_later_one(tmp_path):
    "A step that raises must not strand a subprocess: the window it belonged to has already gone."
    ws = Workspace(roots=[tmp_path])
    ran = []
    def boom(): ran.append('terms'); raise RuntimeError('pty is wedged')
    ws.terms.close_all = boom
    ws.fs_watch.close = lambda: ran.append('watch')
    ws._stop_backups = lambda: ran.append('backups')
    asyncio.run(ws.shutdown())
    assert ran == ['terms', 'watch', 'backups']
    asyncio.run(ws.shutdown())
    assert ran == ['terms', 'watch', 'backups'], 'and it does not run a second time'

def test_naming_a_folder_reopens_that_folder_s_tabs_and_no_other_project_s(tmp_path):
    """`leela .` skipped the saved session entirely and always opened empty. The folder named is
    still that folder's session; another project's tabs are not part of it."""
    mine, other = tmp_path/'mine', tmp_path/'other'
    mine.mkdir(); other.mkdir()
    (a := mine/'a.py').write_text('a = 1\n')
    (b := mine/'b.py').write_text('b = 2\n')
    (c := other/'c.py').write_text('c = 3\n')
    state = tmp_path/'state.json'
    first_run = Workspace(roots=[mine, other]); first_run._state_path = state
    for f in (a, c, b): first_run.open(f)
    first_run.activate(first_run.find(b))
    first_run.save()
    fresh = Workspace(roots=[mine])
    assert fresh.reopen_saved_tabs(state) == 2, 'a.py and b.py, not the other project'
    assert [Path(t.path).name for t in fresh.tabs] == ['a.py', 'b.py']
    assert fresh.tabs[fresh.active].path == str(b), 'and the tab that was in front is again'
    assert Workspace(roots=[other]).reopen_saved_tabs(tmp_path/'never-written.json') == 0, 'no state, no tabs'

def test_a_reopened_tab_whose_file_has_gone_is_skipped_not_an_error(tmp_path):
    state = tmp_path/'state.json'
    (kept := tmp_path/'kept.py').write_text('k = 1\n')
    (lost := tmp_path/'lost.py').write_text('l = 1\n')
    ws = Workspace(roots=[tmp_path]); ws._state_path = state
    ws.open(lost); ws.open(kept); ws.save()
    lost.unlink()
    fresh = Workspace(roots=[tmp_path])
    assert fresh.reopen_saved_tabs(state) == 1
    assert [Path(t.path).name for t in fresh.tabs] == ['kept.py']

def test_shutdown_saves_the_session_so_the_next_window_opens_where_this_one_left_off(tmp_path):
    state = tmp_path/'state.json'
    (f := tmp_path/'notes.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path]); ws._state_path = state
    ws.open(f)
    state.unlink(missing_ok=True)
    asyncio.run(ws.shutdown())
    assert [t['path'] for t in json.loads(state.read_text())['tabs']] == [str(f)]

def test_a_workspace_can_be_torn_down_from_outside_the_event_loop(tmp_path):
    """The desktop shell runs the server on a daemon thread and the window on the main one, so
    closing the window ends the process without uvicorn reaching its shutdown lifespan."""
    import atexit
    ws = Workspace(roots=[tmp_path])
    assert ws.at_exit() is ws
    atexit.unregister(ws.shutdown_now)
    ws.terms.close_all = lambda: (_ for _ in ()).throw(RuntimeError('no loop here'))
    ws.shutdown_now()
    assert ws._down, 'and it never raises on the way out'

def test_the_exit_teardown_goes_back_to_the_loop_that_owns_the_kernels(tmp_path):
    "A kernel's client belongs to the loop it was opened on and cannot be closed from a fresh one."
    ws, ran = Workspace(roots=[tmp_path]), []
    async def _same_loop():
        ran.append(asyncio.get_running_loop() is ws._loop)
    async def serve():
        await ws.opened()
        ws.pool.close_all = _same_loop
        await asyncio.get_running_loop().run_in_executor(None, ws.shutdown_now)
    asyncio.run(serve())
    assert ran == [True], 'the teardown ran on the server loop, not on the exiting thread'
    assert ws._down

def test_the_exit_teardown_falls_back_to_its_own_loop_when_the_server_has_gone(tmp_path):
    ws = Workspace(roots=[tmp_path])
    asyncio.run(ws.opened())            # that loop is closed the moment `run` returns
    ws.shutdown_now()
    assert ws._down

def test_workspace_hub_rejects_unknown_hosts_instead_of_opening_default_workspace():
    called, messages = [], []
    async def app(scope, receive, send): called.append(scope)
    async def send(message): messages.append(message)
    hub = WorkspaceHub([WorkspaceSite('alpha', 'Alpha', '/a', app)], 5001)
    scope = {'type': 'http', 'headers': [(b'host', b'attacker.example:5001')]}
    asyncio.run(hub(scope, Mock(), send))
    assert not called
    assert messages[0]['status'] == 421

def test_loopback_guard_rejects_dns_rebinding_and_cross_site_browser_requests():
    called = []
    async def app(scope, receive, send): called.append(scope)
    async def run(headers):
        messages = []
        async def send(message): messages.append(message)
        await LoopbackHostGuard(app)({'type': 'http', 'headers': headers}, Mock(), send)
        return messages
    rebound = asyncio.run(run([(b'host', b'attacker.example:5001')]))
    cross_site = asyncio.run(run([(b'host', b'localhost:5001'),
                                  (b'origin', b'https://attacker.example'),
                                  (b'sec-fetch-site', b'cross-site')]))
    assert rebound[0]['status'] == cross_site[0]['status'] == 421
    assert not called

def test_runtime_broker_refuses_a_thirteenth_heap_without_evicting_live_state(monkeypatch):
    broker = RuntimeBroker(max_kernels=1)
    pool = KernelPool(broker=broker)
    alive = Mock(alive=True, pid=42, kernel_kind='ipykernel', cwd='/project')
    pool.kernels['first'] = alive
    with pytest.raises(RuntimeError, match='kernel limit reached'):
        asyncio.run(broker.admit(pool, 'second'))
    assert pool.kernels['first'] is alive

def test_the_tree_hears_about_a_change_leela_did_not_make(tmp_path):
    "Without a watcher the tree knew only what the client itself had done."
    from leela.blocks.fs.fs import Sandbox
    from leela.blocks.fs.watch import Watcher
    (tmp_path/'a.py').write_text('x = 1\n')
    (tmp_path/'node_modules').mkdir()
    async def run():
        w = Watcher(Sandbox([tmp_path]), step=50)
        q = w.subscribe()
        try:
            await asyncio.sleep(.4)
            # macOS replays the setup mkdir as a batch of its own once the watch settles.
            while not q.empty(): q.get_nowait()
            (tmp_path/'node_modules'/'junk.js').write_text('1\n')
            with pytest.raises(asyncio.TimeoutError): await asyncio.wait_for(q.get(), .6)
            (tmp_path/'b.py').write_text('y = 2\n')
            return (await asyncio.wait_for(q.get(), 5))[0]
        finally: w.close()
    paths = asyncio.run(run())
    assert any(p.endswith('b.py') for p in paths)
    assert not any('node_modules' in p for p in paths), 'the skip list applies to the watcher too'

def test_the_last_reader_leaving_does_not_stall_the_loop_and_the_next_one_is_watched_again(tmp_path):
    "`unsubscribe` runs on the event loop, and the Rust watcher takes `rust_timeout` to notice."
    import asyncio, time
    from leela.blocks.fs.fs import Sandbox
    from leela.blocks.fs.watch import Watcher
    async def run():
        w = Watcher(Sandbox([tmp_path]), step=50)
        q = w.subscribe()
        await asyncio.sleep(.3)
        at = time.monotonic()
        w.unsubscribe(q)
        spent, first = time.monotonic() - at, w.thread
        second = w.subscribe()
        try:
            await asyncio.sleep(.3)
            (tmp_path/'c.py').write_text('z = 3\n')
            return spent, first, w.thread, (await asyncio.wait_for(second.get(), 5))[0]
        finally: w.close()
    spent, first, second, paths = asyncio.run(run())
    assert spent < .2, f'the last tab closing blocked the loop for {spent:.2f}s'
    assert second is not first, 'a stopping thread is not a running one'
    assert any(p.endswith('c.py') for p in paths), 'and the next reader is watched again'


def test_a_folder_opened_after_boot_is_watched_too(tmp_path):
    """`subscribe` was the only other caller of `start`, and it runs once per page load. Opening
    a folder from the welcome screen left the watcher with the empty root set it booted with.
    """
    a, b = tmp_path/'a', tmp_path/'b'
    a.mkdir(); b.mkdir()
    ws = Workspace(roots=[a])
    async def run():
        q = ws.fs_watch.subscribe()
        await asyncio.sleep(.4)
        while not q.empty(): q.get_nowait()
        ws.add_root(b)
        await asyncio.sleep(.5)
        while not q.empty(): q.get_nowait()
        (b/'new.py').write_text('x = 1\n')
        return (await asyncio.wait_for(q.get(), 5))[0]
    try: paths = asyncio.run(run())
    finally: ws.fs_watch.close()
    assert any('new.py' in p for p in paths), 'the folder opened after boot is watched'

def test_opening_a_folder_off_the_event_loop_is_not_an_error(tmp_path):
    "`/fs/add_root` is a sync route, so `add_root` runs in a threadpool with no running loop."
    a, b = tmp_path/'a', tmp_path/'b'
    a.mkdir(); b.mkdir()
    ws = Workspace(roots=[a])
    ws.add_root(b)                      # no loop here, and none is needed
    assert str(b) in [str(r) for r in ws.fs.roots]
    ws.fs_watch.close()

def test_shutdown_stops_the_watcher_thread(tmp_path):
    "The module says a Rust thread alive at interpreter teardown segfaults; nothing stopped it."
    ws = Workspace(roots=[tmp_path])
    async def run():
        ws.fs_watch.subscribe()
        await asyncio.sleep(.3)
        assert ws.fs_watch.thread and ws.fs_watch.thread.is_alive()
    asyncio.run(run())
    asyncio.run(ws.shutdown())
    assert ws.fs_watch.thread is None, 'shutdown owns the join'


def test_replacing_the_watcher_does_not_wait_for_the_old_thread(tmp_path):
    "`start` calls `close`, and a join on the event loop freezes every socket in the process."
    from leela.blocks.fs.fs import Sandbox
    from leela.blocks.fs.watch import Watcher
    async def run():
        w = Watcher(Sandbox([tmp_path]))
        w.subscribe()
        await asyncio.sleep(.3)
        old = w.thread
        w.close(wait=False)
        return old, old.is_alive()
    old, running = asyncio.run(run())
    old.join(5)
    assert running, 'the replacement must not wait for the old thread to notice'
    assert not old.is_alive(), 'and it still stops'

def test_a_batch_too_big_to_send_asks_for_a_resync_instead_of_dropping_it(tmp_path):
    """Batches are deltas, not snapshots, so a truncated or dropped one is lost for good: the
    tree keeps showing files that are gone until something unrelated happens to touch it.
    """
    from leela.blocks.fs.fs import Sandbox
    from leela.blocks.fs.watch import Watcher, MAX_BATCH
    async def run():
        w = Watcher(Sandbox([tmp_path]))
        q, out = w.subscribe(), []
        w._push([f'{tmp_path}/f{i}.py' for i in range(MAX_BATCH + 5)])
        await asyncio.sleep(.05)
        out.append(q.get_nowait())
        for _ in range(q.maxsize + 3): w._push([f'{tmp_path}/x.py'])
        await asyncio.sleep(.05)
        while not q.empty(): out.append(q.get_nowait())
        w.close()
        return out
    batches = asyncio.run(run())
    assert batches[0] == ([], True), 'too many paths to carry is a resync, not a truncation'
    assert ([], True) in batches[1:], 'a full queue is a resync too'


def test_the_settings_pane_can_mute_the_kernel_limit_prompt(tmp_path):
    "The mute switch the user asked for: leela manages the ceiling itself."
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        page = client.get('/').text
    assert 'kernels-auto-manage' in page and 'setKernelAutoManage(this.checked)' in page
    assert 'auto_manage' in (ROOT/'leela'/'workspace.py').read_text()

def _one_cell_nb(src):
    return json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'cell_type': 'code', 'source': src, 'metadata': {}, 'outputs': [],
         'execution_count': None, 'id': 'c1'}]})

def test_an_open_notebook_does_not_resurrect_itself_over_newer_work(tmp_path):
    """`/tab/state` served the cached notebook stamped with the version now on disk, so the browser
    sent that back as its base, `/nb/save` found base and disk equal, and the old branch's cells
    overwrote the new ones. Opening the tab was enough: no unsaved edit was needed. The live notebook
    stays authoritative because it carries outputs the file does not, so the fix is the stamp."""
    p = tmp_path/'core.ipynb'
    p.write_text(_one_cell_nb('X = "branch-a"'))
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    with TestClient(ide_app(ws)) as client:
        first = client.get('/tab/state', params={'path': tab.path}).json()
        assert first['cells'][0]['source'] == 'X = "branch-a"' and not first.get('stale')
        p.write_text(_one_cell_nb('X = "branch-b"'))          # a branch switch, a rebase, an agent
        after = client.get('/tab/state', params={'path': tab.path}).json()
        r = client.post('/nb/save', json={'path': tab.path,
                                          'base_disk_version': after['disk_version'],
                                          'cells': [{'i': 0, 'source': 'X = "branch-a"'}]})
        assert 'branch-b' in p.read_text(), 'the newer work must survive the stale save'
        assert r.status_code == 409, 'the save guard catches it instead of overwriting'
        assert after['disk_version'] == first['disk_version'], 'stamped with what it was read at'
        assert after.get('stale') is True, 'the file has moved under the copy being served'

def test_an_unsaved_draft_is_kept_but_reported_against_what_it_came_from(tmp_path):
    "A dirty tab is the person's own work, so it survives; the save guard is what must fire."
    p = tmp_path/'mod.py'
    p.write_text('VALUE = "branch-a"\n')
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    with TestClient(ide_app(ws)) as client:
        opened = client.get('/tab/state', params={'path': tab.path}).json()
        client.post('/tab/buffer', json={'path': tab.path, 'kind': 'text',
                                         'text': 'VALUE = "my-edit"\n',
                                         'base_disk_version': opened['disk_version']})
        p.write_text('VALUE = "branch-b"\n')
        after = client.get('/tab/state', params={'path': tab.path}).json()
        assert after['text'].strip() == 'VALUE = "my-edit"', 'unsaved typing is never dropped'
        assert after['stale'] is True
        assert after['disk_version'] == opened['disk_version'], 'reported against its own base'
        r = client.post('/nb/save', json={'path': tab.path,
                                          'base_disk_version': after['disk_version'],
                                          'text': 'VALUE = "my-edit"\n'})
        assert r.status_code == 409, 'the save guard now has a stale base to catch'
    assert 'branch-b' in p.read_text(), 'the newer work on disk is still there'

def test_saving_makes_the_cached_copy_current_again(tmp_path):
    "After a save the cache matches the file, so the next read must not be called stale."
    p = tmp_path/'core.ipynb'
    p.write_text(_one_cell_nb('X = 1'))
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    with TestClient(ide_app(ws)) as client:
        opened = client.get('/tab/state', params={'path': tab.path}).json()
        r = client.post('/nb/save', json={'path': tab.path,
                                          'base_disk_version': opened['disk_version'],
                                          'cells': [{'i': 0, 'source': 'X = 2'}]}).json()
        assert r['ok']
        again = client.get('/tab/state', params={'path': tab.path}).json()
        assert again['cells'][0]['source'] == 'X = 2' and not again['stale']


def test_the_history_list_and_the_model_picker_carry_what_the_pane_filters_on(tmp_path):
    """`/agent/history` says which app started each conversation, so the pane can hide the CLI's.
    `/agent/models` ships the job help, so the `?` beside a model control reads the same sentence
    the server-rendered ones do.
    """
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        d = client.get('/agent/history').json()
        assert all('app' in s for s in d['sessions'])
        m = client.get('/agent/models').json()
        assert m['job_help']['oneshot'] and set(m['jobs']) <= set(m['job_help'])
        # the live conversation is Leela's, and says so once it has been grouped
        from leela.blocks.agent.turns import surfaces
        assert ws.ai.session_id in surfaces(ws.ai.cfg)


def _nb_json(cells):
    "A minimal notebook: (id, source, outputs) per cell."
    import json
    return json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {},
                       'cells': [{'cell_type': 'code', 'id': i, 'source': s, 'outputs': o,
                                  'execution_count': None, 'metadata': {}} for i, s, o in cells]})

def test_a_clean_run_over_the_notebook_does_not_block_a_source_edit(tmp_path):
    """`nbdev_clean` strips outputs and metadata; a browser save writes cell sources. Those never
    touch the same thing, and a conflict on the version token alone stopped the save anyway."""
    nb = tmp_path/'n.ipynb'
    nb.write_text(_nb_json([('c1', 'x = 1', [{'output_type': 'stream', 'text': 'noise'}]),
                            ('c2', 'y = 2', [])]))
    ws = Workspace(roots=[tmp_path]); ws.open(nb)
    with TestClient(ide_app(ws)) as client:
        state = client.get('/tab/state').json()
        # what nbdev-prepare does: same sources, outputs gone
        nb.write_text(_nb_json([('c1', 'x = 1', []), ('c2', 'y = 2', [])]))
        r = client.post('/nb/save', json={'path': str(nb), 'base_disk_version': state['disk_version'],
                                          'cells': [{'i': 0, 'source': 'x = 11'}]})
        assert r.status_code == 200, r.json()
    import json
    saved = json.loads(nb.read_text())
    src = lambda c: ''.join(c['source']) if isinstance(c['source'], list) else c['source']
    assert src(saved['cells'][0]) == 'x = 11', 'the browser edit landed'
    assert src(saved['cells'][1]) == 'y = 2', 'the untouched cell is untouched'
    assert not saved['cells'][0]['outputs'], 'and the clean was not undone'

def test_a_source_changed_on_both_sides_still_refuses_and_names_the_cell(tmp_path):
    "The one case worth stopping for, and it says which cell rather than only that something moved."
    nb = tmp_path/'n.ipynb'
    nb.write_text(_nb_json([('c1', 'x = 1', []), ('c2', 'y = 2', [])]))
    ws = Workspace(roots=[tmp_path]); ws.open(nb)
    with TestClient(ide_app(ws)) as client:
        state = client.get('/tab/state').json()
        nb.write_text(_nb_json([('c1', 'x = 999', []), ('c2', 'y = 2', [])]))
        r = client.post('/nb/save', json={'path': str(nb), 'base_disk_version': state['disk_version'],
                                          'cells': [{'i': 0, 'source': 'x = 11'}]})
        assert r.status_code == 409
        assert 'cell 1' in r.json()['error'], r.json()
        assert 'x = 999' in nb.read_text(), 'the disk version is left alone'
        forced = client.post('/nb/save', json={'path': str(nb), 'force': True,
                                               'base_disk_version': state['disk_version'],
                                               'cells': [{'i': 0, 'source': 'x = 11'}]})
        assert forced.status_code == 200, 'force still wins'

def test_a_cell_the_external_write_removed_is_not_reconciled(tmp_path):
    "With the cell gone there is nothing to rebase onto, so the save refuses rather than guessing."
    nb = tmp_path/'n.ipynb'
    nb.write_text(_nb_json([('c1', 'x = 1', []), ('c2', 'y = 2', [])]))
    ws = Workspace(roots=[tmp_path]); ws.open(nb)
    with TestClient(ide_app(ws)) as client:
        state = client.get('/tab/state').json()
        nb.write_text(_nb_json([('c2', 'y = 2', [])]))
        r = client.post('/nb/save', json={'path': str(nb), 'base_disk_version': state['disk_version'],
                                          'cells': [{'i': 0, 'source': 'x = 11'}]})
        assert r.status_code == 409


def test_a_tab_whose_file_moved_is_reported_as_stale(tmp_path):
    """`/tab/state` keeps serving the cached copy, so the flag is the only thing that says the file
    moved. Nothing read it, and an open notebook showed the version from before `nbdev-prepare`."""
    nb = tmp_path/'n.ipynb'
    nb.write_text(_nb_json([('c1', 'x = 1', [{'output_type': 'stream', 'text': 'noise'}])]))
    ws = Workspace(roots=[tmp_path]); ws.open(nb)
    with TestClient(ide_app(ws)) as client:
        first_read = client.get('/tab/state').json()
        assert first_read['stale'] is False
        nb.write_text(_nb_json([('c1', 'x = 1', [])]))
        again = client.get('/tab/state').json()
        assert again['stale'] is True, 'the file moved under the cached copy'
        assert again['disk_version'] == first_read['disk_version'], 'and the token still names the cached one'

def test_the_client_acts_on_the_stale_flag():
    "Reloading a clean tab, and never dropping an unsaved buffer for a disk change."
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]/'leela'/'blocks'/'editor'/'tabs.js').read_text()
    assert 'if (st.stale) noteStaleTab(' in src, 'the flag has to be read'
    body = src[src.index('function noteStaleTab'):]
    assert 'st.dirty || recoveredDraft' in body, 'an unsaved buffer is never dropped'
    assert body.index('st.dirty || recoveredDraft') < body.index('takeDiskVersion'), \
        'the dirty case must return before anything adopts disk'


def test_a_rewrite_that_changed_nothing_is_not_a_disk_change(tmp_path):
    """`nbdev_clean` rewrites a notebook it has nothing to change, and any formatter does the same.
    On an mtime token that read as an outside write and turned the next save into a conflict."""
    import time
    from leela.blocks.tabs.app import disk_version
    f = tmp_path/'n.ipynb'
    f.write_text('same bytes')
    was = disk_version(f)
    time.sleep(0.01)
    f.write_text('same bytes')
    assert disk_version(f) == was, 'the same bytes are the same version'
    f.write_text('other bytes')
    assert disk_version(f) != was, 'and different bytes are not'

def test_the_version_of_a_file_that_is_gone_is_missing_and_not_remembered(tmp_path):
    "A deleted file must not answer with the token it had, which a cache makes easy to get wrong."
    from leela.blocks.tabs.app import _TOKENS, disk_version
    f = tmp_path/'gone.py'
    f.write_text('x')
    assert disk_version(f) not in ('', 'missing')
    f.unlink()
    assert disk_version(f) == 'missing'
    assert str(f) not in _TOKENS and f not in _TOKENS, 'the stale entry is dropped'
    assert disk_version('') == ''

def test_polling_an_untouched_file_does_not_read_it(tmp_path, monkeypatch):
    "A poll on every open tab must stay one `stat`, which is what it cost before the hash."
    from leela.blocks.tabs.app import disk_version
    f = tmp_path/'a.py'
    f.write_text('x = 1\n')
    first = disk_version(f)
    reads = []
    real = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda self: reads.append(self) or real(self))
    assert disk_version(f) == first
    assert reads == [], 'the cached stamp answered without touching the file'

def test_the_token_cache_does_not_grow_without_bound(tmp_path):
    "A long session opens many files, and none of these entries is worth keeping."
    from leela.blocks.tabs import app as tabs
    tabs._TOKENS.clear()
    for i in range(tabs.TOKEN_CACHE + 5):
        f = tmp_path/f'f{i}.py'; f.write_text(str(i))
        tabs.disk_version(f)
    assert len(tabs._TOKENS) <= tabs.TOKEN_CACHE


def _hub_get(hub, path, query=b''):
    "Drive one HTTP request through the hub and return `(status, json)`."
    sent = []
    async def send(m): sent.append(m)
    async def receive(): return {'type': 'http.request', 'body': b''}
    asyncio.run(hub({'type': 'http', 'path': path, 'query_string': query, 'headers': []},
                    receive, send))
    return sent[0]['status'], json.loads(sent[-1]['body'])

def test_a_folder_opened_while_leela_runs_becomes_its_own_workspace(tmp_path):
    """`open_folder` added a root to the window that was already open, so the second folder shared
    the first one's kernels, tabs and agent. A folder is a workspace, and a workspace is a window."""
    (one := tmp_path/'one').mkdir(); (two := tmp_path/'two').mkdir()
    made = []
    def build(root, slug):
        made.append(slug)
        return WorkspaceSite(slug, Path(root).name, str(root), lambda *a: None)
    hub = WorkspaceHub([WorkspaceSite('one', 'one', str(one), lambda *a: None)], 5001, build=build)
    status, d = _hub_get(hub, OPEN_PATH, b'path=' + str(two).encode())
    assert (status, d['ok']) == (200, True), d
    assert d['url'] == 'http://two.localhost:5001/' and d['id'] == 'two'
    assert set(hub.sites) == {'one', 'two'}, 'and the hub now serves both'

def test_opening_a_folder_that_is_already_open_reuses_its_workspace(tmp_path):
    "Two windows on one folder would be two kernels and two journals writing the same files."
    (one := tmp_path/'one').mkdir()
    def build(root, slug): raise AssertionError('nothing may be built for a folder already served')
    hub = WorkspaceHub([WorkspaceSite('one', 'one', str(one), lambda *a: None)], 5001, build=build)
    status, d = _hub_get(hub, OPEN_PATH, b'path=' + str(one).encode())
    assert (status, d['id']) == (200, 'one')
    assert list(hub.sites) == ['one'], 'and no second site was made for it'

def test_opening_something_that_is_not_a_folder_is_refused_not_served(tmp_path):
    (f := tmp_path/'notes.py').write_text('x = 1\n')
    hub = WorkspaceHub([], 5001, build=lambda root, slug: None)
    for raw in (str(f), str(tmp_path/'gone'), ''):
        status, d = _hub_get(hub, OPEN_PATH, b'path=' + raw.encode())
        assert (status, d['ok']) == (400, False), raw
        assert 'not a folder' in d['error'], d

def test_a_workspace_that_cannot_open_another_folder_says_so_rather_than_failing_silently(tmp_path):
    hub = WorkspaceHub([], 5001)
    status, d = _hub_get(hub, OPEN_PATH, b'path=' + str(tmp_path).encode())
    assert (status, d['ok']) == (400, False)
    assert 'cannot open another folder' in d['error'], d

def test_a_folder_opened_after_startup_still_hears_the_shutdown(tmp_path):
    """The lifespan legs were zipped over the sites present at startup, so a workspace opened later
    never heard `lifespan.shutdown` and left its kernels, terminals and dev servers running."""
    (late := tmp_path/'late').mkdir()
    up, down = [], []
    def site(slug, root=''):
        async def app(scope, receive, send):
            while True:
                m = await receive()
                if m['type'] == 'lifespan.startup': up.append(slug)
                elif m['type'] == 'lifespan.shutdown': down.append(slug); return
        return WorkspaceSite(slug, slug, root, app)
    hub = WorkspaceHub([site('alpha')], 5001, build=lambda root, slug: site(slug, str(root)))
    inbox, sent = asyncio.Queue(), []
    async def drive():
        task = asyncio.create_task(hub({'type': 'lifespan'}, inbox.get,
                                       lambda m: sent.append(m) or asyncio.sleep(0)))
        inbox.put_nowait({'type': 'lifespan.startup'})
        await asyncio.sleep(0)
        await asyncio.to_thread(hub.open_folder, late)
        await asyncio.sleep(.05)
        inbox.put_nowait({'type': 'lifespan.shutdown'})
        await task
    asyncio.run(drive())
    assert sorted(up) == ['alpha', 'late'], 'the late workspace is started, not only registered'
    assert sorted(down) == ['alpha', 'late'], 'and it is torn down with the rest'
    assert [m['type'] for m in sent] == ['lifespan.startup.complete', 'lifespan.shutdown.complete']

def test_a_folders_slug_does_not_depend_on_the_order_it_was_opened_in(tmp_path):
    """The slug names the state file, and a counter made it positional: open two projects that both
    end in `src` the other way round and each was served the other one's tabs."""
    (a := tmp_path/'a'/'src').mkdir(parents=True); (b := tmp_path/'b'/'src').mkdir(parents=True)
    store = tmp_path/'index.json'
    forward = dict(zip([a, b], assign_slugs([a, b], store)))
    assert len(set(forward.values())) == 2, forward
    assert assign_slugs([b, a], store) == [forward[b], forward[a]], 'the other order, the same slugs'
    assert assign_slugs([a], store) == [forward[a]], 'and one folder alone keeps what it was given'

def test_a_slug_already_given_out_survives_a_corrupt_or_missing_index(tmp_path):
    "The index is a convenience, not a source of truth: losing it must not raise, only re-assign."
    (a := tmp_path/'src').mkdir()
    store = tmp_path/'index.json'
    assert assign_slugs([a], store) == ['src']
    store.write_text('{not json')
    assert assign_slugs([a], store) == ['src'], 'and the obvious slug is still the obvious one'

def test_a_kernel_that_will_not_start_is_answered_and_not_raised(tmp_path, monkeypatch):
    """Both routes called `_k()` bare, so an environment that cannot run a kernel arrived as a 500
    with an ASGI traceback, where every other route in that file answers with something the client
    can read. The index completes without a kernel, so only the runtime names are lost."""
    from leela.blocks.runtime.kernels import KernelPool, KernelStartError
    async def _no_kernel(self, key, **kw):
        raise KernelStartError('/p/.venv/bin/python cannot import ipykernel_launcher, so it can run no kernel.')
    monkeypatch.setattr(KernelPool, 'get', _no_kernel)
    (tmp_path/'m.py').write_text('def valuable(): return 1\n')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        h = client.get('/exec/history')
        assert h.status_code == 200 and h.json()['cells'] == []
        assert 'ipykernel_launcher' in h.json()['error'], 'the reason, not an empty history'
        c = client.post('/complete', json={'code': 'valu', 'pos': 4})
        assert c.status_code == 200
        assert 'ipykernel_launcher' in c.json()['kernel_error']
        assert 'matches' in c.json(), 'the index answers even where the kernel cannot'

def test_the_branch_pill_is_rendered_true_and_never_claims_a_folder_has_no_repository(tmp_path):
    """It shipped as the literal `no git`, so any first paint the client did not reach left a claim
    about the project on screen. An unknown says so; only a folder really outside a checkout is
    called one."""
    from leela.app import _git_pill_text
    import subprocess
    repo = tmp_path/'repo'; (repo/'sub').mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', '-b', 'trunk', str(repo)], check=True)
    assert _git_pill_text(Workspace(roots=[repo])) == 'trunk'
    assert _git_pill_text(Workspace(roots=[repo/'sub'])) == 'trunk', 'a folder inside the checkout is in it'
    plain = tmp_path/'plain'; plain.mkdir()
    assert _git_pill_text(Workspace(roots=[plain])) == 'no git'
    assert _git_pill_text(Workspace(roots=[])) == 'git …', 'nothing open is not a statement about git'
    with TestClient(ide_app(Workspace(roots=[repo]))) as client:
        assert 'trunk' in client.get('/').text

def test_the_polled_kernel_pill_reads_the_runtime_the_cells_run_in(tmp_path):
    """`/kernel/info` peeked only the tab's own kernel while `runtime()` runs in the watched
    environment when there is one, so the pill reported dead for a kernel that was executing."""
    (tmp_path/'nb.ipynb').write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    ws = Workspace(roots=[tmp_path]); ws.open(tmp_path/'nb.ipynb')
    class _Live:
        name, base, pid, boot_error, last_api_error, alive = 'watched', 'http://127.0.0.1:8401', 4321, None, '', True
    live = _Live()
    ws.env_base = live.base
    ws.pool.kernels['somewhere/else'] = live
    assert ws.runtime_peek() is live, 'precondition: this is where a run would go'
    with TestClient(ide_app(ws)) as client:
        d = client.get('/kernel/info').json()
    assert d['alive'] is True and d['base'] == live.base and d['pid'] == 4321
    assert d['key'] == 'watched', 'a watched environment is named by its own kernel'

def test_the_kernel_pill_calls_a_tab_the_same_thing_alive_or_dead(tmp_path):
    "It took the kernel's name alive and the tab's file name dead, so one notebook had two names."
    (tmp_path/'01_graph.ipynb').write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    ws = Workspace(roots=[tmp_path]); tab = ws.open(tmp_path/'01_graph.ipynb')
    tab.private_kernel = True
    dead_name = ws.runtime_label()
    class _Live:
        name, base, pid, boot_error, last_api_error, alive = tmp_path.name, '', 1, None, '', True
    ws.pool.kernels[ws.kernel_key()] = _Live()
    assert ws.runtime_label() == dead_name == '01_graph.ipynb', 'the tab names its own kernel, running or not'

def test_one_language_server_however_many_lints_arrive_together(tmp_path):
    """`start` checked `alive` and spawned with nothing between them, and a notebook mount fires one
    lint per mounted cell, so a window ran two language servers with one of them orphaned."""
    import threading
    from leela.blocks.lsp.lsp import PyrightService
    svc = PyrightService(tmp_path)
    spawned = []
    class _Proc:
        def poll(self): return None
        def __init__(self): spawned.append(1)
    def _start(self):
        if self.alive: return True
        time.sleep(.05)                      # the window the race used to fit through
        self.process = _Proc()
        return True
    monkey = PyrightService._start
    PyrightService._start = _start
    try:
        threads = [threading.Thread(target=svc.start) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join(5)
    finally: PyrightService._start = monkey
    assert len(spawned) == 1, f'{len(spawned)} language servers for one workspace'

def test_a_frozen_app_does_not_run_itself_to_read_package_versions(tmp_path, monkeypatch):
    """In the bundle `sys.executable` is Leela, so the fallback ran `Leela.app/Contents/MacOS/Leela
    -c ...`: it relaunched the app and then waited out the eight second timeout, once per switch,
    for any project without an environment of its own."""
    (tmp_path/'pyproject.toml').write_text('[project]\nname = "x"\ndependencies = ["fastcore"]\n')
    import sys
    ran = []
    monkeypatch.setattr('leela.blocks.editor.app.subprocess.run',
                        lambda *a, **kw: ran.append(a) or (_ for _ in ()).throw(AssertionError('spawned')))
    monkeypatch.setattr('leela.blocks.runtime.kernels.nearest_python', lambda *a, **kw: None)
    monkeypatch.setattr('leela.blocks.runtime.kernels.project_python', lambda *a, **kw: None)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    ws = Workspace(roots=[tmp_path])
    ws.pool.default_python = None
    with TestClient(ide_app(ws)) as client:
        d = client.get('/editor/packages', params={'path': str(tmp_path/'pyproject.toml')}).json()
    assert d == {'packages': [], 'summary': {}, 'note': 'no interpreter for this project'}
    assert ran == [], 'and nothing was run to find that out'
