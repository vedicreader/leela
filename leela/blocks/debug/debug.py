"A small Debug Adapter Protocol client for direct Python/debugpy sessions."
from __future__ import annotations

import json, queue, subprocess, threading, time
from pathlib import Path

__all__ = ['DebugSession', 'debugpy_available', 'frame_path', 'open_path',
           'paused_kernel', 'notebook_state_ui']

DAP_COMMANDS = {'continue': 'continue', 'next': 'next', 'stepIn': 'stepIn',
                'stepOut': 'stepOut', 'pause': 'pause'}

def debugpy_available(python):
    try:
        return subprocess.run([str(python), '-c', 'import debugpy'], capture_output=True,
                              timeout=5).returncode == 0
    except Exception: return False

def _breakpoint(row):
    "One requested breakpoint in DAP shape; a bare line number is the common case."
    if isinstance(row, int): row = {'line': row}
    item = {'line': max(1, int(row.get('line', 1)))}
    for k in ('condition', 'hitCondition', 'logMessage'):
        if row.get(k): item[k] = str(row[k])
    return item

class DebugSession:
    "One debugpy adapter process and its request/event state."
    def __init__(self, python, cwd=None):
        self.python = str(Path(python).expanduser().absolute())
        self.cwd = str(Path(cwd or Path.cwd()).resolve())
        self.process = None; self.seq = 0; self.pending = {}; self.events = queue.Queue()
        self._lock = threading.Lock(); self.thread_id = None; self.frame_id = None
        self.breakpoints = {}; self.config = {}; self.closed = False
    @property
    def alive(self): return bool(self.process and self.process.poll() is None and not self.closed)
    def start_adapter(self):
        if not debugpy_available(self.python):
            raise RuntimeError(f'debugpy is not installed in {self.python}')
        self.process = subprocess.Popen([self.python, '-m', 'debugpy.adapter'], cwd=self.cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        threading.Thread(target=self._read, daemon=True, name='leela-debugpy-dap').start()
        threading.Thread(target=self._stderr, daemon=True, name='leela-debugpy-stderr').start()
        self.request('initialize', {'clientID': 'leela', 'clientName': 'Leela', 'adapterID': 'python',
            'pathFormat': 'path', 'linesStartAt1': True, 'columnsStartAt1': True,
            'supportsVariableType': True, 'supportsVariablePaging': True,
            'supportsRunInTerminalRequest': False}, timeout=15)
        return self
    def _write(self, message):
        raw = json.dumps(message, separators=(',', ':')).encode()
        with self._lock:
            self.process.stdin.write(f'Content-Length: {len(raw)}\r\n\r\n'.encode()+raw)
            self.process.stdin.flush()
    def send_request(self, command, arguments=None):
        self.seq += 1; seq = self.seq; answer = queue.Queue(1); self.pending[seq] = answer
        self._write({'seq': seq, 'type': 'request', 'command': command, 'arguments': arguments or {}})
        return seq, answer
    def _await_answer(self, seq, answer, timeout, on_timeout, on_failure):
        "The reply to one sent request, raising `on_timeout`/`on_failure` if it never arrives or failed."
        try: message = answer.get(timeout=timeout)
        except queue.Empty:
            self.pending.pop(seq, None)
            raise TimeoutError(on_timeout)
        if not message.get('success', False): raise RuntimeError(message.get('message') or on_failure)
        return message
    def request(self, command, arguments=None, timeout=10):
        seq, answer = self.send_request(command, arguments)
        message = self._await_answer(seq, answer, timeout, f'debugpy did not answer {command}',
                                     f'debugpy rejected {command}')
        return message.get('body') or {}
    def _read(self):
        stream = self.process.stdout
        while self.process and self.process.poll() is None:
            try:
                headers = {}
                while True:
                    line = stream.readline()
                    if not line: return
                    if line in (b'\r\n', b'\n'): break
                    key, _, value = line.decode('ascii', 'replace').partition(':'); headers[key.lower()] = value.strip()
                raw = stream.read(int(headers.get('content-length', '0'))); message = json.loads(raw)
                if message.get('type') == 'response':
                    waiter = self.pending.pop(message.get('request_seq'), None)
                    if waiter: waiter.put(message)
                elif message.get('type') == 'event':
                    if message.get('event') == 'stopped': self.thread_id = (message.get('body') or {}).get('threadId')
                    elif message.get('event') in ('continued', 'terminated', 'exited'): self.thread_id = None
                    self.events.put(message)
                elif message.get('type') == 'request': self._adapter_request(message)
            except Exception as error:
                self.events.put({'type': 'event', 'event': 'error', 'body': {'message': f'DAP reader: {error}'}}); return
    def _stderr(self):
        while self.process and self.process.poll() is None:
            raw = self.process.stderr.readline()
            if not raw: return
            text = raw.decode(errors='replace').rstrip()
            if text: self.events.put({'type': 'event', 'event': 'output',
                'body': {'category': 'stderr', 'output': text+'\n'}})
    def _adapter_request(self, message):
        command = message.get('command')
        response = {'seq': self.seq+1, 'type': 'response', 'request_seq': message.get('seq'),
                    'command': command, 'success': False}
        self.seq += 1
        if command == 'runInTerminal':
            response['message'] = 'Leela direct debugging uses debugpy internalConsole'
        else: response['message'] = f'unsupported adapter request {command}'
        self._write(response)
    def wait_event(self, names, timeout=15):
        names = {names} if isinstance(names, str) else set(names); deadline = time.time()+timeout; skipped = []
        try:
            while time.time() < deadline:
                try: event = self.events.get(timeout=max(.01, deadline-time.time()))
                except queue.Empty: break
                if event.get('event') in names: return event
                skipped.append(event)
        finally:
            for event in skipped: self.events.put(event)
        raise TimeoutError(f'debugpy did not emit {sorted(names)}')
    def launch(self, config, breakpoints=None):
        self.config = dict(config); request = config.get('request', 'launch')
        args = {'name': config.get('name', 'Python'), 'type': 'debugpy', 'request': request,
                'justMyCode': bool(config.get('justMyCode', True)),
                'stopOnEntry': bool(config.get('stopOnEntry', False)),
                'subProcess': bool(config.get('subProcess', True)),
                'cwd': config.get('cwd') or self.cwd, 'env': config.get('env') or {},
                'console': 'internalConsole', 'redirectOutput': True}
        if request == 'attach':
            args['connect'] = {'host': config.get('host', '127.0.0.1'), 'port': int(config.get('port', 5678))}
            if config.get('pathMappings'): args['pathMappings'] = config['pathMappings']
        else:
            if config.get('module'): args['module'] = config['module']
            else: args['program'] = config.get('program')
            args['args'] = list(config.get('args') or [])
            args['python'] = self.python
            for k in ('django', 'jinja', 'gevent'):
                if config.get(k): args[k] = True
        launch_seq, launch_answer = self.send_request(request, args)
        self.wait_event('initialized', 20)
        for path, lines in (breakpoints or {}).items(): self.set_breakpoints(path, lines)
        filters = [f for f, on in (('raised', config.get('breakOnRaised')),
                                   ('uncaught', config.get('breakOnUncaught', True))) if on]
        self.request('setExceptionBreakpoints', {'filters': filters})
        self.request('configurationDone')
        self._await_answer(launch_seq, launch_answer, 30, 'debugpy launch did not complete',
                           'debugpy launch failed')
        return self
    def set_breakpoints(self, path, rows):
        resolved = str(Path(path).resolve())
        body = self.request('setBreakpoints', {'source': {'path': resolved},
            'breakpoints': [_breakpoint(row) for row in rows or []]})
        self.breakpoints[resolved] = rows
        return body.get('breakpoints') or []
    def state(self, thread_id=None, frame_id=None):
        tid = int(thread_id or self.thread_id or 0)
        if not tid: raise RuntimeError('debugger is not paused')
        frames = self.request('stackTrace', {'threadId': tid, 'startFrame': 0, 'levels': 100}).get('stackFrames') or []
        selected = next((frame for frame in frames if frame.get('id') == frame_id), frames[0] if frames else None)
        if not selected: raise RuntimeError('debugger returned no stack frames')
        self.thread_id, self.frame_id = tid, selected['id']
        scopes = self.request('scopes', {'frameId': selected['id']}).get('scopes') or []
        local = next((s for s in scopes if s.get('name', '').lower() == 'locals'), None)
        return {'thread_id': tid, 'frame_id': selected['id'], 'frames': frames, 'scopes': scopes,
                'variables': self.variables(local.get('variablesReference', 0)) if local else [],
                'source': (selected.get('source') or {}).get('path', '')}
    def variables(self, reference, start=0, count=200):
        return self.request('variables', {'variablesReference': int(reference), 'start': int(start),
            'count': int(count)}).get('variables') or []
    def evaluate(self, expression, frame_id=None, context='repl'):
        return self.request('evaluate', {'expression': expression,
            'frameId': int(frame_id or self.frame_id or 0), 'context': context})
    def control(self, command):
        if command not in DAP_COMMANDS: raise ValueError(f'unknown debug command {command}')
        body = self.request(DAP_COMMANDS[command], {'threadId': int(self.thread_id or 0)})
        if command != 'pause': self.thread_id = None
        return body
    def disconnect(self, terminate=True):
        if self.closed: return
        try: self.request('disconnect', {'restart': False, 'terminateDebuggee': bool(terminate)}, timeout=5)
        except Exception: pass
        self.closed = True
        if self.process and self.process.poll() is None:
            try: self.process.terminate()
            except Exception: pass

def frame_path(frame): return (frame.get('source') or {}).get('path') or ''

def open_path(fs, path):
    "The workspace file a debug frame refers to, or '' when it is outside the sandbox."
    try: return str(fs._check(path, must_exist=True))
    except Exception: return ''

def paused_kernel(state, method=None):
    "The kernel holding the paused notebook debugger, when it can serve `method`."
    k = state.kernel
    return k if k is not None and (method is None or hasattr(k, method)) else None

def notebook_state_ui(state, fs, ui):
    "Map temporary cell sources back to the notebook and mark project files safe to open."
    ui.update(origin_path=state.origin_path, cell_id=state.cell_id)
    temp, sources = ui.get('source'), state.cell_sources
    for frame in ui.get('frames', []):
        path = frame_path(frame)
        cell_id = sources.get(path)
        if path == temp or cell_id:
            frame['open_path'] = state.origin_path or ''
            frame['cell_id'] = cell_id or state.cell_id or ''
        else: frame['open_path'] = open_path(fs, path)
    return ui
