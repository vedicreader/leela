"On macOS the office tab shows Quick Look's own preview: a fake qlmanage stands in, so no test reaches the real one."
import os, plistlib, sys, threading, time
import pytest
from fastcore.all import AttrDict, Path
from collections import OrderedDict
from types import SimpleNamespace
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.fs import office
from leela.workspace import Workspace
from test_office import _docx, _pptx, _xlsx

FAKE = r'''#!{py}
import os, plistlib, sys, time
from pathlib import Path
open({log!r}, 'a').write(' '.join(sys.argv[1:3]) + '\n')
a = sys.argv[1:]
if a[0] == '-t':
    for f in a[5:]: Path(a[4], Path(f).name + '.png').write_bytes(b'\x89PNG fake')
    sys.exit(0)
out, src = Path(a[2]), Path(a[3])
stem = src.stem
if stem == 'hang': time.sleep(60)
if stem == 'empty': sys.exit(0)
pv = out/(src.name + '.qlpreview'); pv.mkdir()
props = dict(MimeType='application/pdf' if stem == 'pdfmime' else 'text/html', TextEncoding='UTF-8')
(pv/'PreviewProperties.plist').write_bytes(plistlib.dumps(props))
if stem == 'book':
    (pv/'Preview.html').write_text('<html><head><script src="Attachment8.js"></script></head><body><div id="tabs">'
        '<div class="TabViewItem selected"><div class="TabHeader">Sales</div><a href="Attachment2.html"></a></div>'
        '<div class="TabViewItem"><div class="TabHeader">&lt;img src=x onerror=alert(1)&gt;</div><a href="Attachment7.html"></a></div></div></body></html>')
    (pv/'Attachment2.html').write_text('<table>' + '<tr><td>r</td></tr>' * 4096 + '</table>')
    (pv/'Attachment7.html').write_text('<table><tr><td>second</td></tr></table>')
    (pv/'Attachment8.js').write_text('alert(1)')
else:
    (pv/'Preview.html').write_text('<html><body><div class="slide">Slide one</div><img src="Attachment1.pdf" style="top:1">'
        '<img src="Attachment2.png"><a href="https://evil.example/x" class="l">a link</a><area href=http://evil.example></body></html>')
    (pv/'Attachment1.pdf').write_bytes(b'%PDF-1.3 fake'); (pv/'Attachment2.png').write_bytes(b'\x89PNG pic')
'''

@pytest.fixture
def ql(tmp_path, monkeypatch):
    "A fake qlmanage, a fresh cache, and the log of its runs."
    (d := tmp_path/'bin').mkdir()
    log = tmp_path/'ql.log'
    (fake := d/'qlmanage').write_text(FAKE.format(py=sys.executable, log=str(log)))
    fake.chmod(0o755)
    monkeypatch.setattr(office, 'QL', str(fake))
    monkeypatch.setattr(office.sys, 'platform', 'darwin')
    (root := tmp_path/'cache').mkdir()
    monkeypatch.setattr(office, '_ql', SimpleNamespace(root=root, keys=OrderedDict(), tokens={}, locks={}, lock=threading.Lock()))
    return AttrDict(log=log, runs=lambda: log.read_text().splitlines() if log.exists() else [], root=root)

@pytest.fixture
def docs(tmp_path):
    (d := tmp_path/'docs').mkdir()
    return AttrDict(deck=_pptx(d/'a.pptx'), doc=_docx(d/'a.docx'), book=_xlsx(d/'book.xlsx'), dir=d)

def test_a_deck_becomes_one_page_with_charts_as_png_and_no_links(ql, docs):
    r = office.quicklook(docs.deck)
    assert r['pages'] == [{'name': '', 'src': 'Preview.html', 'clipped': False}] and len(r['token']) >= 20
    f, src = office.quicklook_file(r['token'], 'Preview.html')
    h = f.read_text()
    assert src == docs.deck.resolve() and 'src="Attachment1.pdf.png"' in h and 'src="Attachment2.png"' in h
    assert 'evil.example' not in h and '<a class="l">a link</a>' in h and h.startswith("<style>@font-face{font-family:'Calibri'") and '<!' not in h
    assert ql.runs() == ['-p -o', '-t -s']

def test_a_workbook_gives_a_page_for_each_sheet_and_flags_a_clipped_sheet(ql, docs):
    r = office.quicklook(docs.book)
    assert [(p['name'], p['src'], p['clipped']) for p in r['pages']] == [('Sales', 'Attachment2.html', True), ('<img src=x onerror=alert(1)>', 'Attachment7.html', False)]
    assert ql.runs() == ['-p -o']

