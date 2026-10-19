"The learned review queue in the Review tab: Dhrona's candidates for `<cfg>/learned`, listed, diffed, accepted and rejected through `/agent/learned`."

import fcntl, subprocess, pytest
from pathlib import Path
from starlette.testclient import TestClient
from leela.app import ide_app

from ramabana.learned import STALE

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
    assert d['pending'][1]['stale'] is None
    r = c.post('/agent/learned/accept', json={'id': A})
    assert r.status_code == 200 and r.json()['ok'] and len(r.json()['commit']) == 7
    assert r.json()['moved'] == [] and r.json()['stale'] == [B], 'B edits the same line, so it no longer picks onto the new HEAD'
    assert (f/'AGENTS.md').read_text() == '# Learned\n\n- two\n', 'the next briefing reads it'
    assert c.get('/agent/learned').json()['pending'][0]['stale'] == STALE
    r = c.post('/agent/learned/accept', json={'id': B})
    assert r.status_code == 409 and r.json() == dict(ok=False, id=B, error=STALE)
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
    assert r == dict(ok=True, id=A, commit=None, moved=[], stale=[B])

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

def test_compact_proposes_a_candidate_off_the_loop_and_it_joins_the_queue(learned, monkeypatch):
    "Compact runs one blocking model turn: it must not hold the server's loop, and its candidate is reviewed like any other."
    import threading, ramabana.learned
    c, f = learned
    seen = {}
    def fake(folder, id=None, chat=None):
        seen.update(folder=folder, thread=threading.current_thread() is threading.main_thread())
        assert c.get('/agent/learned').json()['compacting'], 'a repainted queue shows it pending'
        candidate(f, C, '# Learned\n', 'compact AGENTS.md (17 → 10 characters)')
        return dict(ok=True, id=C, before=17, after=10)
    monkeypatch.setattr(ramabana.learned, 'compact', fake)
    assert not c.get('/agent/learned').json()['compacting']
    r = c.post('/agent/learned/compact')
    assert r.status_code == 200 and r.json() == dict(ok=True, id=C, before=17, after=10)
    assert seen == dict(folder=f, thread=False)
    d = c.get('/agent/learned').json()
    assert [x['id'] for x in d['pending']] == [A, B, C] and not d['compacting']
    assert c.get('/agent/learned/compact').status_code == 405, 'a model turn only on a POST'

def test_compact_refusals_come_back_verbatim_and_one_runs_at_a_time(learned, monkeypatch):
    import threading, ramabana.learned
    c, f = learned
    real, started, gate = ramabana.learned.compact, threading.Event(), threading.Event()
    def slow(folder, id=None, chat=None): started.set(); gate.wait(5); return dict(ok=False, error='the editor gave no answer: no key')
    monkeypatch.setattr(ramabana.learned, 'compact', slow)
    out = {}
    t = threading.Thread(target=lambda: out.update(r=c.post('/agent/learned/compact'))); t.start()
    assert started.wait(5)
    r = c.post('/agent/learned/compact')
    assert r.status_code == 409 and r.json() == dict(ok=False, error='a compaction is already running')
    gate.set(); t.join(5)
    assert out['r'].status_code == 409 and out['r'].json() == dict(ok=False, error='the editor gave no answer: no key')
    def boom(folder, id=None, chat=None): raise OSError('git went away')
    monkeypatch.setattr(ramabana.learned, 'compact', boom)
    r = c.post('/agent/learned/compact')
    assert r.status_code == 409 and r.json() == dict(ok=False, error='OSError: git went away')
    monkeypatch.setattr(ramabana.learned, 'compact', real)
    r = c.post('/agent/learned/compact')
    assert r.status_code == 409 and r.json() == dict(ok=False, error='AGENTS.md holds nothing Dhrona proposed, and a compaction rewrites only that'), 'refused before any model turn'
    (f/'scratch.md').write_text('by hand')
    r = c.post('/agent/learned/compact')
    assert r.status_code == 409 and r.json()['error'] == f'{f} has uncommitted changes; commit or discard them first'

def test_the_compact_button_sits_in_its_slot_and_selects_the_new_candidate():
    src = (Path(__file__).resolve().parents[2]/'leela'/'blocks'/'vault'/'review.js').read_text()
    assert '<span data-learned-compact><button class="lee-btn" data-learned-compact-go' in src
    assert "post('/agent/learned/compact', id ? {id} : {})" in src and 'if (d.id) st.want = d.id;' in src
    assert "if (t.closest('[data-learned-compact-go]')) return learnedCompact(host);" in src
    assert 'learnedCompact' in (Path(__file__).resolve().parents[2]/'leela'/'static'/'lee-ide.js').read_text(), 'the bundle is rebuilt'

class Backend:
    "A started `summary` backend: its window, its lock and its note, as `compact_chat` reads them."
    def __init__(self, ctx=128_000, note=''):
        import threading
        self.spec, self.lock, self.note = type('Spec', (), dict(name='m', ctx=ctx))(), threading.Lock(), note
    def count_tokens(self, s): return len(s)//4

class Summary:
    "The agent pane's assistant on its `summary` route, recording each oneshot."
    def __init__(self, reply='', be=None, note=''): self.reply, self.be, self.calls, self.routing = reply, be or Backend(), [], type('R', (), dict(notes={}))()
    def oneshot(self, p, sp='', job='oneshot', max_tokens=None, fits=None):
        self.calls.append(dict(p=p, job=job, max_tokens=max_tokens))
        if fits is not None and not fits(self.be): return ''
        return self.reply
    def _be_or_none(self, job='turn'): return self.be

