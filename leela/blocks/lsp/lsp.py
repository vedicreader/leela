"Small managed Language Server Protocol client, one service per language."
from __future__ import annotations
import json, os, queue, shutil, subprocess, sysconfig, threading, time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from ...core.langs import servers_for

#: Servers Leela will drive for Python, in the order they are tried. Every language's list lives
#: in `core.langs`; this is Python's.
SERVERS = servers_for('python')
#: Seconds a server may go unused before the workspace closes it. A return after that starts it again.
LSP_IDLE = 600
#: Questions asked on every mount, which a server still indexing may not answer. They wait `SOFT_WAIT`
#: seconds, and after one timeout are answered empty at once for `SOFT_COOL` seconds.
SOFT = ('textDocument/documentSymbol', 'textDocument/inlayHint')
SOFT_WAIT, SOFT_COOL = 1.5, 30

#: `pip install --target` bakes the installing interpreter into each script's shebang, and that
#: interpreter may be a deleted build or the other of app and checkout. Native binaries (`ty`, `pyrefly`) run as themselves.
_RUN_EXTRA = ('import os, runpy, sys; sys.argv[:2] = sys.argv[1:2]; '
    'sys.path.insert(0, os.path.dirname(os.path.dirname(sys.argv[0]))); runpy.run_path(sys.argv[0], run_name="__main__")')

def _py_script(p):
    "Whether `p` starts with a Python shebang."
    with open(p, 'rb') as f: line = f.readline(256)
    return line.startswith(b'#!') and b'python' in line

def find_server(lang='python'):
    "The first language server for `lang`, as `(name, argv)`, or `(None, None)`."
    from ... import extras_bin
    from ...core.host import on
    from ..runtime.kernels import runtime_python
    for name, args in servers_for(lang):
        if (found := shutil.which(name)): return name, [found, *args]
        # the launcher keeps its env's bin off PATH, so a kernel or shell never finds Leela's `python`
        if on() and (own := Path(sysconfig.get_path('scripts'))/name).is_file() and os.access(own, os.X_OK): return name, [str(own), *args]
        here = extras_bin()/name
        if not (here.is_file() and os.access(here, os.X_OK)): continue
        return name, [runtime_python(), '-c', _RUN_EXTRA, str(here), *args] if _py_script(here) else [str(here), *args]
    return None, None

def _why_unavailable(command, root, lang='python'):
    "Why there is no language server, in the words the status pill shows. Empty means it is there."
    if command: return ''
    if not root: return 'open a project folder for a language server'
    if not servers_for(lang): return f'Leela knows no language server for {lang}'
    return f'a {lang} language server is not installed: get one from settings, models and updates'

