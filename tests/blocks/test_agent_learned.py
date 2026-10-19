"The learned review queue in the Review tab: Dhrona's candidates for `<cfg>/learned`, listed, diffed, accepted and rejected through `/agent/learned`."

import fcntl, subprocess, pytest
from pathlib import Path
from starlette.testclient import TestClient
from leela.app import ide_app

A, B, C = '20261019-101500-aaaaaa', '20261019-101600-bbbbbb', '20261019-101700-cccccc'

def git(d, *a): return subprocess.run(['git', '-C', str(d), '-c', 'user.name=t', '-c', 'user.email=t@t', *a], check=True, capture_output=True, text=True)

def candidate(f, id, text, subject, orphan=False):
    git(f, 'checkout', '-q', *(['--orphan', f'pending/{id}'] if orphan else ['-b', f'pending/{id}', 'main']))
    (f/'AGENTS.md').write_text(text); git(f, 'add', '.'); git(f, 'commit', '-qm', subject); git(f, 'checkout', '-q', '-f', 'main')

class Agent:
    "A live assistant that runs without the learned folder, as `--no-learned` does: `learned_dir` is None and the queue is still reviewed."
    def __init__(self, cfg): self.cfg, self.learned, self.learned_dir = cfg, False, None
    def lessons(self, n=50): return [dict(lesson='run the tests before reporting', cue='a fix')]
    def refresh(self): pass
    def close(self): pass

@pytest.fixture
def learned(ws, tmp_path, monkeypatch):
    cfg = tmp_path/'cfg'; f = cfg/'learned'; f.mkdir(parents=True)
    git(f, 'init', '-q', '-b', 'main'); (f/'AGENTS.md').write_text('# Learned\n\n- one\n'); git(f, 'add', '.'); git(f, 'commit', '-qm', 'base')
    candidate(f, A, '# Learned\n\n- two\n', 'say two')
    candidate(f, B, '# Learned\n\n- three\n', 'say three')
    monkeypatch.setattr(ws, '_ai', Agent(cfg))
    with TestClient(ide_app(ws)) as c: yield c, f

def test_the_queue_lists_diffs_accepts_and_rejects_through_the_routes(learned):
    c, f = learned
    d = c.get('/agent/learned').json()
    assert d['ok'] and [r['id'] for r in d['pending']] == [A, B] and d['pending'][0]['files'] == ['AGENTS.md'] and d['pending'][0]['subject'] == 'say two'
    assert d['folder'] == str(f) and d['chars'] == len('# Learned\n\n- one\n') and d['limit'] == 2000
    assert d['lessons'] == [dict(lesson='run the tests before reporting', cue='a fix')], 'read-only, from the live agent'
    r = c.post('/agent/learned/diff', json={'id': A}).json()
    assert r['ok'] and '+- two' in r['diff'] and any(x['kind'] == 'add' and 'two' in x['text'] for x in r['rows']) and not r['truncated']
    r = c.post('/agent/learned/accept', json={'id': A})
    assert r.status_code == 200 and r.json()['ok'] and len(r.json()['commit']) == 7
    assert (f/'AGENTS.md').read_text() == '# Learned\n\n- two\n', 'the next briefing reads it'
    r = c.post('/agent/learned/accept', json={'id': B})
    assert r.status_code == 409 and r.json() == dict(ok=False, id=B, error='it conflicts with what the learned folder holds now; `diff` it, then reject it or edit the folder by hand')
    r = c.post('/agent/learned/reject', json={'id': B})
    assert r.status_code == 200 and r.json() == dict(ok=True, id=B)
    assert c.get('/agent/learned').json()['pending'] == []
    r = c.post('/agent/learned/reject', json={'id': B})
    assert r.status_code == 409 and r.json() == dict(ok=False, id=B, error=f'nothing is pending as {B}')
    r = c.post('/agent/learned/diff', json={'id': '../etc'})
    assert r.status_code == 409 and 'is not a pending id' in r.json()['error'] and r.json()['id'] == '../etc'

def test_a_running_batch_and_uncommitted_changes_come_back_verbatim(learned):
    c, f = learned
    with open(f.parent/'.learned.lock', 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for act in ('accept', 'reject'):
            r = c.post(f'/agent/learned/{act}', json={'id': A})
            assert r.status_code == 409 and r.json()['error'] == f'a Dhrona batch is running on the learned folder; {act} it when the batch ends', act
    (f/'scratch.md').write_text('by hand')
    r = c.post('/agent/learned/accept', json={'id': A})
    assert r.status_code == 409 and r.json()['error'] == f'{f} has uncommitted changes; commit or discard them first'
    assert [x['id'] for x in c.get('/agent/learned').json()['pending']] == [A, B], 'nothing was decided'

def test_an_accept_head_already_holds_says_so(learned):
    c, f = learned
    (f/'AGENTS.md').write_text('# Learned\n\n- two\n'); git(f, 'commit', '-qam', 'by hand')
    r = c.post('/agent/learned/accept', json={'id': A}).json()
    assert r == dict(ok=True, id=A, commit=None)

def test_a_git_failure_is_the_same_structured_refusal(learned):
    "ramabana's `_git` raises on what it does not expect; a root-commit candidate fails `git diff ref^ ref`."
    c, f = learned
    candidate(f, C, 'all new\n', 'from nothing', orphan=True)
    r = c.get('/agent/learned')
    assert r.status_code == 409 and not r.json()['ok'] and r.json()['error'] and r.json()['pending'] == []
    r = c.post('/agent/learned/diff', json={'id': C})
    assert r.status_code == 409 and r.json()['id'] == C and r.json()['error']

def test_no_learned_folder_is_an_empty_queue(ws, tmp_path, monkeypatch):
    from leela.blocks.settings import settings
    monkeypatch.setattr(settings, 'agent_cfg', lambda *a, **k: tmp_path/'none')
    monkeypatch.setattr(ws, '_ai', None)
    with TestClient(ide_app(ws)) as c:
        d = c.get('/agent/learned').json()
        assert d['ok'] and d['pending'] == [] and d['chars'] == 0 and d['folder'] == str(tmp_path/'none'/'learned')
        r = c.post('/agent/learned/accept', json={'id': A})
        assert r.status_code == 409 and 'holds nothing Dhrona proposed' in r.json()['error']

def test_the_review_tab_has_a_learned_queue_and_a_command_reaches_it(ws):
    from fasthtml.common import to_xml
    from leela.blocks.vault.ui import review_view
    from leela.core.keys import DEFAULTS
    from leela.blocks.keys.menus import BAR
    assert 'data-mode="learned"' in to_xml(review_view(mode='learned')) and 'data-mode="proof"' in to_xml(review_view(mode='nonsense'))
    k = next(k for k in DEFAULTS if k.action == 'learned_review')
    assert k.scope == 'global' and not k.key, 'a palette command, no chord'
    static = Path(__file__).resolve().parents[2]/'leela'/'static'
    for js in ('js/actions.js', 'lee-core.js'): assert "learned_review: () => leeVaultReview('', '', '', 'learned')" in (static/js).read_text(), js
    assert 'learned_review' in repr(BAR)
    src = (static.parent/'blocks'/'vault'/'review.js').read_text()
    assert "if (st.mode === 'learned') return learnedAct(host, act, r);" in src, 'keys in the learned queue never reach the vault routes'
    with TestClient(ide_app(ws)) as c:
        assert 'data-mode="learned"' in c.get('/vault/view/review?mode=learned').text
