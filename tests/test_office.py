"Word, PowerPoint and Excel files open in a read-only viewer tab, render as escaped HTML, and read as text for the agent."
import hashlib, io
import pytest
from PIL import Image
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.agent.ai import WorkspaceHost
from leela.blocks.fs import app as fs_app
from leela.blocks.fs.fs import Sandbox, Unsafe, is_texty
from leela.blocks.fs.office import _Images, _safe, office_html, office_text, sheet_rows
from leela.workspace import Tab, Workspace, openable

def _png():
    b = io.BytesIO(); Image.new('RGB', (4, 4), (200, 30, 30)).save(b, 'PNG'); return b.getvalue()

def _docx(p):
    import docx
    d = docx.Document()
    d.add_heading('Quarterly report', 1)
    for s in ('first point', 'second point'): d.add_paragraph(s, style='List Bullet')
    t = d.add_table(rows=2, cols=2); t.cell(0, 0).text = 'Region'; t.cell(1, 1).text = '42'
    d.add_paragraph('<script>alert(1)</script><img src=x onerror=alert(2)>')
    d.add_picture(io.BytesIO(_png()))
    d.save(p); return p

def _pptx(p):
    from pptx import Presentation
    from pptx.util import Inches
    pr = Presentation()
    s = pr.slides.add_slide(pr.slide_layouts[1])
    s.shapes.title.text = 'Plan for <b>Q3</b>'
    s.placeholders[1].text = 'Ship the viewer'
    s.notes_slide.notes_text_frame.text = 'Say this slowly'
    s2 = pr.slides.add_slide(pr.slide_layouts[5])
    s2.shapes.title.text = 'Numbers'
    tb = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    tb.cell(0, 0).text, tb.cell(1, 1).text = 'Cost', '99'
    s2.shapes.add_picture(io.BytesIO(_png()), Inches(1), Inches(4))
    pr.save(p); return p

def _xlsx(p, rows=500):
    import xlsxwriter
    wb = xlsxwriter.Workbook(str(p))
    a = wb.add_worksheet('Sales')
    a.write_row(0, 0, ['item', 'n'])
    for i in range(1, rows): a.write_row(i, 0, [f'row{i}', i])
    a.write_formula(rows, 1, f'=SUM(B2:B{rows})', None, 7777)
    wb.add_worksheet('Notes <x>').write(0, 0, 'hello sheet two')
    wb.close(); return p

def _stamp(p): return p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()

@pytest.fixture
def files(tmp_path):
    return {k: f(tmp_path/f'a.{k}') for k, f in (('docx', _docx), ('pptx', _pptx), ('xlsx', _xlsx))}

def test_office_files_are_not_text_and_open_as_viewers(files, tmp_path):
    for p in files.values(): assert not is_texty(p) and openable(p) and Tab(path=str(p)).kind == 'office'
    for sfx in ('doc', 'xls', 'ppt', 'docm', 'odt'): assert not openable(tmp_path/f'old.{sfx}')

def test_docx_html_keeps_structure_and_escapes_script(files):
    h = office_html(files['docx'])
    assert '<h1>Quarterly report</h1>' in h and '<li>first point</li>' in h and '<table>' in h and '42' in h
    assert 'src="data:image/png;base64,' in h
    assert '<script' not in h and '<img src=x' not in h and '&lt;script&gt;alert(1)&lt;/script&gt;&lt;img src=x onerror=alert(2)&gt;' in h

def test_pptx_html_has_numbered_slides_tables_images_and_notes(files):
    h = office_html(files['pptx'])
    assert h.count('class="lee-office-slide"') == 2 and 'Slide 1' in h and 'Slide 2' in h
    assert h.count('Plan for &lt;b&gt;Q3&lt;/b&gt;') == 1 and 'Ship the viewer' in h
    assert '<summary>Speaker notes</summary>' in h and 'Say this slowly' in h
    assert '99' in h and 'src="data:image/png;base64,' in h

def test_xlsx_html_names_sheets_shows_formula_value_and_pages(files):
    h = office_html(files['xlsx'])
    assert 'Sales' in h and 'Notes &lt;x&gt;' in h and 'hello sheet two' in h
    assert 'row199' in h and 'row200' not in h and 'data-next="200"' in h
    more, n, left = sheet_rows(files['xlsx'], 0, 400, 200)
    assert 'row401' in more and '7777' in more and '=SUM' not in more and n == 101 and not left
    with pytest.raises(ValueError, match='no sheet 3'): sheet_rows(files['xlsx'], 2)
    with pytest.raises(ValueError): sheet_rows(files['xlsx'], 0, -1)

def test_a_formula_with_no_saved_value_shows_the_formula(tmp_path):
    from openpyxl import Workbook
    wb = Workbook(); wb.active['A1'], wb.active['A2'] = 2, '=A1*3'; wb.save(p := tmp_path/'f.xlsx')
    assert '=A1*3' in sheet_rows(p)[0]

