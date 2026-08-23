"The web block end to end: routes, themes and the served bundle."

from __future__ import annotations
from pathlib import Path
from fasthtml.common import first, to_xml
from starlette.testclient import TestClient
from leela.blocks.term.term import TerminalGate
from leela.app import _shell, ide_app
from leela.workspace import Workspace
ROOT = Path(__file__).resolve().parents[2]
import re
from fastcore.all import L
import re, sys
from collections import Counter
from fastcore.all import L, Path

JS = (ROOT / 'leela/static/lee-ide.js').read_text()
CSS = (ROOT / 'leela/static/lee-ide.css').read_text()

def test_modals_stay_in_the_viewport_and_lock_scroll_as_a_stack():
    overlays = (ROOT / 'leela/static/js/20_overlays.js').read_text()
    assert 'function modalViewport()' in overlays
    assert 'function fitModal(' in overlays
    assert 'v?.width' in overlays and 'v?.height' in overlays
    assert 'document.body.dataset.leeModalOverflow' in overlays
    assert "$$('.lee-modal').length" in overlays
    assert 'fitModal(m)' in overlays
    assert 'v.left + Math.max(0, v.width - width)' in overlays
    assert 'innerWidth - width' not in overlays and 'innerHeight - height' not in overlays
    assert 'max-width: calc(100dvw - 16px)' in CSS
    assert 'max-height: calc(100dvh - 16px)' in CSS


def test_note_editors_wrap_without_changing_code_editor_preferences():
    agent = (ROOT / 'leela/static/js/12_agent.js').read_text()
    editor = agent[agent.index('const stateView = createEditor(textHost'):agent.index('const noteText =')]
    assert "settings: {wordWrap: 'viewport'}" in editor
    assert '.lee-memory-note-cm .cm-content' in CSS
    assert 'overflow-wrap: anywhere' in CSS
    assert '.lee-vault-text' in CSS and 'overflow-wrap: anywhere' in CSS[CSS.index('.lee-vault-text'):]


def test_cursor_theme_is_default_and_keeps_light_dark_system():
    assert "const THEME_DEFAULT = 'cursor:light:tight'" in JS
    assert "localStorage.getItem('lee-theme')" in JS
    assert ':root[data-theme="cursor"][data-mode="light"]' in CSS
    assert ':root[data-theme="cursor"][data-mode="dark"]' in CSS
    assert 'thin quiet chrome' in JS
    assert ':root[data-density="tight"] .lee-btn.go' in CSS
    assert ':root[data-density="tight"] .lee-phead' in CSS
    assert ':root[data-density="tight"] .lee-node.sel' in CSS

