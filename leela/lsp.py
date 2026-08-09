"""Small managed Language Server Protocol client for optional Pyright diagnostics."""
from __future__ import annotations
import json, os, queue, shutil, subprocess, threading, time
from pathlib import Path
from urllib.parse import quote


class PyrightService:
    def __init__(self, root):
        self.root = Path(root).resolve() if root else None
        self.command = shutil.which('pyright-langserver') if self.root else None
        self.process = None; self._seq = 0; self._pending = {}; self._diagnostics = {}; self._versions = {}
        self._lock = threading.Lock(); self.note = '' if self.command else ('open a project folder for Pyright' if not self.root else 'pyright-langserver is not installed')

    @property
    def available(self): return bool(self.command)
    @property
    def alive(self): return bool(self.process and self.process.poll() is None)

    def _uri(self, path): return 'file://' + quote(str(Path(path).resolve()))

    def start(self):
        if self.alive or not self.available: return self.alive
        self.process = subprocess.Popen([self.command, '--stdio'], cwd=str(self.root), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        threading.Thread(target=self._read, daemon=True, name='leela-pyright').start()
        try:
            self._request('initialize', {'processId': os.getpid(), 'rootUri': self._uri(self.root),
                'capabilities': {'workspace': {'workspaceEdit': {'documentChanges': True}},
                    'textDocument': {'publishDiagnostics': {'relatedInformation': True},
                    'hover': {'contentFormat': ['markdown', 'plaintext']},
                    'documentSymbol': {'hierarchicalDocumentSymbolSupport': True},
                    'rename': {'prepareSupport': True}, 'inlayHint': {}}}}, timeout=8)
            self._notify('initialized', {})
            self.note = 'Pyright connected'
        except Exception as e:
            self.note = f'Pyright failed: {type(e).__name__}: {e}'; self.close(); return False
        return True

    def _send(self, payload):
        raw = json.dumps(payload, separators=(',', ':')).encode()
        with self._lock:
            self.process.stdin.write(f'Content-Length: {len(raw)}\r\n\r\n'.encode() + raw); self.process.stdin.flush()

    def _request(self, method, params, timeout=5):
        self._seq += 1; ident = self._seq; answer = queue.Queue(1); self._pending[ident] = answer
        self._send({'jsonrpc':'2.0','id':ident,'method':method,'params':params})
        row = answer.get(timeout=timeout)
        if 'error' in row: raise RuntimeError(row['error'])
        return row.get('result')

    def _notify(self, method, params): self._send({'jsonrpc':'2.0','method':method,'params':params})

    def _read(self):
        stream = self.process.stdout
        while self.alive:
            try:
                headers = {}
                while True:
                    line = stream.readline()
                    if not line: return
                    if line in (b'\r\n', b'\n'): break
                    key, _, value = line.decode('ascii', 'replace').partition(':'); headers[key.lower()] = value.strip()
                body = stream.read(int(headers.get('content-length', '0')))
                msg = json.loads(body)
                if 'id' in msg and msg['id'] in self._pending: self._pending.pop(msg['id']).put(msg)
                elif msg.get('method') == 'textDocument/publishDiagnostics':
                    p = msg.get('params', {}); self._diagnostics[p.get('uri', '')] = (time.time(), p.get('diagnostics', []))
            except Exception: return

    def sync(self, path, text):
        if not self.start(): return None
        uri = self._uri(path); version = self._versions.get(uri, 0) + 1; self._versions[uri] = version
        if version == 1:
            self._notify('textDocument/didOpen', {'textDocument': {'uri':uri,'languageId':'python','version':version,'text':text}})
        else:
            self._notify('textDocument/didChange', {'textDocument': {'uri':uri,'version':version}, 'contentChanges':[{'text':text}]})
        return uri

    def request(self, method, path, text, line=0, character=0, extra=None, timeout=5):
        uri = self.sync(path, text)
        if not uri: raise RuntimeError(self.note)
        params = {'textDocument': {'uri': uri}}
        if line is not None: params['position'] = {'line': max(0, int(line)), 'character': max(0, int(character))}
        params.update(extra or {})
        return self._request(method, params, timeout)

    def diagnostics(self, path, text, timeout=2.5):
        started = time.time(); uri = self.sync(path, text)
        if not uri: return [], self.note
        while time.time() - started < timeout:
            row = self._diagnostics.get(uri)
            if row and row[0] >= started: return row[1], self.note
            time.sleep(.025)
        return self._diagnostics.get(uri, (0, []))[1], 'Pyright diagnostics timed out; showing the latest result'

    def close(self):
        if self.process:
            try: self._notify('exit', {})
            except Exception: pass
            try: self.process.terminate()
            except Exception: pass
        self.process = None
