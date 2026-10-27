"The web IDE surface: project tools, movement, tabs, cells and workspaces."

from leela.workspace import Workspace
from pathlib import Path
import json
from starlette.testclient import TestClient
from leela.app import ide_app
import asyncio
import time
from unittest.mock import Mock
import pytest
from leela.hub import (OPEN_PATH, LoopbackHostGuard, WorkspaceHub, WorkspaceSite,
                       assign_slugs, cfg_mark)


def test_a_pyproject_is_annotated_from_the_venv_beside_it(tmp_path):
    """One interpreter answered for every open project at once."""
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


def test_a_window_is_pointed_at_the_host_the_server_will_answer_to(tmp_path):
    "`serve_ide` slugs resolved roots, so a symlinked folder must not be slugged by its link."
    from leela.hub import workspace_urls
    (tmp_path/'real-name').mkdir()
    (tmp_path/'link').symlink_to(tmp_path/'real-name')
    assert workspace_urls([tmp_path/'link'], 5001) == ['http://real-name.localhost:5001/']


@pytest.mark.parametrize('loose', [False, True])
def test_relative_tab_open_uses_the_project_root_and_keeps_the_sandbox(tmp_path, loose):
    first, project = tmp_path/'first', tmp_path/'project'
    first.mkdir(); project.mkdir()
    target = project/'reply.py'; target.write_text('reply = 1\n')
    outside = tmp_path/'outside.py'; outside.write_text('outside = 1\n')
    ws = Workspace(roots=[first, project]); ws.activate_root(project)
    if loose: ws.fs.loose = first
    with TestClient(ide_app(ws)) as client:
        opened = client.post('/tab/open', params={'path': 'reply.py'})
        assert 'lee-err' not in opened.text, opened.text
        assert ws.tab.path == str(target.resolve())
        refused = client.post('/tab/open', params={'path': '../outside.py'})
        assert 'outside the open folders' in refused.text, refused.text
        assert ws.tab.path == str(target.resolve())
        assert not ws.fs.admitted
        assert 'lee-err' not in client.post('/tab/open', params={'path': str(target)}).text


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


def test_the_compressor_leaves_an_event_stream_alone(tmp_path):
    "GZip went on the app for the cold load. Buffering the streams would have paid for it."
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        r = client.get('/search/stream', params={'q': ''}, headers={'accept-encoding': 'gzip'})
    assert r.status_code == 200 and r.text.startswith('event: start')
    assert 'content-encoding' not in r.headers, 'the stream was compressed, so it arrives at the end'


def test_screen_capture_route_rejects_oversized_payloads_before_decoding(tmp_path):
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        response = client.post('/screen', json={'data_url': 'data:image/png;base64,' + 'A' * 12_000_001})
    assert response.status_code == 413


def test_the_selection_agent_has_no_tool_that_could_change_anything(tmp_path):
    """The panel promises nothing changes until Replace."""
    from ramabana.tools import NO_SUB
    from shalya.core import ACTING_TOOLS, WRITE_TOOLS
    ws = Workspace(roots=[tmp_path])
    a = ws.selection_ai
    names = {t.__name__ for t in a.tools}
    assert not (names & WRITE_TOOLS), f'a write survived: {sorted(names & WRITE_TOOLS)}'
    assert not (names & ACTING_TOOLS), f'an effect survived: {sorted(names & ACTING_TOOLS)}'
    assert not (names & NO_SUB), 'it cannot delegate its way past the refusal'
    assert 'view_file' in names and 'search_code' in names, 'it can still look'
    assert a.approvals is None, 'nothing is gated because nothing needs gating'
    assert ws._threads is None, 'building it must not build the agent pane behind the scenes'
    assert {t.__name__ for t in ws.inline_ai.tools} & WRITE_TOOLS, 'prompt cells keep their writes'


