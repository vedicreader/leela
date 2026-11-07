"Audio and video files open in their media tab from every route, stream with HTTP Range, and never show as text or change on disk."
import hashlib, io, wave
import pytest
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.agent.ai import WorkspaceHost
from leela.blocks.fs import app as fs_app, office
from leela.blocks.fs.fs import MEDIA_TYPES, Unsafe, is_media, is_texty, loose_refusal
from leela.hub import _unopenable
from leela.workspace import Tab, Workspace, kind_for, openable
from fastcore.all import Path

FIXTURES = Path(__file__).parent/'fixtures'
AUDIO = ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.oga', '.flac', '.opus')
VIDEO = ('.mp4', '.m4v', '.mov', '.webm')

def _wav(p, secs=1, rate=8000):
    with wave.open(str(p), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(bytes(range(256)) * (secs*rate*2//256))
    return p

def _stamp(p): return p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()

def test_each_playable_format_opens_as_its_media_kind(tmp_path):
    """.mp3 and .mp4 were refused, and .wav, .m4a and .mov opened as text tabs of raw bytes."""
    assert set(MEDIA_TYPES) == {*AUDIO, *VIDEO}
    for e in AUDIO + VIDEO:
        p = tmp_path/f'a{e}'
        want = 'audio' if e in AUDIO else 'video'
        assert openable(p) and not is_texty(p) and is_media(p) and kind_for(p) == want and Tab(path=str(p)).kind == want, e
        assert MEDIA_TYPES[e].startswith(want + '/'), e
    assert kind_for(tmp_path/'A.MP3') == 'audio' and kind_for(tmp_path/'clip.MOV') == 'video'

def test_media_no_engine_plays_is_never_text_and_is_refused(tmp_path):
    for e in ('.ogv', '.avi', '.mkv', '.wmv', '.flv', '.wma', '.mpg', '.aiff', '.caf', '.m4b'):
        p = tmp_path/f'a{e}'
        assert not is_texty(p) and not openable(p) and not is_media(p), e

def test_tab_open_and_state_give_media_kinds_without_text(tmp_path):
    w = _wav(tmp_path/'a.wav'); (m := tmp_path/'a.mp4').write_bytes((FIXTURES/'tiny.mp4').read_bytes())
    (o := tmp_path/'a.ogv').write_bytes(b'OggS\0\0')
    before = {p: _stamp(p) for p in (w, m)}
    with TestClient(ide_app(Workspace(roots=[str(tmp_path)])), base_url='http://127.0.0.1') as c:
        for p, k in ((w, 'audio'), (m, 'video')):
            assert 'lee-err' not in c.post('/tab/open', params={'path': str(p)}).text
            st = c.get('/tab/state', params={'path': str(p)}).json()
            assert st['kind'] == k and st['path'] == str(p) and 'text' not in st and st['disk_version'], st
        assert 'not a text file' in c.post('/tab/open', params={'path': str(o)}).text
    assert before == {p: _stamp(p) for p in (w, m)}

def test_a_saved_text_tab_on_a_wav_comes_back_as_audio(tmp_path):
    _wav(tmp_path/'a.wav')
    assert Tab(path=str(tmp_path/'a.wav'), kind='text').kind == 'audio'

def test_raw_serves_media_with_range_and_seek(tmp_path):
    """WebKit plays a video only from a 206 answer, and seeking asks for a byte range."""
    w = _wav(tmp_path/'a.wav'); data = w.read_bytes(); n = len(data)
    (m := tmp_path/'a.mov').write_bytes((FIXTURES/'tiny.mp4').read_bytes())
    with TestClient(ide_app(Workspace(roots=[str(tmp_path)])), base_url='http://127.0.0.1') as c:
        r = c.get('/file/raw/a.wav', params={'path': str(w)})
        assert r.status_code == 200 and r.content == data and r.headers['content-type'] == 'audio/wav' and r.headers['accept-ranges'] == 'bytes'
        r = c.get('/file/raw/a.wav', params={'path': str(w)}, headers={'Range': 'bytes=0-1'})
        assert r.status_code == 206 and r.content == data[:2] and r.headers['content-range'] == f'bytes 0-1/{n}'
        r = c.get('/file/raw/a.wav', params={'path': str(w)}, headers={'Range': f'bytes={n//2}-'})
        assert r.status_code == 206 and r.content == data[n//2:] and r.headers['content-range'] == f'bytes {n//2}-{n-1}/{n}'
        r = c.get('/file/raw/a.wav', params={'path': str(w)}, headers={'Range': f'bytes=-100'})
        assert r.status_code == 206 and r.content == data[-100:]
        assert c.get('/file/raw/a.wav', params={'path': str(w)}, headers={'Range': f'bytes={n+10}-'}).status_code == 416
        r = c.get('/file/raw/a.mov', params={'path': str(m)}, headers={'Range': 'bytes=0-'})
        assert r.status_code == 206 and r.headers['content-type'] == 'video/quicktime' and r.content == m.read_bytes()
        assert c.get('/file/raw/x.wav', params={'path': '/etc/hosts'}).status_code == 400
        (t := tmp_path/'x.ogv').write_bytes(b'OggS')
        assert c.get('/file/raw/x.ogv', params={'path': str(t)}).status_code == 400

def test_nothing_writes_a_media_file(tmp_path):
    w = _wav(tmp_path/'a.wav'); before = _stamp(w)
    ws = Workspace(roots=[str(tmp_path)])
    with pytest.raises(Unsafe, match='binary'): ws.fs.read(w)
    with pytest.raises(Unsafe, match='read-only'): ws.fs.write(w, 'text')
    h = WorkspaceHost(ws)
    with pytest.raises(Unsafe): h.read(str(w))
    with pytest.raises(Unsafe): h.write(str(w), 'x')
    assert before == _stamp(w)

def test_open_in_default_app_takes_office_and_media_only(tmp_path, monkeypatch):
    ran, argv = [], []
    monkeypatch.setattr(fs_app, 'open_in_app', lambda p: ran.append(str(p)))
    w = _wav(tmp_path/'a.wav'); (tmp_path/'run.command').write_text('echo hi')
    with TestClient(ide_app(Workspace(roots=[str(tmp_path)])), base_url='http://127.0.0.1') as c:
        assert c.post('/media/open', params={'path': str(w)}).json()['ok']
        assert c.post('/media/open', params={'path': str(tmp_path/'run.command')}).status_code == 400
        assert c.post('/media/open', params={'path': '/etc/hosts'}).status_code == 400
    assert ran == [str(w)]
    monkeypatch.setattr(office.subprocess, 'Popen', lambda a, **kw: argv.append(a))
    office.open_in_app(w); office.open_in_app(tmp_path/'a.docx')
    with pytest.raises(ValueError): office.open_in_app(tmp_path/'run.command')
    assert [a[1] for a in argv] == [str(w), str(tmp_path/'a.docx')]

def test_finder_opens_a_large_media_file_outside_every_folder(tmp_path):
    """A loose file was capped at the 4 MB text limit, so Finder could not open most films."""
    big = tmp_path/'film.mov'
    with open(big, 'wb') as f: f.truncate(8_000_000)
    assert loose_refusal(big) is None
    (txt := tmp_path/'big.txt').write_bytes(b'x' * 5_000_000)
    assert 'too large' in loose_refusal(txt)
    from leela.core.projects import loose_root
    assert _unopenable(str(big), loose_root()) is None
    assert _unopenable(str(_wav(tmp_path/'a.wav')), tmp_path) is None

def test_a_media_disk_version_is_from_the_stat_not_the_bytes(tmp_path, monkeypatch):
    from leela.blocks.tabs import app as tabs_app
    w = _wav(tmp_path/'a.wav'); s = w.stat()
    monkeypatch.setattr(Path, 'read_bytes', lambda self: pytest.fail('hashed a media file'))
    assert tabs_app.disk_version(str(w)) == f'{s.st_size}:{s.st_mtime_ns}'

def test_rename_follows_the_media_kind(tmp_path):
    ws = Workspace(roots=[str(tmp_path)])
    t = Tab(path=str(tmp_path/'a.txt'))
    assert ws.retarget(t, tmp_path/'a.txt', tmp_path/'a.wav').kind == 'audio'
    assert ws.retarget(t, tmp_path/'a.wav', tmp_path/'a.mov').kind == 'video'
    assert ws.retarget(t, tmp_path/'a.mov', tmp_path/'a.md').kind == 'text'
    nb = Tab(path=str(tmp_path/'n.ipynb'))
    assert ws.retarget(nb, tmp_path/'n.ipynb', tmp_path/'n.txt').kind == 'notebook'

def test_attaching_a_video_is_refused_not_sent_as_bytes(tmp_path):
    (m := tmp_path/'a.mp4').write_bytes((FIXTURES/'tiny.mp4').read_bytes())
    with pytest.raises(ValueError, match='cannot take'): Workspace(roots=[str(tmp_path)])._attachment_context([str(m)])

ODD_NAMES = ('Screen Recording 2026-11-04 at 9.46.03 am.mov', 'café.mov', 'café.mp4', 'a #1?.mov', '100% done.mov',
    'say "hi"; x.mov', '録画.mov', 'Screenshot 2026-11-04 at 9.46.03 am.png', 'notes am.pdf')

def test_raw_serves_any_file_name_with_range(tmp_path):
    """macOS names a recording `… 9.46.03 am.mov`, and a non-Latin-1 name in the Content-Disposition header made `/file/raw` answer 400."""
    from urllib.parse import quote, unquote
    from unicodedata import normalize
    tiny = (FIXTURES/'tiny.mp4').read_bytes()
    with TestClient(ide_app(Workspace(roots=[str(tmp_path)])), base_url='http://127.0.0.1') as c:
        for n in ODD_NAMES:
            (p := tmp_path/n).write_bytes(tiny)
            for path in {str(p), normalize('NFC', str(p)), normalize('NFD', str(p))}:
                for dl in (False, True):
                    r = c.get(f'/file/raw/{quote(n, safe="")}', params={'path': path, 'download': dl}, headers={'Range': 'bytes=0-9'})
                    assert r.status_code == 206 and r.content == tiny[:10], (n, path, r.text[:200])
                    cd = r.headers['content-disposition']
                    assert cd.startswith(('attachment' if dl else 'inline') + "; filename*=utf-8''"), cd
                    assert normalize('NFC', unquote(cd.split("''", 1)[1])) == normalize('NFC', n), cd
            p.unlink()

def test_sandbox_takes_odd_names_in_either_unicode_form(tmp_path, monkeypatch):
    """A root, a file and an admitted loose file each resolve by their NFC and NFD paths."""
    from unicodedata import normalize
    from leela.blocks.fs.fs import Sandbox
    forms = lambda p: {normalize('NFC', str(p)), normalize('NFD', str(p))}
    root, out = tmp_path/'Café notes am', tmp_path/'Desktop'
    root.mkdir(); out.mkdir()
    loose = tmp_path/'loose'; loose.mkdir()
    sb = Sandbox([root, loose]); sb.loose = sb.roots[-1]
    for n in ODD_NAMES:
        (p := root/n).write_bytes(b'x'); (q := out/n).write_bytes(b'x')
        for f in forms(p): assert sb._check(f, must_exist=True).samefile(p), f
        for f in forms(q):
            with pytest.raises(Unsafe): sb._check(f)
        sb.admit(q)
        for f in forms(q): assert sb._check(f, must_exist=True).samefile(q), f
    ran = []
    monkeypatch.setattr(fs_app, 'open_in_app', lambda p: ran.append(p.name))
    with TestClient(ide_app(Workspace(roots=[str(root)])), base_url='http://127.0.0.1') as c:
        for n in ODD_NAMES[:7]:
            for f in forms(root/n): assert c.post('/media/open', params={'path': f}).json()['ok'], (n, f)
    assert len(ran) == len([f for n in ODD_NAMES[:7] for f in forms(root/n)])
