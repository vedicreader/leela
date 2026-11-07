"The approval gate: which calls ask a person in each approvals mode."

import os, tempfile
_T = tempfile.mkdtemp(prefix='leela-gate-')
for k, v in dict(VISHALAKSHI_VAULT='v/vault.db', LEELA_SEARCH_VAULT='v/search.db', RAMABANA_CONFIG='ram.toml').items(): os.environ.setdefault(k, os.path.join(_T, v))
os.environ['LEELA_MEMORY_OFFLINE'] = '1'

import pytest
from fastcore.all import Path
from leela.blocks.agent.ai import Interventions, WorkspaceHost, WRITE_TOOLS
from leela.workspace import Workspace

def _ap(mode, host=None):
    ap = Interventions(tools=WRITE_TOOLS, mode=mode, host=host, timeout=.1)
    ap.no_listener = 'refuse'
    return ap

def asks(ap, name, args):
    "Whether the call stops for a person: with nobody listening, a stop is a refusal."
    a = ap.request(name, args)
    return not a and 'nothing is listening' in a.note

ASKING = [('inspect_python', {'code': 'open("/tmp/x", "w")', 'scope': 'overlay'}),
          ('watch', {'target': 'https://example.com', 'kind': 'url'}),
          ('watch', {'target': '/somewhere', 'kind': 'folder', 'instructions': 'x'}),
          ('remember', {'text': 'a note'}),
          ('cancel_watch', {'watch_id': '1'}),
          ('generate_image', {'prompt': 'a cat'}),
          ('generate_video', {'prompt': 'a cat'}),
          ('check_exercise', {'path': 'a.ipynb', 'cell_id': 'c1'})]

@pytest.mark.parametrize('mode', ['ask', 'edits'])
@pytest.mark.parametrize('name,args', ASKING)
def test_code_runs_watches_memory_writes_and_spending_ask_in_ask_and_edits(mode, name, args):
    assert asks(_ap(mode), name, args)

@pytest.mark.parametrize('name,args', ASKING)
def test_full_auto_runs_them_and_off_refuses_them(name, args):
    assert _ap('auto').request(name, args)
    a = _ap('off').request(name, args)
    assert not a and 'switched off' in a.note

@pytest.mark.parametrize('name,args', [('inspect_python', {'code': 'x', 'scope': 'isolated'}), ('inspect_python', {'code': 'x'}),
                                       ('inspect_python', {'code': '', 'scope': 'overlay'}),
                                       ('watch', {'target': 'drink water', 'kind': 'remind'}), ('list_watches', {})])
def test_isolated_inspection_reminders_and_reads_stay_free(name, args):
    assert _ap('ask').request(name, args)

class _Spec:
    "A host whose one spec has a GET, a HEAD and a DELETE."
    rows = [dict(name='get_repo', verb='GET'), dict(name='head_repo', verb='HEAD'), dict(name='delete_repo', verb='DELETE')]
    def api_ops(self, group='', name='', match='', limit=None, offset=0): return self.rows

@pytest.mark.parametrize('mode', ['ask', 'edits'])
def test_api_call_asks_for_every_verb_but_get_and_head(mode):
    ap = _ap(mode, _Spec())
    assert ap.request('api_call', {'operation': 'get_repo', 'name': 'gh'})
    assert ap.request('api_call', {'operation': 'head_repo', 'name': 'gh'})
    assert asks(ap, 'api_call', {'operation': 'delete_repo', 'name': 'gh'})
    assert asks(ap, 'api_call', {'operation': 'no_such_op', 'name': 'gh'}), 'an operation nobody can name the verb of asks'
    assert _ap('auto', _Spec()).request('api_call', {'operation': 'delete_repo', 'name': 'gh'})

@pytest.mark.parametrize('path', ['.git/hooks/pre-commit', '.git/config', '.venv/bin/python', '.leela/settings.json', 'sub/.git/config'])
def test_edits_mode_asks_for_writes_under_git_venv_and_leela(tmp_path, path):
    ws = Workspace(roots=[tmp_path], approvals='auto')
    try:
        ap = _ap('edits', WorkspaceHost(ws))
        assert asks(ap, 'create_file', {'path': path, 'text': 'pwn'})
        assert asks(ap, 'edit_file', {'path': str(tmp_path/path), 'edits': []})
        assert ap.request('create_file', {'path': 'src/a.py', 'text': 'x = 1'}), 'an ordinary file is still covered by edits'
        assert ap.request('view_file', {'path': path}), 'a read is not a write'
        assert _ap('auto', WorkspaceHost(ws)).request('create_file', {'path': path, 'text': 'x'})
    finally: ws.shutdown_now()