def test_untrusted_markdown_cannot_execute_raw_html(tmp_path):
    """Without `allow_raw` the tag is escaped; with it the tag stays but its handler is stripped."""
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as client:
        raw = '```{=html}\n<img src=x onerror=alert(1)>\n```'
        safe = client.post('/markdown/render', json={'text': raw, 'allow_raw': False}).json()['html']
        trusted = client.post('/markdown/render', json={'text': raw, 'allow_raw': True}).json()['html']
    import re   # fastpylight, which ramabana 0.2.5's `[cli]` brings, highlights the escaped tag into spans
    assert '<img' not in safe and '&lt;img src=x onerror=alert(1)&gt;' in re.sub(r'<[^>]+>', '', safe), safe
    assert '<img' in trusted and 'onerror' not in trusted, 'an explicit `{=html}` block keeps its markup, never its handlers'


def test_resuming_a_history_session_puts_its_turns_back_into_the_model_context(tmp_path):
    "History showed the turns and left the model with none of them."
    ws = Workspace(roots=[tmp_path])
    model = ws.ai.model.name
    turns = [{'session': 'agent-a', 'at': 1, 'model': model, 'prompt': 'remember cedar', 'reply': 'noted'},
             {'session': 'agent-a', 'at': 2, 'model': model, 'prompt': 'what was it?', 'reply': 'cedar'}]
    # a resumed thread builds its own assistant and reads the log, so the session has to be in it
    import json as _json
    from tests.conftest import history_file
    path = history_file(ws)
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


def test_model_selector_endpoint_exposes_sources_not_secrets(monkeypatch):
    from leela.agent import core as models
    monkeypatch.setenv('OPENAI_API_KEY', 'top-secret')
    models.forget_probes()
    import ramabana.models as rm
    monkeypatch.setattr(rm, 'LIVE', {'openai': lambda: ['gpt-5.4']})
    with TestClient(ide_app(Workspace(roots=[]))) as client:
        data = client.get('/agent/models').json()
    assert any(m['value'] == 'openai/gpt-5.4' for m in data['models'])
    assert data['auth']['openai']['source'] == 'OPENAI_API_KEY'
    assert 'top-secret' not in str(data)


def _nb(path, source):
    path.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [{
        'cell_type': 'code', 'source': source, 'metadata': {}, 'outputs': [],
        'execution_count': None, 'id': path.stem,
    }]}))


def test_a_restored_file_is_dropped_from_every_tab_holding_it_not_only_the_active_one(tmp_path):
    """A rolled-back turn restores files wherever they happen to be open, and `/tab/reload` refused every path but the active tab's."""
    a, b = tmp_path/'a.ipynb', tmp_path/'b.ipynb'
    _nb(a, 'value = "before"'); _nb(b, 'value = "before"')
    ws = Workspace(roots=[tmp_path]); ws.open(a); ws.open(b)
    with TestClient(ide_app(ws)) as client:
        for p in (b, a):                    # both looked at, so the server holds a document for each
            client.post('/tab/open', params={'path': str(p)})
            assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "before"'
        _nb(b, 'value = "restored"')         # b is the tab nobody is looking at, and it is clean
        dropped = client.post('/tab/reload', json={'paths': [str(b)]}).json()
        assert dropped['paths'] == [str(b)] and dropped['held'] == [], dropped
        client.post('/tab/open', params={'path': str(b)})
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "restored"'

        client.post('/tab/open', params={'path': str(a)})
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'notebook', 'i': 0,
                                         'text': 'value = "typed"'})
        client.post('/tab/open', params={'path': str(b)})   # left dirty, and then restored under it
        _nb(a, 'value = "restored"')
        held = client.post('/tab/reload', json={'paths': [str(a)]}).json()
        assert held['paths'] == [] and held['held'] == [str(a)], held
        client.post('/tab/open', params={'path': str(a)})
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "typed"', 'the typing was discarded'
        out = client.post('/tabs/save-all')
        assert not out.json().get('ok'), 'save-all wrote a draft that predates the restore'
        assert json.loads(a.read_text())['cells'][0]['source'] == 'value = "restored"', 'the restore was written over'