def test_file_click_sets_the_same_selected_state_as_keyboard_navigation(tmp_path):
    "Mouse opens used to stopPropagation without painting `.sel`; keys already did."
    from leela.blocks.fs.ui import tree_node as _tree_node
    (tmp_path / 'alpha.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    file_entry = first(ws.fs.ls(str(tmp_path)))
    html = to_xml(_tree_node(file_entry))
    assert 'leeOpenFile(' in html
    open_fn = JS[JS.index('async function leeOpenFile'):JS.index('window.leeOpenFile')]
    assert 'selectTreeNode(treeNode)' in open_fn, 'paint before the await, so the click feels instant'
    assert 'selectTreeNode(after)' in open_fn, 'and again after the tab bar swaps'
    assert 'function selectTreeNode(n)' in JS
    assert "n.classList.add('sel')" in JS
    assert 'window.selectTreeNode = selectTreeNode' in JS

def test_source_control_refreshes_when_the_working_directory_switches():
    "Which repository a panel asks about travels in `gitUI.repo`, via `gitUrl`."
    assert 'function gitUrl(path, params = {})' in JS
    assert "if (gitUI.repo) q.set('repo', gitUI.repo)" in JS
    assert 'gitUI.repoRoot' not in JS, 'one root-tracking field, not two'
    assert 'function scmPanelOpen()' in JS and 'function refreshScmIfOpen(' in JS
    cwd = JS[JS.index('async function leeCwd'):JS.index('window.leeCwd')]
    assert 'refreshScmIfOpen()' in cwd, 'a new cwd can imply a different repository'
    branch = JS[JS.index('async function leeBranchMenu'):JS.index('window.leeBranchMenu')]
    assert "gitInfo(gitUrl('/git/info'))" in branch, 'and through the guard, not bare `api`' 
    assert "async def git_info(repo: str = '')" in (ROOT / 'leela/blocks/git/app.py').read_text()

def test_nbdev_prepare_uses_settings_ini_and_initialises_uv(tmp_path):
    (tmp_path / 'settings.ini').write_text(
        '[DEFAULT]\nlib_name = demo\nlib_path = demo\nnbs_path = nbs\n')
    (tmp_path / 'nbs').mkdir()
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/project/nbdev_prepare', json={})
        body = r.json()
        assert r.status_code in (200, 400)
        if body.get('ok'):
            assert body['root'] == str(tmp_path)
            assert body['nbs_path'] == 'nbs'
        else:
            assert 'nbdev' in body.get('error', '').lower() or 'uv' in body.get('error', '').lower() \
                or 'settings.ini' in body.get('error', '').lower()
    assert "leeNbdevPrepare" in JS
    assert "'nbdev prepare…'" in JS or 'nbdev prepare…' in JS
    assert '/project/nbdev_prepare' in JS

def test_shell_still_exposes_workspace_and_git_switchers(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'id="workspacepill"' in html and 'leeWorkspaceMenu(this)' in html
    assert 'id="gitpill"' in html and 'leeBranchMenu(this)' in html
    assert 'data-left="git"' in html

def test_the_committed_bundle_is_the_modules_it_was_built_from():
    assert 'focus_agent:' in JS
    assert "leeRight('agent')" in JS
    assert "$('#agentprompt')?.focus()" in JS
    assert "applyTheme('cursor')" in (ROOT / 'tools/webshots.py').read_text()
    assert "leeAct('focus_agent')" in (ROOT / 'tools/webshots.py').read_text()
    assert [p.name for p in builder.modules() if not p.read_text().endswith('\n')] == []
    names = L(builder.modules()).map(lambda p: set(_DECL.findall(p.read_text())))
    dupes = sorted(n for n, c in Counter(n for s in names for n in s).items() if c > 1)
    assert dupes == [], f'declared in more than one module: {dupes}'
    assert builder.OUT.read_text() == builder.bundle(), 'run python tools/build_ide_js.py'
    js = builder.OUT.read_text()
    for fn in ('function leeAct', 'function leeLeft', 'function leeRight', 'function leePane'): assert fn in js, fn


JS = (ROOT/'leela/static/lee-ide.js').read_text()
CSS = (ROOT/'leela/static/lee-ide.css').read_text()

TOKENS = set('bg bg1 bg2 bg3 fg fg2 fg4 border accent sel selection-fg red green yellow orange blue '
             'purple aqua output warning log active-line bracket guide'.split())
BLOCK = re.compile(r'([^{}]*?)\{([^{}]*?)\}', re.S)
VARIANT = re.compile(r':root\[data-theme="(\w+)"\]\[data-mode="(dark|light)"\]\s*$')

def css_variants():
    "family, mode -> the --lee-* names that variant's block declares."
    out = {}
    for sel, body in BLOCK.findall(CSS):
        for one in sel.split(','):
            if m := VARIANT.search(one.strip()):
                out[m.groups()] = set(re.findall(r'--lee-([\w-]+):', body))
    return out

def js_families():
    "The family names in the JS THEMES table."
    table = JS.split('const THEMES = {', 1)[1].split('\n};', 1)[0]
    return set(re.findall(r'^\s*(\w+):\s*\{', table, re.M))

def test_every_theme_variant_declares_every_token_in_both_modes():
    import itertools
    variants = css_variants()
    families = js_families()
    assert families >= {'leela', 'cursor', 'vscode', 'jetbrains', 'solarized', 'gruvbox', 'nord', 'dracula'}
    assert {f for f, _ in variants} == families, 'a family exists in only one of CSS and JS'
    for family in families:
        assert (family, 'dark') in variants and (family, 'light') in variants, family
    for (family, mode), names in css_variants().items():
        assert not (TOKENS - names), f'{family}/{mode} is missing {sorted(TOKENS - names)}'
    assert 'var(--lee-space-mark)' in CSS.split('.cm-lee-space-mark')[1].split('}')[0]
    assert 'var(--lee-space-mark)' in CSS.split('.cm-lee-tab-mark')[1].split('}')[0]
    for (family, mode), names in css_variants().items():
        assert 'space-mark' in names, f'{family}/{mode}'
    assigns = L(re.findall(r'colorScheme\s*=\s*([^;\n]+)', JS + (ROOT/'leela/app.py').read_text()))
    assert assigns, 'nothing sets colorScheme any more'
    for a in assigns: assert a.strip() in ('resolved', 'resolved;'), a
    app = (ROOT/'leela/app.py').read_text()
    assert 'dataset.density' in app and 'dataset.density' in JS
    for value in re.findall(r'dataset\.density\s*=\s*([^;\n]+)', JS):
        assert value.strip() == 'density'
    for reader in (JS, (ROOT/'leela/app.py').read_text()):
        assert "dark: 'leela:dark:relaxed'" in reader and "cursor: 'cursor:light:tight'" in reader
    for (fam, mode), tokens in variant_colours().items():
        for a, b in [*itertools.combinations(LEGEND, 2), ('blue', 'purple')]:
            assert tokens[a].lower() != tokens[b].lower(), f'{fam} {mode}: {a} and {b} are both {tokens[a]}'
            assert _dE(tokens[a], tokens[b]) > 5, f'{fam} {mode}: {a} and {b} are indistinguishable'





def test_density_is_its_own_axis_and_carries_the_chrome():
    "Tight chrome came from the cursor theme, but any family must be able to wear it."
    assert ':root[data-density="tight"] .lee-phead' in CSS
    assert ':root[data-density="tight"] .lee-node.sel' in CSS
    keyed = re.findall(r':root\[data-density="tight"\](\[data-mode="\w+"\])?\s+\.lee-', CSS)
    assert keyed and not all(keyed)
    assert re.findall(r':root\[data-theme="\w+"\]\s+\.lee-', CSS) == []
    assert "const THEME_DENSITIES = ['tight', 'relaxed']" in JS



def _lab(hex_):
    "sRGB hex to CIE Lab, so two colours can be compared the way an eye compares them."
    h = hex_.strip().lstrip('#')
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
    r, g, b = f(r), f(g), f(b)
    X, Y, Z = (.4124*r + .3576*g + .1805*b)/.95047, .2126*r + .7152*g + .0722*b, (.0193*r + .1192*g + .9505*b)/1.08883
    k = lambda t: t ** (1/3) if t > .008856 else 7.787 * t + 16/116
    X, Y, Z = k(X), k(Y), k(Z)
    return 116*Y - 16, 500*(X - Y), 200*(Y - Z)

def _dE(a, b): return sum((x - y) ** 2 for x, y in zip(_lab(a), _lab(b))) ** .5

LEGEND = ('accent', 'aqua', 'orange', 'green', 'blue')

def variant_colours():
    "family, mode -> the declared `--lee-*` values, not just their names."
    out = {}
    for sel, body in BLOCK.findall(CSS):
        for one in sel.split(','):
            if m := VARIANT.search(one.strip()):
                out[m.groups()] = {k: v.strip() for k, v in re.findall(r'--lee-([\w-]+):\s*([^;]+);', body)}
    return out


sys.path.insert(0, str(ROOT/'tools'))

import build_ide_js as builder  # noqa: E402


_DECL = re.compile(r'^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(', re.M)




def test_the_empty_state_is_written_only_in_python():
    "`mountTab` clones `#leeempty`; a second copy in JS is the drift that put them out of step."
    from fasthtml.common import to_xml
    from leela.app import _editor_pane
    js = builder.OUT.read_text()
    assert 'lee-empty-features' not in js and '#leeempty' in js
    html = to_xml(_editor_pane(_NoTab()))
    assert '<template id="leeempty">' in html and 'lee-empty-features' in html

class _NoTab:
    tab = None

def test_the_branch_pill_and_its_icons_have_handlers_in_the_bundle():
    "The header renders these four names inline; a missing one is a dead control in the top bar."
    from fasthtml.common import to_xml
    from leela.app import _header
    from leela.workspace import Workspace
    js, html = builder.OUT.read_text(), to_xml(_header(Workspace(roots=[])))
    for name in ('leeBranchMenu', 'leeGitQuick'):
        assert f'function {name}' in js, name
        assert name in html, name
    for name in ('leeCloneRepo', 'switchBranch', 'branchActions'): assert f'function {name}' in js, name

def test_a_structured_refusal_shows_its_message_rather_than_the_http_status():
    """Thread-aware routes answer with `code` and `message` and no `error`, so a client reading only
    `error` showed a person the word "Conflict" instead of the sentence it was sent."""
    core = (ROOT / 'leela/static/js/00_core.js').read_text()
    throw = core[core.index('async function api('):core.index('const post =')]
    assert 'body.error || body.message' in throw


def test_a_dropped_stream_carries_no_data_to_parse():
    """`EventSource` fires `error` both for a dead socket and for a frame the server named `error`.
    Only one of them has data, and parsing the other threw before the handler could run."""
    js = (ROOT / 'leela/static/js/12_agent.js').read_text()
    dedupe = js[js.index('const dedupe = fn =>'):js.index("es.addEventListener('activity'")]
    assert "typeof ev.data !== 'string'" in dedupe and 'catch (_) { return; }' in dedupe


def test_agent_timeline_orders_prose_and_calls_and_folds_delegate_children():
    import json, subprocess
    js = (ROOT / 'leela/static/js/12_agent.js').read_text()
    start, end = js.index('function reduceAgentTimeline('), js.index('function agentTimeline(')
    reducer = js[start:end]
    events = [
        {'event': 'chunk', 'data': {'text': 'before '}},
        {'event': 'chunk', 'data': {'text': 'call'}},
        {'event': 'activity', 'data': {'id': 'child', 'parent_action_id': 'parent', 'summary': 'child'}},
        {'event': 'activity', 'data': {'id': 'parent', 'summary': 'delegate'}},
        {'event': 'chunk', 'data': {'text': 'after'}},
        {'event': 'activity', 'data': {'id': 'loose', 'parent_action_id': 'missing', 'summary': 'loose'}},
        {'event': 'activity', 'data': {'id': 'parent', 'done': True, 'ok': True}},
        {'event': 'done', 'data': {'ok': True}},
    ]
    script = reducer + f"\nconsole.log(JSON.stringify(reduceAgentTimeline({json.dumps(events)})))"
    parts = json.loads(subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True).stdout)
    assert [(p['kind'], p.get('id'), p.get('text')) for p in parts] == [
        ('prose', None, 'before call'), ('activity', 'parent', None),
        ('prose', None, 'after'), ('activity', 'loose', None), ('done', None, None)]
    assert [child['id'] for child in parts[1]['children']] == ['child']
    assert parts[1]['data']['done'] is True, 'an update changes one call rather than appending another'


def test_history_and_resync_use_the_same_timeline_reducer_as_live_delivery():
    js = (ROOT / 'leela/static/js/12_agent.js').read_text()
    history = js[js.index('function renderTurns('):js.index('const sessionTime')]
    resync = js[js.index("es.addEventListener('resync'"):js.index("es.addEventListener('done'")]
    assert 'reduceAgentTimeline(' in history, 'durable history cannot guess live call/prose ordering'
    assert 'renderTurns(log, turns' in resync, 'resync must enter the same history renderer'


def test_thread_header_controls_have_handlers_and_preserve_each_draft():
    from fasthtml.common import to_xml
    from leela.app import _agent_panel
    from leela.workspace import Workspace
    html = to_xml(_agent_panel(Workspace(roots=[])))
    js = (ROOT / 'leela/static/js/12_agent.js').read_text()
    # the head offers one control and a count; the per-conversation actions live on the cards, so
    # they act on the conversation a person pointed at rather than on whichever one was showing
    assert 'leeAgentThreadsToggle' in html and 'leeAgentNew' in html
    assert 'agentthreadlist' in html and 'live conversations' in html
    assert 'lee-select' not in html.split('agentthreadlist')[0].split('agentthreads')[-1]
    for name in ('leeAgentThreadSwitch', 'leeAgentNew', 'leeAgentThreadRename', 'leeAgentThreadClose',
                 'leeAgentThreadOpen', 'leeAgentThreadMute'):
        assert f'function {name}' in js, name
    cards = js[js.index('function bindAgentThreadCards('):js.index('function leeAgentThreadsToggle(')]
    for hook in ('data-thread-rename', 'data-thread-mute', 'data-thread-close'):
        assert hook in js, hook
    assert 'leeAgentThreadOpen(id)' in cards and "e.key !== 'Enter'" in cards, 'mouse and keyboard'
    # a draft is the browser's alone, so it is kept per conversation; the transcript is the
    # server's, and caching that innerHTML is what left a switched-to conversation blank
    assert 'agentThreadDrafts.set' in js and 'agentThreadViews' not in js
    assert '/agent/thread/switch' in js and '/agent/thread/close' in js


def test_stop_and_send_next_is_reachable_without_the_keyboard():
    "A chord is the only route to force otherwise, and the send control is where the mode is shown."
    app = (ROOT / 'leela/app.py').read_text()
    assert "onclick='sendAgent(event.shiftKey)'" in app
    js = (ROOT / 'leela/static/js/12_agent.js').read_text()
    mode = js[js.index('function updateAgentSendMode('):js.index('function setQueuedSteer(')]
    assert 'shift-click' in mode, 'and the button says so'
    assert "return status('nothing is running to stop" in js, 'a chord that does nothing says why'
    assert "return status('write what to steer towards first'" in js

def _reduce(events):
    "Run the shipped reducer under Node so the test reads the same code the browser does."
    import json, subprocess
    js = (ROOT / 'leela/static/js/12_agent.js').read_text()
    body = js[js.index('function reduceAgentTimeline('):js.index('function agentTimeline(')]
    script = body + f'\nconsole.log(JSON.stringify(reduceAgentTimeline({json.dumps(events)})))'
    out = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_an_update_to_a_call_already_on_screen_does_not_split_the_prose():
    """The live renderer seals the open block only when a call is seen for the first time. If the
    reducer sealed on updates too, replay would break one answer into several where live kept it
    whole -- and the two paths are meant to produce the same transcript."""
    parts = _reduce([
        {'event': 'chunk', 'data': {'text': 'before '}},
        {'event': 'activity', 'data': {'id': 'a1', 'tool': 'view_file'}},
        {'event': 'chunk', 'data': {'text': 'after '}},
        {'event': 'activity', 'data': {'id': 'a1', 'tool': 'view_file', 'done': True}},
        {'event': 'chunk', 'data': {'text': 'and more'}}])
    kinds = [part['kind'] for part in parts]
    assert kinds == ['prose', 'activity', 'prose'], kinds
    assert [p['text'] for p in parts if p['kind'] == 'prose'] == ['before ', 'after and more']


def test_a_call_with_no_identity_is_still_shown():
    "A row we cannot key is still work a person did; dropping it hides a call that ran."
    parts = _reduce([{'event': 'activity', 'data': {'tool': 'run_shell'}},
                     {'event': 'chunk', 'data': {'text': 'done'}}])
    assert [part['kind'] for part in parts] == ['activity', 'prose']
    assert parts[0]['data']['tool'] == 'run_shell'


def test_a_delegates_delegate_is_folded_under_it_and_not_lost():
    "Three levels: the reducer nests recursively, so every consumer has to descend recursively too."
    parts = _reduce([
        {'event': 'activity', 'data': {'id': 'root', 'tool': 'delegate'}},
        {'event': 'activity', 'data': {'id': 'kid', 'parent_action_id': 'root', 'tool': 'delegate'}},
        {'event': 'activity', 'data': {'id': 'grandkid', 'parent_action_id': 'kid', 'tool': 'view_file'}}])
    assert len(parts) == 1 and parts[0]['id'] == 'root'
    kid = parts[0]['children'][0]
    assert kid['id'] == 'kid' and [c['id'] for c in kid['children']] == ['grandkid']
    js = (ROOT / 'leela/static/js/12_agent.js').read_text()
    history = js[js.index('function renderTurns('):js.index('const sessionTime')]
    assert 'paintActivity(child)' in history, 'and history paints the whole tree, not one level'


def test_a_turn_that_ends_on_a_call_still_shows_its_pictures():
    "There is no prose block to hang them on, and the pictures are still that turn's own."
    js = (ROOT / 'leela/static/js/12_agent.js').read_text()
    done = js[js.index("es.addEventListener('done'"):]
    done = done[:done.index('await reloadAfterEdits')]
    assert 'const closing = body || timelineRoot' in done
    assert 'drawTurnMedia(closing, d.media)' in done and 'addResponseRevision(closing' in done


def test_one_sequence_delivered_twice_has_one_effect():
    "Reconnect and a second tab both replay; a repeated sequence must not append the text again."
    import json, subprocess
    js = (ROOT / 'leela/static/js/12_agent.js').read_text()
    dedupe = js[js.index('const dedupe = fn =>'):js.index("es.addEventListener('activity'")]
    script = ('let lastSeq = 0, raw = "";\n' + dedupe.replace('const dedupe', 'var dedupe') +
              'const on = dedupe(d => { raw += d.text; });\n'
              'const frame = seq => ({data: JSON.stringify({seq, text: "x"})});\n'
              'on(frame(1)); on(frame(1)); on(frame(2)); on(frame(2));\n'
              'on({});\n'
              'console.log(JSON.stringify({raw, lastSeq}))')
    out = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == {'raw': 'xx', 'lastSeq': 2}

def test_the_markdown_cell_action_is_absent_until_a_notebook_is_focused():
    """It inserts a reply into the open notebook, so with a `.py` tab focused it was a control that
    was always there, usually inert, and only said so after a click. It is hidden instead, and the
    tab-change hook that already shows and hides the run controls brings it back."""
    core = (ROOT / 'leela/static/js/00_core.js').read_text()
    state = core[core.index('function markdownCellActionState('):core.index('function refreshMarkdownCellActions(')]
    assert "const ready = lee.kind === 'notebook'" in state
    assert 'bar.hidden = !ready' in state, 'hidden, not merely disabled'
    assert 'button.disabled = !ready' in state, 'and inert even if something un-hides it'
    assert 'open a notebook tab' not in state, 'nothing to explain once it is not offered'
    assert 'markdownCellActionState(button)' in core, 'set when the reply is drawn'
    editor = (ROOT / 'leela/static/js/04_editor.js').read_text()
    hook = editor[editor.index('function updateToolbarForKind('):editor.index('function saveTabLocation(')]
    assert 'refreshMarkdownCellActions()' in hook, 'and re-evaluated when the focused tab changes'
    assert '.lee-reply-actions[hidden] { display: none; }' in CSS

def test_the_keymap_editor_is_a_form_that_takes_keystrokes_and_warns_before_saving():
    """It was a raw JSON textarea: you had to know the chord grammar, and a clash only surfaced as a
    server note after saving. A row per action, a field that records the keystroke itself, and the
    server's own check on every change."""
    js = (ROOT / 'leela/static/js/07_keymap_bind.js').read_text()
    assert 'function chordFromEvent(' in js
    chord = js[js.index('function chordFromEvent('):js.index('async function editKeys(')]
    assert "parts.push('mod')" in chord and "parts.push('ctrl')" in chord, 'mod is the platform key'
    assert 'CHORD_SKIP.has(e.key)' in chord, 'a bare modifier is not a chord'
    editor = js[js.index('async function editKeys('):js.index('function remountEditors(')]
    assert 'data-record' in editor and "classList.add('recording')" in editor, 'it takes a keystroke'
    assert "post('/keys/check'" in editor, 'and the server says what conflicts'
    assert "status(r.notes[0], 'err')" in editor, 'a clash is a notification, not a silent note'
    assert 'keysearch' in editor and 'nothing matches' in editor, 'and it is filterable'
    assert 'lee-keyedit' not in editor, 'no raw JSON textarea as the primary surface'
    assert 'keyjson' in editor, 'though the JSON is still one click away'
    assert '.lee-keyrow-chord.recording' in CSS


def test_the_conflict_check_is_the_same_one_the_save_runs(tmp_path):
    """Two implementations of what conflicts would drift, and the editor would warn about something
    the save then allowed, or stay quiet about something it refused."""
    from starlette.testclient import TestClient
    app = (ROOT / 'leela/blocks/keys/app.py').read_text()
    check = app[app.index("@rt('/keys/check')"):app.index("@rt('/keys/reset')")]
    assert 'keymap.apply_overrides' in check, 'the save path\'s own validation, not a copy'
    assert 'keymap.DEFAULTS' in check and 'notes' in check
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        assert client.post('/keys/check', json={'keys': {'agent_send': 'mod+j'}}).json()['ok']
        clash = client.post('/keys/check', json={'keys': {'agent_send': 'alt+shift+c'}}).json()
        assert clash['ok'] is False and 'conflicts' in clash['notes'][0]
        assert 'agent_stop' in clash['notes'][0], 'and it names what it collides with'
        junk = client.post('/keys/check', json={'keys': {'agent_send': 'not+a+chord'}}).json()
        assert junk['ok'] is False and 'unknown modifier' in junk['notes'][0]
        assert client.post('/keys/check', json={'keys': {'agent_send': ''}}).json()['ok'], 'unbinding is fine'
        assert client.post('/keys/check', json={'keys': 'nope'}).status_code == 400



def test_the_agent_can_be_pointed_at_ramabanas_own_config_dir(tmp_path, monkeypatch):
    """Ramabana writes the log and its sidecars from the same code Leela drives, so one folder can
    serve both surfaces. Empty keeps every existing install exactly where it was."""
    from leela.blocks.settings.settings import Settings, agent_cfg
    import leela
    settings = Settings(user_path=tmp_path/'settings.json')
    assert agent_cfg(settings) == Path(leela.leela_cfg), 'empty means Leela\'s own config dir'
    shared = tmp_path/'shared'/'ramabana'
    settings.save('user', 'agent', {'configFolder': str(shared)})
    assert agent_cfg(settings) == shared and shared.is_dir(), 'and it is made, not just named'
    settings.save('user', 'agent', {'configFolder': '~'})
    assert agent_cfg(settings) == Path.home(), 'a home-relative folder is expanded'
    try: settings.save('user', 'agent', {'nope': 1})
    except ValueError as e: assert 'unknown setting' in str(e)
    else: assert False, 'an unknown key is refused, not written'


def test_a_workspace_assistant_and_its_backups_follow_that_folder(tmp_path, monkeypatch):
    "Moving the log without moving the copies taken of it would protect an empty file."
    from leela.blocks.settings import settings as S
    from leela.core import backups as B
    from leela.workspace import Workspace
    shared, project = tmp_path/'shared', tmp_path/'project'
    project.mkdir()
    monkeypatch.setattr(S, 'leela_cfg', tmp_path/'leela')
    S.Settings().save('user', 'agent', {'configFolder': str(shared)})
    ws = Workspace(roots=[project])
    try:
        assert Path(ws.ai.history_path) == shared/'agent-history.jsonl'
        assert B.agent_source(tmp_path/'leela') == shared
        assert B.entry_source('agent-history.jsonl', tmp_path/'leela', B.agent_source()) == shared/'agent-history.jsonl'
        assert B.entry_source('keys.json', tmp_path/'leela') == tmp_path/'leela'/'keys.json', 'only the agent moves'
    finally: ws.threads.shutdown()
