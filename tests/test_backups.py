"Dated copies of what cannot be rebuilt, the retention that keeps them useful, and the restore."

import tarfile
from datetime import datetime, timedelta
from pathlib import Path

from starlette.testclient import TestClient
from leela.app import ide_app
from leela.core import backups as B
from leela.workspace import Workspace


def _cfg(tmp):
    cfg = Path(tmp)/'cfg'; cfg.mkdir()
    (cfg/'agent-history.jsonl').write_text('{"session":"a","prompt":"q"}\n')
    (cfg/'agent-sessions.json').write_text('{"sessions":{"a":{"title":"kept"}}}')
    (cfg/'timelines').mkdir(); (cfg/'timelines'/'x.json').write_text('{}')
    (cfg/'leela-app.log').write_text('noise')
    return cfg


def _members(arc):
    with tarfile.open(arc, 'r:gz') as tar: return {m.name for m in tar.getmembers()}


def test_a_backup_holds_what_cannot_be_rebuilt_and_nothing_that_can(tmp_path):
    cfg = _cfg(tmp_path)
    made = B.create_backup(cfg, B.backup_dir(cfg), reason='asked for', include=B.PRECIOUS)
    held = _members(made)
    assert {'agent-history.jsonl', 'agent-sessions.json', 'timelines'} <= held
    assert 'leela-app.log' not in held, 'a log regenerates, and copying it makes backups too big'
    assert 'timelines/x.json' in held, 'directories come whole'
    assert B.backups(cfg)[-1]['reason'] == 'asked for'


def test_a_dated_copy_is_one_archive_and_survives_the_round_trip(tmp_path):
    """Five uncompressed copies were a third of a gigabyte, which is why one file per copy."""
    cfg = _cfg(tmp_path)
    (cfg/'journals').mkdir(); (cfg/'journals'/'big.md').write_text('the same line\n' * 4000)
    made = B.create_backup(cfg, B.backup_dir(cfg), reason='asked for', include=B.PRECIOUS)
    assert made.name.endswith(B.ARCHIVE) and made.is_file()
    raw = sum(f.stat().st_size for f in cfg.rglob('*') if f.is_file() and 'backups' not in f.parts)
    assert made.stat().st_size < raw, 'the archive is smaller than what went into it'
    listed = B.backups(cfg)[-1]
    assert listed['name'] == made.name[:-len(B.ARCHIVE)] and listed['archived'] is True
    assert listed['bytes'] == made.stat().st_size and listed['files'] >= 4
    assert 'journals' in listed['entries'] and listed['reason'] == 'asked for'
    for f in (cfg/'journals').iterdir(): f.unlink()
    (cfg/'agent-history.jsonl').write_text('WIPED')
    out = B.restore(listed['name'], cfg)
    assert (cfg/'journals'/'big.md').read_text().startswith('the same line')
    assert (cfg/'agent-history.jsonl').read_text().startswith('{"session":"a"')
    assert 'journals' in out['restored']


def test_only_the_asked_for_entries_come_out_of_the_archive(tmp_path):
    "Extracting the whole archive to put one file back would overwrite everything else with it."
    cfg = _cfg(tmp_path)
    made = B.create_backup(cfg, B.backup_dir(cfg), include=B.PRECIOUS)
    (cfg/'agent-history.jsonl').write_text('WIPED')
    (cfg/'agent-sessions.json').write_text('WIPED')
    out = B.restore(made.name, cfg, only=['agent-sessions.json'])
    assert out['restored'] == ['agent-sessions.json'] and out['files'] == 1
    assert (cfg/'agent-sessions.json').read_text().startswith('{"sessions"')
    assert (cfg/'agent-history.jsonl').read_text() == 'WIPED', 'the rest was left where it was'