def test_save_all_rewrites_the_workspace_only_when_it_saved_something(tmp_path):
    """Every tab switch posted `/tabs/save-all`, and each answer rewrote `workspace.json` with nothing changed."""
    a = tmp_path/'a.py'; a.write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    saves = []; real = ws.save
    ws.save = lambda *x, **k: (saves.append(1), real(*x, **k))[1]
    with TestClient(ide_app(ws)) as client:
        client.post('/tab/open', params={'path': str(a)})
        n = len(saves)
        assert client.post('/tabs/save-all').json()['saved'] == 0 and len(saves) == n, 'a clean save-all wrote the workspace'
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'text', 'text': 'x = 2\n'})
        assert client.post('/tabs/save-all').json()['saved'] == 1 and len(saves) == n + 1
        assert a.read_text() == 'x = 2\n'


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


def test_cell_runs_carry_document_and_cell_identity_and_reject_stale_positions(tmp_path):
    notebook = tmp_path/'ordered.ipynb'; _nb(notebook, 'class Definition: pass')
    ws = Workspace(roots=[tmp_path]); ws.open(notebook)
    with TestClient(ide_app(ws)) as client:
        state = client.get('/tab/state').json()
        response = client.post('/nb/run/stream', json={
            'path': str(notebook), 'i': 0, 'id': 'a-cell-that-moved', 'source': 'pass',
        })
    assert response.status_code == 409


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
        t.join(5)
        assert held['a'].note == 'use the other file', 'answered where it was raised'


def test_naming_a_folder_reopens_that_folder_s_tabs_and_no_other_project_s(tmp_path):
    """`leela .` skipped the saved session entirely and always opened empty."""
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


def test_a_fully_qualified_host_reaches_the_workspace_it_names():
    "The dot is the DNS root, not a different workspace."
    from leela.hub import _host
    site = WorkspaceSite(slug='vruksha', name='vruksha', root='/w/vruksha', app=object())
    hub = WorkspaceHub([site], port=5001)
    assert _host({b'host': b'vruksha.localhost.:5001'}) == 'vruksha.localhost'
    got = hub.site_for({'type': 'http', 'headers': [(b'host', b'vruksha.localhost.:5001')]})
    assert got is site, 'the trailing dot is not part of the slug'

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
    # `vruksha.localhost.` is the same name written absolutely, and a browser sends it that way
    # when a search domain has made the short form ambiguous: choosing that workspace from the
    # folder list loaded a window that answered `invalid Host header`.
    absolute = asyncio.run(run([(b'host', b'vruksha.localhost.:5001'),
                                (b'origin', b'http://vruksha.localhost.:5001')]))
    assert called and not absolute, 'a fully qualified loopback name is that name'


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


def test_a_batch_too_big_to_send_asks_for_a_resync_instead_of_dropping_it(tmp_path):
    """Batches are deltas, not snapshots, so a truncated or dropped one is lost for good: the tree keeps showing files that are gone until something unrelated happens to touch it."""
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


def _one_cell_nb(src):
    return json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'cell_type': 'code', 'source': src, 'metadata': {}, 'outputs': [],
         'execution_count': None, 'id': 'c1'}]})

def test_an_open_notebook_does_not_resurrect_itself_over_newer_work(tmp_path):
    """`/tab/state` served the cached notebook stamped with the version now on disk, so the browser sent that back as its base, `/nb/save` found base and disk equal, and the old branch's cells overwrote the new ones."""
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


def _nb_json(cells):
    "A minimal notebook: (id, source, outputs) per cell."
    import json
    return json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {},
                       'cells': [{'cell_type': 'code', 'id': i, 'source': s, 'outputs': o,
                                  'execution_count': None, 'metadata': {}} for i, s, o in cells]})

def test_a_clean_run_over_the_notebook_does_not_block_a_source_edit(tmp_path):
    """`nbdev_clean` strips outputs and metadata; a browser save writes cell sources."""
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
        assert 'x = 999' in nb.read_text(), 'the disk version is left alone'
        forced = client.post('/nb/save', json={'path': str(nb), 'force': True,
                                               'base_disk_version': state['disk_version'],
                                               'cells': [{'i': 0, 'source': 'x = 11'}]})
        assert forced.status_code == 200, 'force still wins'


def _hub_get(hub, path, query=b''):
    "Drive one HTTP request through the hub and return `(status, json)`."
    sent = []
    async def send(m): sent.append(m)
    async def receive(): return {'type': 'http.request', 'body': b''}
    asyncio.run(hub({'type': 'http', 'path': path, 'query_string': query, 'headers': []},
                    receive, send))
    return sent[0]['status'], json.loads(sent[-1]['body'])