@pytest.fixture
def dhronas(learned, monkeypatch):
    "`learned` with HEAD's last paragraph committed as Dhrona, so a compaction has something to rewrite; no `ramabana` executable may run."
    import dhrona.improve as di
    c, f = learned
    (f/'AGENTS.md').write_text('# Learned\n\n- one\n\n- run the tests before reporting, every time, whatever the change\n')
    git(f, 'add', '.'); subprocess.run(['git', '-C', str(f), *di._AS_DHRONA, 'commit', '-qm', f'{di.LESSON} run the tests'], check=True, capture_output=True)
    real = subprocess.run
    def run(cmd, *a, **k):
        assert Path(str(cmd[0])).name != 'ramabana', f'a headless ramabana ran: {cmd}'
        return real(cmd, *a, **k)
    monkeypatch.setattr(di.subprocess, 'run', run)
    return c, f

def test_compact_asks_leelas_summary_route_in_process(dhronas, ws, monkeypatch):
    "The frozen app has no `ramabana` console script beside its Python: the editor is Leela's own `summary` route, never a subprocess."
    import dhrona.improve as di
    c, f = dhronas
    ai = Summary('[kept 1]\n\n[kept 2]\n\n- run the tests before reporting\n')
    monkeypatch.setattr(type(ws), 'ai', property(lambda s: ai))
    monkeypatch.setattr(di, '_editor', lambda *a, **k: pytest.fail('the headless editor was built'))
    r = c.post('/agent/learned/compact')
    assert r.status_code == 200 and r.json()['ok'], r.json()
    assert [x['job'] for x in ai.calls] == ['summary'] and ai.calls[0]['max_tokens'] == 1024
    assert ai.calls[0]['p'] == di.compaction_prompt((f/'AGENTS.md').read_text(), di._paragraphs(f), di.COMPACT_TARGET), 'the scrubbed prompt'
    assert r.json()['id'] in [x['id'] for x in c.get('/agent/learned').json()['pending']]

def test_compact_chat_failures_come_back_verbatim(dhronas, ws, monkeypatch):
    c, f = dhronas
    for ai, err in [(Summary(be=Backend(note='m: no API key')), 'm: no API key'),
                    (Summary(be=Backend(ctx=200)), 'the window of m is too small for this compaction'),
                    (Summary(), 'the summary model answered nothing')]:
        monkeypatch.setattr(type(ws), 'ai', property(lambda s, ai=ai: ai))
        r = c.post('/agent/learned/compact')
        assert r.status_code == 409 and not r.json()['ok'] and r.json()['error'] == err, err
    busy = Summary(); busy.be.lock.acquire()
    monkeypatch.setattr(type(ws), 'ai', property(lambda s: busy))
    assert c.post('/agent/learned/compact').json()['error'] == 'm is busy with another turn; compact when it ends'
    assert c.get('/agent/learned').json()['pending'][-1]['id'] == B, 'nothing was proposed'

def test_a_size_refusal_offers_a_compaction_that_folds_the_candidate_in(learned, monkeypatch):
    "ramabana 0.2.41: an accept past `LEARNED_MAX` returns the would-be `length`, and `compact(folder, id)` folds that candidate in."
    import ramabana.learned
    c, f = learned
    candidate(f, C, '# Learned\n\n' + '- a long lesson\n' * 200, 'say a lot')
    r = c.post('/agent/learned/accept', json={'id': C})
    assert r.status_code == 409 and r.json()['length'] > 2000 and f'/learned compact {C}' in r.json()['error'], r.json()
    seen = {}
    def fake(folder, id=None, chat=None):
        seen.update(id=id)
        return dict(ok=True, id='20261019-101800-dddddd', before=17, after=10)
    monkeypatch.setattr(ramabana.learned, 'compact', fake)
    assert c.post('/agent/learned/compact', json={'id': C}).json()['ok'] and seen == dict(id=C)
    assert c.post('/agent/learned/compact').json()['ok'] and seen == dict(id=None), 'no body is the plain compaction'

def test_the_queue_shows_stale_rows_what_an_accept_moved_and_offers_the_folding_compaction():
    root = Path(__file__).resolve().parents[2]/'leela'
    src = (root/'blocks'/'vault'/'review.js').read_text()
    assert '(r.stale ? `<small class="lee-review-stalewhy" data-learned-stale>stale: ${esc(r.stale)}</small>` : \'\')' in src
    assert "status(act === 'reject' ? `rejected ${d.id}` : learnedAccepted(d), 'ok');" in src
    assert 'candidate${moved === 1 ? \'\' : \'s\'} moved onto it' in src and "stale now: ${stale.join(', ')}" in src
    assert "st.lrefused = {id: r.id, error: e.message || String(e), length: e.body.length || 0};" in src, 'the refusal is kept verbatim'
    assert 'data-learned-compact-with="${esc(ref.id)}"' in src and 'Compact with this candidate' in src
    assert "return learnedCompact(host, fold.dataset.learnedCompactWith);" in src and "post('/agent/learned/compact', id ? {id} : {})" in src
    assert 'learnedAccepted' in (root/'static'/'lee-ide.js').read_text(), 'the bundle is rebuilt'