def test_what_is_deselected_is_not_copied(tmp_path):
    "The set is a person's choice, and the choice is what makes a copy small enough to keep five of."
    cfg = _cfg(tmp_path)
    made = B.create_backup(cfg, B.backup_dir(cfg), include=('agent-history.jsonl',))
    assert _members(made) == {'agent-history.jsonl'}
    assert B.backups(cfg)[-1]['entries'] == ['agent-history.jsonl']
    assert B.create_backup(cfg, B.backup_dir(cfg), include=()) is None, 'nothing chosen, nothing copied'
    assert 'nothing is selected' in B.run_backup(cfg, include=[])['problem']


def test_vault_memory_is_backed_up_when_it_is_chosen(tmp_path, monkeypatch):
    "The vault lives in its own directory, so it is named rather than found under the config dir."
    cfg = _cfg(tmp_path)
    vault = tmp_path/'vishalakshi'; vault.mkdir(); (vault/'vault.db').write_text('SQLite')
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(vault/'vault.db'))
    assert B.entry_source('vault', cfg) == vault
    assert 'vault' not in B.PRECIOUS, 'opt-in: restoring it writes outside the config dir'
    made = B.create_backup(cfg, B.backup_dir(cfg), include=('agent-history.jsonl', 'vault'))
    assert 'vault/vault.db' in _members(made)
    (vault/'vault.db').write_text('WIPED')
    out = B.restore(made.name, cfg, only=['vault'])
    assert out['restored'] == ['vault'] and (vault/'vault.db').read_text() == 'SQLite'


def test_retention_keeps_one_inside_each_band_and_the_newest_few():
    now = datetime(2026, 8, 21, 12)
    names = [(now - timedelta(days=d)).strftime(B.STAMP) for d in (0, 1, 3, 10, 30, 90, 200)]
    keep = B.clean_dates(names, now=now, max_ages=(2, 14, 60), k=2)
    assert names[0] in keep and names[1] in keep, 'the newest two, whatever their age'
    # the oldest still inside a band, not the newest: that is what gives depth rather than
    # three copies of roughly the same moment
    assert names[3] in keep, 'ten days old is the oldest inside fourteen'
    assert names[4] in keep, 'thirty days old is the oldest inside sixty'
    assert names[6] not in keep, 'and nothing beyond every band'
    assert names[5] not in keep, 'nor a second copy inside a band that already has one'
    assert B.clean_dates([], now=now) == [] and B.clean_dates(['not-a-date'], now=now) == []


def test_pruning_removes_only_what_retention_did_not_choose(tmp_path):
    cfg, root = _cfg(tmp_path), None
    now = datetime(2026, 8, 21, 12)
    root = B.backup_dir(cfg); root.mkdir(parents=True)
    names = [(now - timedelta(days=d)).strftime(B.STAMP) for d in (0, 1, 5, 400)]
    for name in names[:2]: (root/f'{name}{B.ARCHIVE}').write_text('x'); (root/f'{name}.json').write_text('{}')
    for name in names[2:]: (root/name).mkdir()      # copies taken before the archives
    gone = B.clean_backups(root, max_ages=(2, 14, 60), k=2)
    assert names[3] in gone and names[0] not in gone
    assert {B._stem(p.name) for p in root.iterdir() if not p.name.endswith('.json')} == set(names) - set(gone)
    assert not (root/f'{names[3]}').exists(), 'the folder it was went with it'


def test_a_copy_is_taken_before_anything_overwrites_the_log(tmp_path):
    """The failure this exists for is one write to the conversation log, so the copy happens on
    that write rather than on a cadence that may be hours away."""
    cfg = _cfg(tmp_path)
    log = cfg/'agent-history.jsonl'
    kept = B.guard(log, cfg, reason='before an overwrite')
    log.write_text('WIPED')
    assert kept and kept.read_text().startswith('{"session":"a"'), 'the words survive the overwrite'
    assert kept.parent.name == 'guard', 'kept apart from the dated copies, which have their own pruning'
    assert B.guard(cfg/'not-there.json', cfg) is None
    log.write_text('')
    assert B.guard(log, cfg) is None, 'an empty file is not worth a copy'