def test_a_folder_opened_while_leela_runs_becomes_its_own_workspace(tmp_path):
    """`open_folder` added a root to the window that was already open, so the second folder shared the first one's kernels, tabs and agent."""
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
    assert d['config'] == cfg_mark()


def test_opening_something_that_is_not_a_folder_is_refused_not_served(tmp_path):
    (f := tmp_path/'notes.py').write_text('x = 1\n')
    hub = WorkspaceHub([], 5001, build=lambda root, slug: None)
    for raw in (str(f), str(tmp_path/'gone'), ''):
        status, d = _hub_get(hub, OPEN_PATH, b'path=' + raw.encode())
        assert (status, d['ok']) == (400, False), raw
        assert d['config'] == cfg_mark(), 'a second launch tells its own Leela from one on another config dir by this'


def _real_hub(tmp_path):
    "A hub whose workspaces are real and each saves to its own state file."
    made = {}
    def build(root, slug):
        ws = made[slug] = Workspace(roots=[root])
        ws._state_path = tmp_path/f'{slug}.json'
        return WorkspaceSite(slug, Path(root).name, str(root), lambda *a: None, ws.open_external)
    return WorkspaceHub([], 5001, build=build), made


def test_a_file_handed_to_the_hub_opens_as_the_active_tab_and_is_saved(tmp_path):
    """Finder hands Leela a file, and `/hub/open` took only folders, so double-clicking a file opened nothing."""
    (proj := tmp_path/'proj').mkdir()
    (a := proj/'a.md').write_text('a\n'); (b := proj/'b.md').write_text('b\n')
    hub, made = _real_hub(tmp_path)
    for f in (a, b):
        status, d = _hub_get(hub, OPEN_PATH, f'path={proj}&file={f}'.encode())
        assert (status, d['ok']) == (200, True), d
    assert d['url'] == 'http://proj.localhost:5001/' and list(hub.sites) == ['proj'], 'both files, one workspace'
    ws = made['proj']
    assert [t.path for t in ws.tabs] == [str(a.resolve()), str(b.resolve())] and ws.tab.path == str(b.resolve())
    again = Workspace(roots=[proj]); again._state_path = tmp_path/'proj.json'
    assert again.reopen_saved_tabs() == 2 and again.tab.path == str(b.resolve()), 'the tab outlives the workspace'


def test_a_file_the_workspace_cannot_show_is_refused_before_anything_is_built(tmp_path):
    from leela.core import projects
    (proj := tmp_path/'proj').mkdir(); (other := tmp_path/'other').mkdir()
    (outside := other/'x.md').write_text('x\n'); (packed := proj/'a.zip').write_bytes(b'PK')
    hub, made = _real_hub(tmp_path)
    for f in (outside, packed, proj/'gone.md'):
        status, d = _hub_get(hub, OPEN_PATH, f'path={proj}&file={f}'.encode())
        assert (status, d['ok']) == (400, False), f
    assert not hub.sites and not made and not projects.recent_folders(), 'a refusal leaves no workspace, no recent entry'
    status, d = _hub_get(hub, OPEN_PATH)
    assert status == 400, 'the probe `leela_on` relies on still answers'


def _loose_hub(tmp_path):
    "A hub whose workspaces are real; the one rooted at the loose root is a loose-files workspace."
    from leela.core.projects import loose_root
    made = {}
    def build(root, slug):
        ws = made[slug] = Workspace(); ws.add_root(root, loose=Path(root) == loose_root())
        ws._state_path = tmp_path/f'{slug}.json'
        return WorkspaceSite(slug, Path(root).name, str(root), lambda *a: None, ws.open_external, ws.release)
    return WorkspaceHub([], 5001, build=build), made