def test_edits_mode_asks_for_a_link_that_resolves_into_git(tmp_path):
    (tmp_path/'.git').mkdir(); (tmp_path/'hooks').symlink_to(tmp_path/'.git')
    ws = Workspace(roots=[tmp_path], approvals='auto')
    try: assert asks(_ap('edits', WorkspaceHost(ws)), 'create_file', {'path': 'hooks/pre-commit', 'text': 'pwn'})
    finally: ws.shutdown_now()

def test_a_watch_or_a_poll_reads_no_file_outside_the_open_folders(tmp_path):
    proj, sec = tmp_path/'proj', tmp_path/'home'/'.ssh'
    proj.mkdir(); sec.mkdir(parents=True); (sec/'notes.md').write_text('zebrafish AKIAFAKE')
    ws = Workspace(roots=[proj], approvals='auto')
    try:
        h = WorkspaceHost(ws)
        with pytest.raises(Exception, match='outside|open folders'): h.watch(str(sec/'notes.md'), action='path', every='1m')
        (proj/'n.md').write_text('inside')
        assert h.watch(str(proj/'n.md'), action='path', every='1m')['id']
        h._vault(write=True).vault.watch(str(sec/'notes.md'), action='path', every='1m')   # one made before the check existed
        out = h.poll()
        assert 'AKIAFAKE' not in str(h.memory_search('zebrafish')) and out['skipped'] == [str(sec/'notes.md')]
    finally: ws.shutdown_now()

def test_watch_url_the_old_name_asks_too():
    assert asks(_ap('edits'), 'watch_url', {'url': 'https://example.com'})

@pytest.mark.parametrize('policy', ['once', 'count', 'until_write', 'reads', 'until_failure', 'completion'])
def test_no_run_policy_runs_a_guarded_write_and_reads_does_not_run_new_gates(tmp_path, policy):
    ws = Workspace(roots=[tmp_path], approvals='auto')
    try:
        ap = _ap('edits', WorkspaceHost(ws)); ap.set_run_policy(policy, 5)
        assert asks(ap, 'create_file', {'path': '.git/hooks/pre-commit', 'text': 'pwn'})
        if policy in ('reads', 'until_write'):
            assert asks(ap, 'inspect_python', {'code': 'x', 'scope': 'overlay'})
    finally: ws.shutdown_now()

def test_switching_to_edits_leaves_a_waiting_guarded_write_for_the_person(tmp_path):
    import threading, time
    ws = Workspace(roots=[tmp_path], approvals='auto')
    try:
        ap = Interventions(tools=WRITE_TOOLS, mode='ask', host=WorkspaceHost(ws), timeout=1); stop = ap.listen()
        got = {}
        t = threading.Thread(target=lambda: got.setdefault('a', ap.request('create_file', {'path': '.git/config', 'text': 'x'}))); t.start()
        for _ in range(100):
            if ap.pending is not None: break
            time.sleep(.01)
        ap.set_mode('edits')
        assert ap.pending is not None and ap.pending.forced == 'guard', 'edits does not settle it'
        ap.set_mode('auto'); t.join(2); stop()
        assert got['a'], 'auto does'
    finally: ws.shutdown_now()

def test_read_url_and_a_url_watch_refuse_a_local_file(tmp_path):
    ws = Workspace(roots=[tmp_path], approvals='auto')
    try:
        h = WorkspaceHost(ws)
        for f in (lambda: h.read_url('file:///etc/passwd'), lambda: h.watch('file:///etc/passwd', action='url')):
            with pytest.raises(Exception, match='not a web address'): f()
    finally: ws.shutdown_now()

def test_a_checkpoint_cannot_rerun_code_in_the_real_interpreter(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    ws = Workspace(roots=[tmp_path], approvals='auto')
    try:
        r = TestClient(ide_app(ws)).post('/agent/retry-tool', json={'tool': 'inspect_python', 'args': {'code': 'x', 'scope': 'overlay'}})
        assert 'only read-only calls' in r.text
    finally: ws.shutdown_now()
