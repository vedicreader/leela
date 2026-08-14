"""What the agent is given when you point at something: a file, a folder, or a highlighted range.

The rule under test throughout is that context is *legible*: what went in can be named, and what
the model was shown is what you chose rather than whatever fitted in a budget.
"""

import sys

import pytest
from fastcore.all import Path
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder  # noqa: E402


@pytest.fixture
def ws(tmp_path):
    (tmp_path/'pkg').mkdir()
    (tmp_path/'pkg'/'a.py').write_text('print(1)\n')
    (tmp_path/'pkg'/'b.md').write_text('# B\n')
    (tmp_path/'top.py').write_text('x = 1\ny = 2\n')
    return Workspace(roots=[tmp_path])


def test_a_folder_is_a_manifest_not_its_contents(ws, tmp_path):
    """A folder is attached to say *look in here*, and the agent has file tools of its own.

    Inlining the contents would cut a repo off at the budget with the model unable to tell what
    it had not been shown.
    """
    out = ws.folder_manifest(tmp_path/'pkg')
    assert '<attached-folder' in out and 'files="2"' in out
    assert 'a.py' in out and 'b.md' in out
    assert 'python' in out and 'markdown' in out, 'the language is what makes it worth reading'
    assert 'print(1)' not in out, 'the contents are the agent\'s to fetch'


def test_a_folder_manifest_skips_what_walk_skips(ws, tmp_path):
    "Otherwise the first thing a manifest shows is somebody's virtualenv."
    (tmp_path/'pkg'/'node_modules').mkdir()
    (tmp_path/'pkg'/'node_modules'/'junk.js').write_text('module.exports = 1\n')
    assert 'junk.js' not in ws.folder_manifest(tmp_path/'pkg')


def test_attaching_a_folder_no_longer_raises(ws, tmp_path):
    "It used to be refused outright: `attachment is not a file`."
    text, _ = ws._attachment_context([str(tmp_path/'pkg')])
    assert '<attached-folder' in text


def test_a_selection_is_sent_as_chosen_not_re_read_from_disk(ws, tmp_path):
    "The buffer may be unsaved, and what was highlighted is what was meant."
    sel = {'kind': 'selection', 'path': str(tmp_path/'top.py'), 'from': 2, 'to': 2,
           'text': 'y = 2  # edited, never saved'}
    text, _ = ws._attachment_context([sel])
    assert 'lines="2-2"' in text and 'never saved' in text
    assert '<attached-selection' in text, 'marked as a range, not mistaken for a whole file'


def test_two_selections_in_one_file_are_two_contexts(ws, tmp_path):
    p = str(tmp_path/'top.py')
    a = {'kind': 'selection', 'path': p, 'from': 1, 'to': 1, 'text': 'x = 1'}
    b = {'kind': 'selection', 'path': p, 'from': 2, 'to': 2, 'text': 'y = 2'}
    text, _ = ws._attachment_context([a, b])
    assert text.count('<attached-selection') == 2
    # And the identical one is still deduplicated.
    assert ws._attachment_context([a, dict(a)])[0].count('<attached-selection') == 1


def test_folders_are_offered_to_the_agent_and_not_to_quick_open(ws, tmp_path):
    with TestClient(ide_app(ws)) as c:
        agent = c.get('/fs/find', params={'q': 'pkg', 'dirs': 1}).json()['hits']
        assert any(h['kind'] == 'folder' and h['name'] == 'pkg/' for h in agent)
        quick = c.get('/fs/find', params={'q': 'pkg'}).json()['hits']
        assert all(h['kind'] == 'file' for h in quick), 'opening a folder is not quick-open\'s job'


def test_the_token_stays_in_the_prompt_when_a_file_is_attached():
    """Stripping it left the sentence reading "look at and tell me why".

    What you typed is the reference; the chip is that reference resolved, not a replacement.
    """
    js = builder.OUT.read_text()
    block = js[js.index('function chooseAgentSuggest'):js.index('let agentSuggestSeq')]
    assert '`$1@${item.name} `' in block, 'the token is rewritten, not removed'


def test_removing_a_chip_removes_its_token():
    "Or the prompt goes on naming something that is no longer attached."
    js = builder.OUT.read_text()
    block = js[js.index('function paintAgentAttachments'):js.index('function closeAgentSuggest')]
    assert "input.value.replace(new RegExp(" in block
    assert 'lee.agentSelections.splice' in block, 'a selection chip is removable too'


def test_a_selection_reaches_the_agent_panel_as_a_queued_context():
    js = builder.OUT.read_text()
    block = js[js.index('function leeAgentSelection'):js.index('async function leeAgentBudget')]
    assert "kind: 'selection'" in block and 'doc.sliceString' in block
    assert "leeRight('agent')" in block, 'the panel comes forward so the chip is visible'
    assert 'agent_selection: () => leeAgentSelection()' in js, 'and it is a bindable action'


def test_an_interpreters_libraries_are_not_the_project(tmp_path):
    """98% of a walk of this repo was site-packages, so `@keys` ranked `libxslt/keys.h` over
    `leela/core/keys.py` and the 20k cap was spent before the project was reached.

    A virtualenv is not always called `.venv` -- this repo has `packaging/.app-venv` -- so the
    skip matches the shape rather than the one name.
    """
    for d in ('.venv', '.app-venv', 'my-venv', 'venv-3.12'):
        lib = tmp_path/d/'lib'/'python3.12'/'site-packages'/'lxml'
        lib.mkdir(parents=True)
        (lib/'keys.h').write_text('/* not your code */\n')
    (tmp_path/'keys.py').write_text('KEYS = 1\n')
    # A folder that merely *contains* the word is still the project's.
    (tmp_path/'conventions').mkdir(); (tmp_path/'conventions'/'keys.py').write_text('X = 1\n')

    ws = Workspace(roots=[tmp_path])
    walked = [str(p) for p in ws.fs.walk(tmp_path)]
    assert not [p for p in walked if 'site-packages' in p], walked[:3]
    assert len(walked) == 2, walked
    assert any(p.endswith('conventions/keys.py') for p in walked), 'not an over-eager skip'


def test_a_site_packages_under_an_oddly_named_venv_is_still_skipped(tmp_path):
    "The inner skip is the backstop for a venv folder named something nobody predicted."
    lib = tmp_path/'weird'/'lib'/'site-packages'/'pkg'
    lib.mkdir(parents=True)
    (lib/'mod.py').write_text('x = 1\n')
    (tmp_path/'mine.py').write_text('y = 2\n')
    ws = Workspace(roots=[tmp_path])
    assert [p.name for p in ws.fs.walk(tmp_path)] == ['mine.py']


def test_the_file_suggest_is_coalesced():
    "Each call walks the project tree; dropping the answer discards the work after doing it."
    js = builder.OUT.read_text()
    assert 'clearTimeout(agentSuggestTimer)' in js and 'agentSuggestTimer = setTimeout(' in js