def test_finder_open_with_a_loose_file_opens_it_and_refuses_what_it_should(tmp_path, monkeypatch):
    """A dotfile in the home folder has no workspace, so Open With opened nothing."""
    from leela.core import projects
    noted = []
    monkeypatch.setattr(projects, 'note_folder', noted.append)
    home = tmp_path/'home'; (ssh := tmp_path/'.ssh').mkdir(); home.mkdir()
    (rc := home/'.zshrc').write_text('x\n'); (packed := home/'a.zip').write_bytes(b'PK')
    (key := ssh/'id_ed25519').write_text('k')
    hub, made = _loose_hub(tmp_path); loose = projects.loose_root()
    for f in (home, packed, key, home/'gone'):
        status, d = _hub_get(hub, OPEN_PATH, f'path={loose}&file={f}'.encode())
        assert (status, d['ok']) == (400, False), f
    assert not hub.sites and not made, 'a refusal builds nothing'
    status, d = _hub_get(hub, OPEN_PATH, f'path={loose}&file={rc}'.encode())
    assert (status, d['ok']) == (200, True), d
    ws = made[d['id']]
    assert [t.path for t in ws.tabs] == [str(rc.resolve())] and ws.fs.covers(rc.resolve())
    assert not noted and not projects.recent_folders() and not projects.last_folders(), 'the loose folder is never remembered'


def test_opening_a_loose_file_in_a_checkout_drops_its_loose_tab(tmp_path):
    from leela.core import projects
    (proj := tmp_path/'proj').mkdir(); (a := proj/'a.md').write_text('a\n'); (b := proj/'b.md').write_text('b\n')
    hub, made = _loose_hub(tmp_path); loose = projects.loose_root()
    for f in (a, b): assert _hub_get(hub, OPEN_PATH, f'path={loose}&file={f}'.encode())[1]['ok']
    lws = made[hub.site_at(loose).slug]
    assert len(lws.tabs) == 2
    assert _hub_get(hub, OPEN_PATH, f'path={proj}&file={a}'.encode())[1]['ok']
    assert [t.path for t in lws.tabs] == [str(b.resolve())] and not lws.fs.covers(a.resolve())
    assert [t.path for t in made['proj'].tabs] == [str(a.resolve())]


def test_a_tab_opened_by_the_shell_is_pushed_to_the_page_that_is_listening(tmp_path):
    """The page learns of a server-opened tab over `/fs/events`, which it already holds open."""
    from leela.blocks.fs.fs import Sandbox
    from leela.blocks.fs.watch import Watcher
    async def run():
        w = Watcher(Sandbox([tmp_path]), step=50)
        q = w.subscribe()
        try:
            await asyncio.sleep(.3)
            while not q.empty(): q.get_nowait()
            await asyncio.to_thread(w.announce, tmp_path/'a.md')
            return await asyncio.wait_for(q.get(), 2)
        finally: w.close()
    assert asyncio.run(run()) == str(tmp_path/'a.md')

@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    "A keymap file of the test's own, and the global `KEYS` put back after."
    import leela.core.keys as keymap
    p = tmp_path/'cfg'/'keys.json'
    monkeypatch.setenv('LEELA_KEYMAP', str(p))
    keymap.reload()
    yield p
    keymap.reload(tmp_path/'gone.json')

def _chord(action):
    import leela.core.keys as keymap
    return keymap.lookup(action).key

def test_a_keymap_edit_on_disk_reaches_the_open_page_over_fs_events(tmp_path, keyfile):
    """Sanketa writes keys.json as text. Leela read it only at import or from its own panel, so the page kept the old chords until a restart."""
    import leela.core.keys as keymap
    ws = Workspace(roots=[tmp_path])
    ws.fs_watch.poll = .05
    app, got = ide_app(ws), []
    async def run():
        sent = asyncio.Event()
        async def send(m):
            if m['type'] == 'http.response.body' and b'event: keys' in m.get('body', b''): got.append(m['body']); sent.set()
        scope = {'type': 'http', 'method': 'GET', 'path': '/fs/events', 'raw_path': b'/fs/events', 'query_string': b'',
                 'headers': [(b'host', b'127.0.0.1')], 'scheme': 'http', 'server': ('127.0.0.1', 80), 'client': ('127.0.0.1', 1),
                 'root_path': '', 'http_version': '1.1'}
        never, asked = asyncio.Event(), []
        async def receive():
            if not asked: asked.append(1); return {'type': 'http.request', 'body': b'', 'more_body': False}
            await never.wait()
        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.sleep(.3)
            keyfile.parent.mkdir(parents=True, exist_ok=True)
            keyfile.write_text(json.dumps({'keys': {'run_cell': 'ctrl+y'}}))
            await asyncio.wait_for(sent.wait(), 5)
        finally:
            task.cancel()
            ws.fs_watch.close()
    asyncio.run(run())
    d = json.loads(got[0].decode().split('data: ', 1)[1])
    assert next(k for k in d['keys'] if k['action'] == 'run_cell')['key'] == 'ctrl+y', 'the push carries the new chord'
    assert {'keys', 'help', 'menus', 'bars', 'notes', 'path'} <= set(d), 'and all of what /keys.json returns'
    assert _chord('run_cell') == 'ctrl+y'
    with TestClient(ide_app(Workspace(roots=[]))) as c:
        assert next(k for k in c.get('/keys.json').json()['keys'] if k['action'] == 'run_cell')['key'] == 'ctrl+y'

