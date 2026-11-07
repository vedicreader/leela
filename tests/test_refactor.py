"Refactoring and the language server behind it."

from leela.blocks.fs.fs import Sandbox
from kosha.refactor import replace_plan
from leela.blocks.lsp.lsp import PyrightService

def _plan(root, *a, **kw):
    fs = Sandbox([root])
    return replace_plan(fs.walk(), *a, read=fs.read, **kw)

def test_replace_plan_changes_text_files_and_skips_notebooks(tmp_path):
    root = tmp_path/'project'; root.mkdir()
    (root/'a.py').write_text('value = old\nold_value = old\n')
    (root/'notes.ipynb').write_text('{}')
    rows, skipped = _plan(root, 'old', 'new', word=True)
    assert len(rows) == 1 and rows[0].edits == 2
    assert rows[0].after == 'value = new\nold_value = new\n'
    assert str(root/'notes.ipynb') in skipped


def test_pyright_is_optional_and_reports_status(tmp_path, monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: None)
    # `find_server` falls back to the extras directory, which is where a frozen app installs one.
    # Stubbing PATH alone made this pass or fail on whether this machine had ever installed a
    # language server from the Tools row.
    monkeypatch.setattr('leela.extras_bin', lambda: tmp_path/'no-extras')
    service = PyrightService(tmp_path)
    assert not service.available and not service.start()
    rows, note = service.diagnostics(tmp_path/'a.py', 'x: int = "bad"')
    assert rows == [] and note


FAKE_SERVER = r'''
import sys, json
def read():
    h = {}
    while True:
        l = sys.stdin.buffer.readline()
        if not l: sys.exit()
        if l in (b'\r\n', b'\n'): break
        k, _, v = l.decode().partition(':'); h[k.lower()] = v.strip()
    return json.loads(sys.stdin.buffer.read(int(h['content-length'])))
def send(m):
    raw = json.dumps(m).encode()
    sys.stdout.buffer.write(b'Content-Length: %d\r\n\r\n' % len(raw) + raw); sys.stdout.buffer.flush()
mode, configured, waiting = sys.argv[1], False, None
while True:
    m = read(); method = m.get('method')
    if method == 'initialize': send({'jsonrpc': '2.0', 'id': m['id'], 'result': {'capabilities': {}}})
    elif method == 'initialized' and mode == 'config':
        send({'jsonrpc': '2.0', 'id': 1, 'method': 'workspace/configuration', 'params': {'items': [{'section': 'a'}, {'section': 'b'}]}})
    elif method is None and 'id' in m:
        configured = m['result'] == [None, None]
        if configured and waiting: send({'jsonrpc': '2.0', 'id': waiting, 'result': [{'name': 'f'}]})
    elif method == 'textDocument/documentSymbol' and mode == 'config':
        if configured: send({'jsonrpc': '2.0', 'id': m['id'], 'result': [{'name': 'f'}]})
        else: waiting = m['id']
'''

def _fake_service(tmp_path, mode):
    import sys
    from leela.blocks.lsp.lsp import LspService
    script = tmp_path/'fake_lsp.py'; script.write_text(FAKE_SERVER)
    s = LspService(tmp_path)
    s.server, s.argv = 'fake', [sys.executable, str(script), mode]; s.command = sys.executable
    return s

def test_a_request_the_server_makes_is_answered_and_a_silent_server_is_not_waited_on_twice(tmp_path, monkeypatch):
    """basedpyright asks `workspace/configuration` first and answers nothing until it is replied to; its request id also collides with ours."""
    import time
    f = tmp_path/'a.py'; f.write_text('def f(): pass\n')
    s = _fake_service(tmp_path, 'config')
    # The 1.5 s soft wait covers the configuration round trip too, which a loaded runner took longer than.
    with monkeypatch.context() as m:
        m.setattr('leela.blocks.lsp.lsp.SOFT_WAIT', 30)
        try: assert s.request('textDocument/documentSymbol', f, f.read_text(), None) == [{'name': 'f'}]
        finally: s.close()
    s = _fake_service(tmp_path, 'mute')
    try:
        for method, extra in [('textDocument/documentSymbol', None), ('textDocument/inlayHint', {'range': {}})]:
            assert s.request(method, f, f.read_text(), None, 0, extra) is None
            t = time.monotonic()
            assert s.request(method, f, f.read_text(), None, 0, extra) is None
            assert time.monotonic() - t < .1, 'a method that just timed out is answered empty at once'
    finally: s.close()
