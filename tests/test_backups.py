"Dated copies of what cannot be rebuilt, the retention that keeps them useful, and the restore."

from datetime import datetime, timedelta
from pathlib import Path

from leela.core import backups as B


def _cfg(tmp):
    cfg = Path(tmp)/'cfg'; cfg.mkdir()
    (cfg/'agent-history.jsonl').write_text('{"session":"a","prompt":"q"}\n')
    (cfg/'agent-sessions.json').write_text('{"sessions":{"a":{"title":"kept"}}}')
    (cfg/'timelines').mkdir(); (cfg/'timelines'/'x.json').write_text('{}')
    (cfg/'leela-app.log').write_text('noise')
    return cfg


def test_a_dated_copy_is_one_archive_and_survives_the_round_trip(tmp_path):
    """Five uncompressed copies were a third of a gigabyte, which is why one file per copy."""
    cfg = _cfg(tmp_path)
    (cfg/'agent-plans').mkdir(); (cfg/'agent-plans'/'big.md').write_text('the same line\n' * 4000)
    made = B.create_backup(cfg, B.backup_dir(cfg), reason='asked for', include=B.PRECIOUS)
    assert made.name.endswith(B.ARCHIVE) and made.is_file()
    raw = sum(f.stat().st_size for f in cfg.rglob('*') if f.is_file() and 'backups' not in f.parts)
    assert made.stat().st_size < raw, 'the archive is smaller than what went into it'
    listed = B.backups(cfg)[-1]
    assert listed['name'] == made.name[:-len(B.ARCHIVE)] and listed['archived'] is True
    assert listed['bytes'] == made.stat().st_size and listed['files'] >= 4
    assert 'agent-plans' in listed['entries'] and listed['reason'] == 'asked for'
    assert 'journals' not in listed['entries'], 'undo state for files still on disk is not precious'
    for f in (cfg/'agent-plans').iterdir(): f.unlink()
    (cfg/'agent-history.jsonl').write_text('WIPED')
    out = B.restore(listed['name'], cfg)
    assert (cfg/'agent-plans'/'big.md').read_text().startswith('the same line')
    assert (cfg/'agent-history.jsonl').read_text().startswith('{"session":"a"')
    assert 'agent-plans' in out['restored']


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


def test_a_live_database_is_copied_through_sqlite_not_as_three_files(tmp_path, monkeypatch):
    """A `.db` in WAL mode is three files that change independently, so copying them one after another can capture a set that never existed together, and a stale `-shm` confuses recovery rather than helping it."""
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