def test_the_same_bytes_written_again_do_not_reload_the_keymap(keyfile, monkeypatch):
    "An Undo can put back the bytes Leela already holds. Only other bytes are a change."
    import leela.core.keys as keymap
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    keyfile.write_text(json.dumps({'keys': {'run_cell': 'ctrl+y'}}))
    assert keymap.refresh() and _chord('run_cell') == 'ctrl+y'
    calls = []
    monkeypatch.setattr(keymap, 'reload', lambda *a: calls.append(a))
    keyfile.write_text(json.dumps({'keys': {'run_cell': 'ctrl+y'}}))
    assert not keymap.changed() and not keymap.refresh() and not calls

def test_a_watcher_queues_nothing_for_the_same_bytes_and_one_event_for_other_bytes(tmp_path, keyfile):
    "The poll thread compares content, so a rewrite of the same bytes is quiet."
    from leela.blocks.fs.fs import Sandbox
    from leela.blocks.fs.watch import Watcher, KEYMAP
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    keyfile.write_text('{"keys": {}}')
    import leela.core.keys as keymap
    keymap.reload()
    async def run():
        (proj := tmp_path/'proj').mkdir()
        ws = [Watcher(Sandbox([]), poll=.05), Watcher(Sandbox([proj]), poll=.05)]
        qs = [w.subscribe() for w in ws]
        try:
            await asyncio.sleep(.3)
            for q in qs:
                while not q.empty(): q.get_nowait()
            keyfile.write_text('{"keys": {}}')
            with pytest.raises(asyncio.TimeoutError): await asyncio.wait_for(qs[0].get(), .4)
            keyfile.write_text('{"keys": {"run_cell": "ctrl+y"}}')
            return [await asyncio.wait_for(q.get(), 3) for q in qs]
        finally:
            for w in ws: w.close()
    got = asyncio.run(run())
    assert got[0] is KEYMAP, 'a workspace with no folder open still hears the keymap'
    assert got[1] is KEYMAP, 'and so does every other workspace, though only one of them reloads it'
    assert _chord('run_cell') == 'ctrl+y'

def test_a_broken_keymap_file_keeps_the_last_good_keys_and_says_why(keyfile):
    "A half-written file must not take every custom chord away."
    import leela.core.keys as keymap
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    keyfile.write_text(json.dumps({'keys': {'run_cell': 'ctrl+y'}}))
    assert keymap.refresh()
    for bad in ('{"keys": {"run_cell": ', '[1, 2]'):
        keyfile.write_text(bad)
        assert keymap.refresh() and _chord('run_cell') == 'ctrl+y'
        assert len(keymap.NOTES) == 1 and 'last good keys' in keymap.NOTES[0] and str(keyfile) in keymap.NOTES[0]
    with TestClient(ide_app(Workspace(roots=[]))) as c:
        assert c.get('/keys.json').json()['notes'] == list(keymap.NOTES), 'the page shows the note as the keys panel does'
    keyfile.write_text(json.dumps({'keys': {'run_cell': 'ctrl+u'}}))
    assert keymap.refresh() and _chord('run_cell') == 'ctrl+u' and not keymap.NOTES, 'a good file again clears the note'