def test_images_that_make_a_request_or_cannot_show_become_labels():
    assert '<img' not in str(_safe('<p><img src="https://track.example/p.png" alt="pixel"></p>')) and 'pixel' in str(_safe('<img src="http://x/a" alt="pixel">'))
    assert 'not shown: x-emf' in str(_Images()('image/x-emf', b'\x01\x00'))

def test_text_for_the_agent_and_nothing_writes(files):
    before = {k: _stamp(p) for k, p in files.items()}
    assert 'Quarterly report' in office_text(files['docx']) and 'Say this slowly' in office_text(files['pptx'])
    assert '7777' in office_text(files['xlsx'])
    fs = Sandbox([files['docx'].parent])
    for p in files.values():
        with pytest.raises(Unsafe): fs.read(p)
        with pytest.raises(Unsafe, match='read-only'): fs.write(p, 'text')
    with pytest.raises(Unsafe): fs.write(files['docx'].parent/'new.docx', 'text')
    assert before == {k: _stamp(p) for k, p in files.items()}

def test_the_agent_reads_text_and_cannot_write(files):
    ws = Workspace(roots=[str(files['docx'].parent)])
    before = {k: _stamp(p) for k, p in files.items()}
    h = WorkspaceHost(ws)
    assert 'Quarterly report' in h.read(str(files['docx'])) and 'Sales' in h.read(str(files['xlsx']))
    with pytest.raises(Unsafe): h.write(str(files['pptx']), 'x')
    text, _ = ws._attachment_context([str(files['docx'])])
    assert 'Quarterly report' in text and 'PK' not in text
    assert before == {k: _stamp(p) for k, p in files.items()}

def test_only_office_and_media_files_open_in_the_default_app(tmp_path, monkeypatch):
    from leela.blocks.fs import office
    ran = []
    monkeypatch.setattr(office.subprocess, 'Popen', lambda argv, **kw: ran.append(argv))
    with pytest.raises(ValueError): office.open_in_app(tmp_path/'run.command')
    office.open_in_app(tmp_path/'a.xlsx')
    assert ran == [[ran[0][0], str(tmp_path/'a.xlsx')]] and ran[0][0] in ('open', 'xdg-open')

def test_a_broken_office_file_says_so(tmp_path):
    (p := tmp_path/'~$bad.docx').write_bytes(b'not a zip')
    with pytest.raises(ValueError, match='not a valid docx'): office_html(p)

def test_rename_follows_the_kind(tmp_path):
    ws = Workspace(roots=[str(tmp_path)])
    t = Tab(path=str(tmp_path/'a.txt'))
    assert ws.retarget(t, tmp_path/'a.txt', tmp_path/'a.docx').kind == 'office'
    assert ws.retarget(t, tmp_path/'a.docx', tmp_path/'a.md').kind == 'text'

def test_routes_open_each_kind_as_a_viewer_tab(files, monkeypatch):
    root = files['docx'].parent
    before = {k: _stamp(p) for k, p in files.items()}
    opened = []
    monkeypatch.setattr(fs_app, 'open_in_app', opened.append)
    (root/'run.command').write_text('echo hi')
    ws = Workspace(roots=[str(root)])
    with TestClient(ide_app(ws), base_url='http://127.0.0.1') as c:
        for k, p in files.items():
            c.get('/tab/open', params={'path': str(p)})
            st = c.get('/tab/state', params={'path': str(p)}).json()
            assert st['kind'] == 'office' and 'text' not in st, st
            assert 'lee-office-view' in c.get('/office/view', params={'path': str(p)}).json()['html']
            assert c.get('/office/text', params={'path': str(p)}).json()['text']
        d = c.get('/office/rows', params={'path': str(files['xlsx']), 'sheet': 0, 'start': 200}).json()
        assert 'row201' in d['html'] and d['count'] == 200 and d['more']
        assert c.post('/office/open', params={'path': str(files['docx'])}).json()['ok']
        assert c.post('/office/open', params={'path': str(root/'run.command')}).status_code == 400
        assert c.get('/office/view', params={'path': '/etc/hosts'}).status_code == 400
    assert [str(p) for p in opened] == [str(files['docx'])]
    assert before == {k: _stamp(p) for k, p in files.items()}

def test_restoring_an_old_text_version_leaves_the_file_alone(files):
    p = files['docx']
    before = _stamp(p)
    ws = Workspace(roots=[str(p.parent)])
    with TestClient(ide_app(ws), base_url='http://127.0.0.1') as c:
        row = ws.history.record(str(p), 'PK\x03\x04 garbage from the old text tab', 'save')
        r = c.post('/history/restore', json={'id': row['id']})
        assert r.status_code == 400 and 'read-only' in r.json()['error']
    assert _stamp(p) == before
