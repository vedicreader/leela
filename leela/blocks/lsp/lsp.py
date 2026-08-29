"Small managed Language Server Protocol client, one service per language."
from __future__ import annotations
import json, os, queue, shutil, subprocess, threading, time
from pathlib import Path
from urllib.parse import quote

from ...core.langs import servers_for

#: Servers Leela will drive for Python, in the order they are tried. Each speaks LSP on stdio and
#: differs only in how it is asked to. `basedpyright` leads because it answers everything `start`
#: asks for and carries its own node, so installing it needs neither a system node nor a download
#: at first run. Every language's list lives in `core.langs`; this is Python's, named here because
#: Python is the language the rest of Leela reaches for without saying so.
SERVERS = servers_for('python')

def find_server(lang='python'):
    """The first language server for `lang`, as `(name, argv)`, or `(None, None)`.

    PATH first, then the extras directory. A frozen app installs an optional tool there because the
    bundle is signed and read-only, and nothing puts its `bin` on PATH, so a server installed from
    the Tools row was found by nothing and the row went on offering to install it.
    """
    from ... import extras_bin
    for name, args in servers_for(lang):
        if (found := shutil.which(name)): return name, [found, *args]
        here = extras_bin()/name
        if here.is_file() and os.access(here, os.X_OK): return name, [str(here), *args]
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
        self.process, self._seq = None, 0
        self._pending, self._diagnostics, self._versions = {}, {}, {}
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
    def start(self):
        # The check and the spawn had nothing between them, and a notebook mount fires one lint
        # request per mounted cell, so a window ended up running two language servers with one of
        # them orphaned. The handshake is inside the lock: the second caller waits for the first
        # server rather than starting a second.
        with self._start_lock: return self._start()

    def _start(self):
        if self.alive or not self.available: return self.alive
        self.process = subprocess.Popen(self.argv, cwd=str(self.root), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
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
            self.note = f'{self.server} failed: {type(e).__name__}: {e}'
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
        row = answer.get(timeout=timeout)
        if 'error' in row: raise RuntimeError(row['error'])
        return row.get('result')
    def _notify(self, method, params): self._send({'jsonrpc': '2.0', 'method': method, 'params': params})
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
                if 'id' in msg and msg['id'] in self._pending: self._pending.pop(msg['id']).put(msg)
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
        uri = self.sync(path, text)
        if not uri: raise RuntimeError(self.note)
        params = {'textDocument': {'uri': uri}}
        if line is not None: params['position'] = {'line': max(0, int(line)), 'character': max(0, int(character))}
        params.update(extra or {})
        return self._request(method, params, timeout)
    def diagnostics(self, path, text, timeout=2.5):
        started, uri = time.time(), self.sync(path, text)
        if not uri: return [], self.note
        while time.time() - started < timeout:
            row = self._diagnostics.get(uri)
            if row and row[0] >= started: return row[1], self.note
            time.sleep(.025)
        return self._diagnostics.get(uri, (0, []))[1], f'{self.server} diagnostics timed out; showing the latest result'
    def close(self):
        if self.process:
            try: self._notify('exit', {})
            except Exception: pass
            try: self.process.terminate()
            except Exception: pass
        self.process = None

#: The name this was called when Python was the only language it served.
PyrightService = LspService