def test_a_guard_keeps_the_last_ten_and_no_more(tmp_path):
    cfg = _cfg(tmp_path)
    log, seen = cfg/'agent-history.jsonl', []
    for i in range(13):
        log.write_text(f'turn {i}\n')
        out = B.guard(log, cfg)
        if out: seen.append(out.name)
    kept = sorted(p.name for p in (B.backup_dir(cfg)/'guard').iterdir())
    assert len(kept) <= 10, 'ten is enough to notice and act, and it does not grow without limit'


def test_a_copy_taken_before_the_archives_still_restores(tmp_path):
    "A folder copy already on disk is what this feature exists for; it stays readable."
    cfg = _cfg(tmp_path)
    old = B.backup_dir(cfg)/'20260101_000000'
    (old/'timelines').mkdir(parents=True)
    (old/'agent-history.jsonl').write_text('{"session":"a","prompt":"kept"}\n')
    (old/'timelines'/'x.json').write_text('{"old":1}')
    (old/'.reason').write_text('taken by an older Leela\n')
    listed = B.backups(cfg)
    assert [b['name'] for b in listed] == ['20260101_000000']
    assert listed[0]['archived'] is False and listed[0]['reason'] == 'taken by an older Leela'
    assert listed[0]['files'] == 3
    (cfg/'agent-history.jsonl').write_text('WIPED')
    out = B.restore('20260101_000000', cfg, only=['agent-history.jsonl'])
    assert out['restored'] == ['agent-history.jsonl']
    assert (cfg/'agent-history.jsonl').read_text().endswith('"kept"}\n')
    assert (cfg/'timelines'/'x.json').read_text() == '{}', 'only what was asked for came back'


def test_restoring_keeps_a_copy_of_what_it_replaces(tmp_path):
    "A restore is itself a write over live state; the wrong one must not be a second loss."
    cfg = _cfg(tmp_path)
    made = B.create_backup(cfg, B.backup_dir(cfg), reason='before the mistake', include=B.PRECIOUS)
    (cfg/'agent-history.jsonl').write_text('WIPED')
    out = B.restore(made.name, cfg)
    assert 'agent-history.jsonl' in out['restored']
    assert (cfg/'agent-history.jsonl').read_text().startswith('{"session":"a"')
    replaced = list((B.backup_dir(cfg)/'guard').iterdir())
    assert any(p.read_text() == 'WIPED' for p in replaced), 'what the restore replaced was kept'
    assert B.restore(made.name, cfg, only=['agent-sessions.json'])['restored'] == ['agent-sessions.json']


def test_a_backup_that_is_not_there_is_named_rather_than_guessed_at(tmp_path):
    import pytest
    cfg = _cfg(tmp_path)
    with pytest.raises(FileNotFoundError): B.restore('20260101_000000', cfg)
    B.backup_dir(cfg).mkdir(parents=True); (B.backup_dir(cfg)/'20260101_000000').mkdir()
    with pytest.raises(ValueError): B.restore('20260101_000000', cfg)
    made = B.create_backup(cfg, B.backup_dir(cfg), include=('agent-history.jsonl',))
    with pytest.raises(ValueError): B.restore(made.name, cfg, only=['workspace.json'])


def test_a_failed_backup_never_stops_the_app(tmp_path):
    "Backing up is insurance. Insurance that can crash the thing it insures is worse than none."
    out = B.run_backup(tmp_path/'nothing-here', reason='empty')
    assert out['ok'] is False and 'nothing to back up' in out['problem']