class LspService:
    "One language server for one language in one project root."
    def __init__(self, root, lang='python'):
        self.root = Path(root).resolve() if root else None
        self.lang = lang or 'python'
        self.server, self.argv = find_server(self.lang) if self.root else (None, None)
        self.command = self.argv[0] if self.argv else None
        self.process, self._seq, self.retired = None, 0, False
        self.used, self.busy = time.monotonic(), 0
        self._pending, self._diagnostics, self._versions, self._cool = {}, {}, {}, {}
        self._lock = threading.Lock()
        #: Held across the spawn and the handshake. `_lock` is the one that guards writes, and
        #: `start` writes, so this cannot be the same one.
        self._start_lock = threading.Lock()
        self.note = _why_unavailable(self.command, self.root, self.lang)
    @property
    def available(self): return bool(self.command)
    @property
    def alive(self): return bool(self.process and self.process.poll() is None)
    def _uri(self, path): return 'file://' + quote(str(Path(path).resolve()))
    def idle(self, now):
        "Unused for longer than `LSP_IDLE` and serving no request."
        return not self.busy and now - self.used > LSP_IDLE
    @contextmanager
    def _using(self):
        with self._lock: self.busy += 1
        try: yield
        finally:
            with self._lock: self.busy -= 1; self.used = time.monotonic()
    def start(self):
        # The handshake is inside the lock: the second caller waits for the first server rather
        # than starting a second.
        with self._start_lock: return self._start()

    def _start(self):
        if self.retired: return False
        if self.alive or not self.available: return self.alive
        self.process = subprocess.Popen(self.argv, cwd=str(self.root), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        if self.retired: self.close(); return False   # `retire` landed while the process was starting
        threading.Thread(target=self._read, daemon=True, name=f'leela-lsp-{self.lang}').start()
        try:
            self._request('initialize', {'processId': os.getpid(), 'rootUri': self._uri(self.root),
                'capabilities': {'workspace': {'workspaceEdit': {'documentChanges': True}},
                    'textDocument': {'publishDiagnostics': {'relatedInformation': True},
                    'hover': {'contentFormat': ['markdown', 'plaintext']},
                    'documentSymbol': {'hierarchicalDocumentSymbolSupport': True},
                    'rename': {'prepareSupport': True}, 'inlayHint': {}}}}, timeout=8)
            self._notify('initialized', {})
            self.note = f'{self.server} connected'
        except Exception as e:
            if not self.retired: self.note = f'{self.server} failed: {type(e).__name__}: {e}'
            self.close()
            return False
        return True
    def _send(self, payload):
        raw = json.dumps(payload, separators=(',', ':')).encode()
        with self._lock:
            self.process.stdin.write(f'Content-Length: {len(raw)}\r\n\r\n'.encode() + raw)
            self.process.stdin.flush()
    def _request(self, method, params, timeout=5):
        self._seq += 1
        ident, answer = self._seq, queue.Queue(1)
        self._pending[ident] = answer
        self._send({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params})
        try: row = answer.get(timeout=timeout)
        finally: self._pending.pop(ident, None)
        if 'error' in row: raise RuntimeError(row['error'])
        return row.get('result')
    def _notify(self, method, params): self._send({'jsonrpc': '2.0', 'method': method, 'params': params})
    def _answer(self, msg):
        "Reply to a request the server made of us: a server that is not answered never answers back."
        items = (msg.get('params') or {}).get('items') or []
        result = [None] * len(items) if msg['method'] == 'workspace/configuration' else None
        self._send({'jsonrpc': '2.0', 'id': msg['id'], 'result': result})
    def _read(self):
        stream = self.process.stdout
        while self.alive:
            try:
                headers = {}
                while True:
                    line = stream.readline()
                    if not line: return
                    if line in (b'\r\n', b'\n'): break
                    key, _, value = line.decode('ascii', 'replace').partition(':')
                    headers[key.lower()] = value.strip()
                body = stream.read(int(headers.get('content-length', '0')))
                msg = json.loads(body)
                if 'id' in msg and 'method' in msg: self._answer(msg)
                elif 'id' in msg and msg['id'] in self._pending: self._pending.pop(msg['id']).put(msg)
                elif msg.get('method') == 'textDocument/publishDiagnostics':
                    p = msg.get('params', {})
                    self._diagnostics[p.get('uri', '')] = (time.time(), p.get('diagnostics', []))
            except Exception: return
    def sync(self, path, text):
        if not self.start(): return None
        uri = self._uri(path)
        version = self._versions[uri] = self._versions.get(uri, 0) + 1
        if version == 1:
            self._notify('textDocument/didOpen',
                {'textDocument': {'uri': uri, 'languageId': self.lang, 'version': version, 'text': text}})
        else:
            self._notify('textDocument/didChange',
                {'textDocument': {'uri': uri, 'version': version}, 'contentChanges': [{'text': text}]})
        return uri
    def request(self, method, path, text, line=0, character=0, extra=None, timeout=5):
        soft = method in SOFT
        if soft and time.monotonic() < self._cool.get(method, 0): return None
        with self._using():
            try: return self._ask(method, path, text, line, character, extra, SOFT_WAIT if soft else timeout)
            except queue.Empty:
                if not soft: raise
                self._cool[method] = time.monotonic() + SOFT_COOL
    def _ask(self, method, path, text, line, character, extra, timeout):
        uri = self.sync(path, text)
        if not uri: raise RuntimeError(self.note)
        params = {'textDocument': {'uri': uri}}
        if line is not None: params['position'] = {'line': max(0, int(line)), 'character': max(0, int(character))}
        params.update(extra or {})
        return self._request(method, params, timeout)
    def diagnostics(self, path, text, timeout=2.5):
        with self._using(): return self._diagnose(path, text, timeout)
    def _diagnose(self, path, text, timeout):
        started, uri = time.time(), self.sync(path, text)
        if not uri: return [], self.note
        while time.time() - started < timeout:
            row = self._diagnostics.get(uri)
            if row and row[0] >= started: return row[1], self.note
            time.sleep(.025)
        return self._diagnostics.get(uri, (0, []))[1], f'{self.server} diagnostics timed out; showing the latest result'
    def retire(self):
        "Close for good: a caller still holding this service cannot start another process."
        self.retired, self.note = True, f'{self.server or self.lang} was stopped'
        self.close()
    def close(self):
        "Stop the server and forget what it was told, so a later start opens every document afresh."
        if (p := self.process):
            try: self._notify('exit', {})
            except Exception: pass
            try: p.terminate(); p.wait(2)
            except subprocess.TimeoutExpired: p.kill()
            except Exception: pass
        self.process = None
        for q in list(self._pending.values()):
            try: q.put_nowait({'error': f'{self.server} closed'})
            except queue.Full: pass
        self._pending.clear(); self._versions.clear(); self._diagnostics.clear()

#: The name this was called when Python was the only language it served.
PyrightService = LspService