def test_the_cache_runs_once_and_follows_a_change(ql, docs):
    a = office.quicklook(docs.doc)
    ts = [threading.Thread(target=office.quicklook, args=(docs.doc,)) for _ in range(4)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert office.quicklook(docs.doc) == a and ql.runs().count('-p -o') == 1
    old = office.quicklook_file(a['token'], 'Preview.html')[0]
    os.utime(docs.doc, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))
    b = office.quicklook(docs.doc)
    assert b['token'] != a['token'] and office.quicklook_file(a['token'], 'Preview.html') is None and not old.exists()

def test_the_cache_keeps_a_few_previews(ql, docs, monkeypatch):
    monkeypatch.setattr(office, 'QL_KEEP', 2)
    toks = [office.quicklook(p)['token'] for p in (docs.deck, docs.doc, docs.book)]
    assert [office.quicklook_file(t, 'Preview.html') is not None for t in toks] == [False, True, True]
    assert len(list(ql.root.iterdir())) == 2

@pytest.mark.parametrize('stem,msg', [('empty', 'could not show'), ('pdfmime', 'gave no page')])
def test_quick_look_that_gives_no_page_is_an_error(ql, docs, stem, msg):
    p = _docx(docs.dir/f'{stem}.docx')
    with pytest.raises(office.QuickLookError, match=msg): office.quicklook(p)
    assert not list(ql.root.iterdir()) and not office._ql.keys

def test_a_hung_quick_look_is_stopped(ql, docs, monkeypatch):
    monkeypatch.setattr(office, 'QL_TIMEOUT', 1)
    t = time.time()
    with pytest.raises(office.QuickLookError, match='too long'): office.quicklook(_docx(docs.dir/'hang.docx'))
    assert time.time() - t < 10

def test_off_mac_there_is_no_quick_look(ql, docs, monkeypatch):
    monkeypatch.setattr(office.sys, 'platform', 'linux')
    with pytest.raises(office.NoQuickLook) as e: office.quicklook(docs.doc)
    assert e.value.kind == 'no-quicklook' and ql.runs() == []

def test_a_file_name_outside_the_preview_is_refused(ql, docs):
    t = office.quicklook(docs.deck)['token']
    for name in ('../ql.log', '.hidden', 'PreviewProperties.plist', 'a/b.html', 'Attachment8.js'):
        assert office.quicklook_file(t, name) is None, name
    assert office.quicklook_file('nope', 'Preview.html') is None

def test_runs_that_ended_leave_no_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(office.tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(office, '_ql', SimpleNamespace(root=None, keys=OrderedDict(), tokens={}, locks={}, lock=threading.Lock()))
    monkeypatch.setattr(office.atexit, 'register', lambda *a: None)
    (dead := tmp_path/'leela-ql-999999999-x').mkdir(); (live := tmp_path/f'leela-ql-{os.getppid()}-y').mkdir()
    root = office._ql_root()
    assert not dead.exists() and live.exists() and root.name.startswith(f'leela-ql-{os.getpid()}-')

def test_routes_serve_the_preview_with_a_strict_policy(ql, docs, tmp_path):
    (out := tmp_path/'outside').mkdir()
    (docs.dir/'link.docx').symlink_to(_docx(out/'x.docx'))
    ws = Workspace(roots=[str(docs.dir)])
    with TestClient(ide_app(ws), base_url='http://127.0.0.1') as c:
        r = c.get('/office/quicklook', params={'path': str(docs.book)}).json()
        assert r['ok'] and [p['name'] for p in r['pages']][0] == 'Sales'
        g = c.get(f"/office/ql/{r['token']}/Attachment7.html")
        assert g.status_code == 200 and 'second' in g.text and g.headers['content-type'].startswith('text/html')
        csp = g.headers['content-security-policy']
        assert "default-src 'none'" in csp and 'sandbox allow-same-origin' in csp and 'script' not in csp and g.headers['x-content-type-options'] == 'nosniff'
        assert c.get(f"/office/ql/{r['token']}/Attachment8.js").status_code == 404
        gone = c.get('/office/ql/nope/Preview.html')
        assert gone.status_code == 404 and 'Open the file again' in gone.json()['error']
        assert c.get('/office/quicklook', params={'path': '/etc/hosts'}).status_code == 400
        assert c.get('/office/quicklook', params={'path': str(docs.dir/'link.docx')}).status_code == 400
        f = c.get('/office/quicklook', params={'path': str(_docx(docs.dir/'empty.docx'))}).json()
        assert not f['ok'] and f['kind'] == 'quicklook'
        d = c.get('/office/quicklook', params={'path': str(docs.deck)}).json()
        assert c.get(f"/office/ql/{d['token']}/Attachment1.pdf").headers['content-type'] == 'application/pdf'
        docs.deck.unlink()   # a file that has gone is not served from the cache
        assert c.get(f"/office/ql/{d['token']}/Preview.html").status_code == 404
        office.sys.platform = 'linux'
        n = c.get('/office/quicklook', params={'path': str(docs.doc)}).json()
        assert not n['ok'] and n['kind'] == 'no-quicklook'