def test_the_cadence_decides_when_one_is_due(tmp_path):
    import time
    cfg = _cfg(tmp_path)
    assert B.due('daily', cfg) is True, 'with no copies at all, one is due'
    assert B.due('off', cfg) is False, 'off is never due, and keeps only the pre-write copies'
    B.create_backup(cfg, B.backup_dir(cfg), include=B.PRECIOUS)
    assert B.due('daily', cfg) is False
    assert B.due('hourly', cfg, now=time.time() + 3700) is True


def test_the_routes_list_take_and_restore_a_backup(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(B, 'leela_cfg', cfg)
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        listed = client.get('/backups').json()
        assert listed['ok'] and listed['cadence'] in B.CADENCES and listed['backups'] == []
        made = client.post('/backups/run', json={'reason': 'asked for'}).json()
        assert made['ok'] and made['name']
        again = client.get('/backups').json()
        assert [b['name'] for b in again['backups']] == [made['name']]
        assert again['backups'][0]['reason'] == 'asked for'
        (cfg/'agent-history.jsonl').write_text('WIPED')
        back = client.post('/backups/restore', json={'name': made['name']}).json()
        assert back['ok'] and 'agent-history.jsonl' in back['restored']
        assert (cfg/'agent-history.jsonl').read_text().startswith('{"session":"a"')
        missing = client.post('/backups/restore', json={'name': '20200101_000000'})
        assert missing.status_code == 404
        assert client.post('/backups/restore', json={}).status_code == 400


def test_resuming_a_conversation_copies_the_log_first(tmp_path, monkeypatch):
    "Resume rebuilds context from the log, so the log is copied before anything can touch it."
    src = (Path(__file__).resolve().parents[1]/'leela/blocks/agent/threads.py').read_text()
    resume = src[src.index('def resume(self, session)'):src.index('def close(self, thread_id)')]
    assert 'guard_history' in resume and 'before resuming' in resume
    assert resume.index('guard_history') < resume.index('resume_session('), 'before, not after'


def test_only_known_entries_can_be_saved_as_the_set(tmp_path):
    import pytest
    from leela.blocks.settings.settings import Settings
    held = Settings(user_path=tmp_path/'settings.json')
    held.save('user', 'backups', {'include': ['journals', 'vault']})
    assert held.effective()['backups']['include'] == ['journals', 'vault']
    with pytest.raises(ValueError): held.save('user', 'backups', {'include': ['~/.ssh']})
    with pytest.raises(ValueError): held.save('user', 'backups', {'include': 'journals'})

def test_a_live_database_is_copied_through_sqlite_not_as_three_files(tmp_path, monkeypatch):
    """A `.db` in WAL mode is three files that change independently, so copying them one after
    another can capture a set that never existed together -- and a stale `-shm` confuses recovery
    rather than helping it. The backup API hands over one consistent file instead."""
    import sqlite3, tarfile
    from leela.core import backups as B
    cfg = Path(tmp_path)/'cfg'; (cfg/'memory').mkdir(parents=True)
    db = cfg/'memory'/'notes.db'
    con = sqlite3.connect(db)
    con.execute('pragma journal_mode=wal'); con.execute('create table t (x)')
    con.execute("insert into t values ('committed')"); con.commit()
    assert (cfg/'memory'/'notes.db-wal').exists(), 'a WAL to be tempted by'

    made = B.create_backup(cfg, B.backup_dir(cfg), include=['memory'])
    names = tarfile.open(made).getnames()
    assert 'memory/notes.db' in names
    assert not [n for n in names if n.endswith(('-wal', '-shm'))], 'the sidecars are not copied'
    con.close()

    (cfg/'memory'/'notes.db').unlink()
    for side in ('-wal', '-shm'):
        p = cfg/'memory'/f'notes.db{side}'
        if p.exists(): p.unlink()
    B.restore(_stem(made.name), cfg, only=['memory'])
    back = sqlite3.connect(cfg/'memory'/'notes.db')
    assert back.execute('select x from t').fetchall() == [('committed',)], 'the committed row came back'
    back.close()


def _stem(name): return name.split('.tar')[0]