def test_a_deleted_keymap_file_falls_back_to_the_defaults(keyfile):
    import leela.core.keys as keymap
    default = next(k.key for k in keymap.DEFAULTS if k.action == 'run_cell')
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    keyfile.write_text(json.dumps({'keys': {'run_cell': 'ctrl+y'}}))
    assert keymap.refresh() and _chord('run_cell') == 'ctrl+y'
    keyfile.unlink()
    assert keymap.refresh() and _chord('run_cell') == default and not keymap.NOTES
    assert not keymap.refresh(), 'a file still gone is no change'


def test_a_folder_opened_after_startup_still_hears_the_shutdown(tmp_path):
    """The lifespan legs were zipped over the sites present at startup, so a workspace opened later never heard `lifespan.shutdown` and left its kernels, terminals and dev servers running."""
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
    """The slug names the state file, and a counter made it positional: open two projects that both end in `src` the other way round and each was served the other one's tabs."""
    (a := tmp_path/'a'/'src').mkdir(parents=True); (b := tmp_path/'b'/'src').mkdir(parents=True)
    store = tmp_path/'index.json'
    forward = dict(zip([a, b], assign_slugs([a, b], store)))
    assert len(set(forward.values())) == 2, forward
    assert assign_slugs([b, a], store) == [forward[b], forward[a]], 'the other order, the same slugs'
    assert assign_slugs([a], store) == [forward[a]], 'and one folder alone keeps what it was given'


def test_a_conversations_turns_carry_the_tool_results_the_log_keeps_elsewhere(tmp_path):
    "The log keeps 600 characters of a long tool result; the thread's turns put the rest back from `agent-details/`."
    import json as _json
    from tests.conftest import history_file
    ws = Workspace(roots=[tmp_path])
    whole = 'x' * 3000
    act = {'id': 'act1', 'tool': 'run_shell', 'args': {'command': 'ls'}, 'ok': True, 'done': True}
    row = {'session': 'agent-a', 'at': 1, 'model': ws.ai.model.name, 'prompt': 'list', 'reply': 'listed', 'turn_id': 't1',
           'activity': [act | {'detail': whole[:600] + '\n…[2400 more chars]'}], 'details': 'agent-details/agent-a.jsonl'}
    path = history_file(ws)
    path.write_text(_json.dumps(row) + '\n')
    (path.parent/'agent-details').mkdir()
    (path.parent/'agent-details'/'agent-a.jsonl').write_text(_json.dumps({'turn_id': 't1', 'details': {'act1': whole}}) + '\n')
    with TestClient(ide_app(ws)) as client:
        resumed = client.post('/agent/resume', json={'session': 'agent-a'}).json()
        turns = client.get('/agent/thread/turns', params={'thread': resumed['session']}).json()
    assert resumed['turns'][0]['activity'][0]['detail'] == whole
    assert turns['ok'] and turns['turns'][0]['activity'][0]['detail'] == whole, turns


def test_a_test_never_opens_the_machines_browser(system_browser):
    "Slow and web tests that opened an external link left a stray tab in the user's Chrome."
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    with TestClient(ide_app(Workspace())) as c:
        r = c.post('/browser/external', json={'url': 'https://example.test/notes'})
    assert r.json()['ok'] and system_browser == ['https://example.test/notes']

def test_a_test_never_drives_the_machines_cdp_chrome(tmp_path):
    "A workspace's inline browser took Leela's default CDP port, 9223, where the person's own headed Chrome listens, and a test opened its pages there as tabs."
    from leela.workspace import Workspace
    b = Workspace(roots=[tmp_path]).browser
    assert b.port != 9223 and b.profile, (b.port, b.profile)


def test_the_page_title_names_the_workspace_folder(tmp_path):
    "The client adds the pane to this, so the folder part is the server's and matches the native window."
    (root := tmp_path/'orgs').mkdir()
    with TestClient(ide_app(Workspace(roots=[root]))) as c: assert '<title>leela — orgs</title>' in c.get('/').text
    with TestClient(ide_app(Workspace(roots=[]))) as c: assert '<title>leela</title>' in c.get('/').text
