"Languages Leela runs without a Jupyter kernel: a cargo scratch crate, and one node process."
from __future__ import annotations
import asyncio, hashlib, json, os, re, shutil
from pathlib import Path
from fastcore.xdg import xdg_data_home

from .kernels import ExecOutcome, InspectorClient, KernelStartError

__all__ = ['Runner', 'CargoRunner', 'NodeRunner', 'RUNNERS', 'runner_for', 'scratch_root',
           'rust_chunks', 'rust_source']

DRIVER = Path(__file__).parent/'driver.mjs'

def scratch_root(lang, key=''):
    "Where a notebook's scratch project lives. One per notebook, kept between sessions."
    d = xdg_data_home()/'leela'/'scratch'/lang/hashlib.sha256(str(key).encode()).hexdigest()[:16]
    d.mkdir(parents=True, exist_ok=True)
    return d

def _stream(name, text): return {'output_type': 'stream', 'name': name, 'text': text}
def _error(ename, evalue, tb=()): return {'output_type': 'error', 'ename': str(ename),
    'evalue': str(evalue), 'traceback': [str(t) for t in tb]}
def _result(text, count): return {'output_type': 'execute_result', 'execution_count': count,
    'metadata': {}, 'data': {'text/plain': str(text)}}

class Runner(InspectorClient):
    "The `Kernel` surface for a language with no kernel: the same execute, no namespace to inspect."
    lang, tool, inspect, base, boot_error, evicted = '', '', False, None, None, None
    wants_key = True   # no connection file to be found by, so `KernelPool` hands it its key
    def __init__(self, cwd=None, name=None, key='', python=None, **kw):
        self.cwd = str(cwd) if cwd else os.getcwd()
        self.name = name or self.lang
        self.key = str(key or self.cwd)
        self.kernel, self.python, self.exe = self.tool, None, None
        self.last_api_error, self.count = '', 0
        self._exec_task, self._exec_lock = None, asyncio.Lock()
        self.dir = scratch_root(self.lang, self.key)
    @property
    def alive(self): return self.exe is not None
    @property
    def pid(self): return None
    @property
    def missing(self):
        return (f'{self.tool} is not installed, so Leela cannot run {self.lang} cells. '
                f'Install it and restart this runtime.')
    def _which(self):
        "The tool this runner drives. PATH first, then the directories a desktop app is launched without."
        from ... import TOOL_DIRS
        if (p := shutil.which(self.tool)): return p
        for d in TOOL_DIRS:
            p = Path(d).expanduser()/self.tool
            if p.is_file() and os.access(p, os.X_OK): return str(p)
        return None
    async def start(self, timeout=60):
        if not (exe := self._which()): raise KernelStartError(self.missing)
        self.exe = exe
        await self.setup()
        return self
    async def setup(self): pass
    async def chdir(self, path):
        self.cwd = str(path)
        return True
    async def bootstrap(self): return None
    async def interrupt(self): return None
    async def restart(self):
        await self.shutdown()
        self.exe = self._which()
        await self.setup()
    async def shutdown(self): self.exe = None
    async def complete(self, code, pos): return {'from': pos, 'matches': []}
    async def inspect_obj(self, code, pos, detail=0): return ''
    async def execute(self, code, silent=False, store_history=True, on_output=None, timeout=None,
        on_debug=None):
        "Run one cell, streaming nbformat outputs to `on_output` as the language produces them."
        if not self.alive: return ExecOutcome(ok=False, error=self.missing)
        async with self._exec_lock:
            task = asyncio.current_task()
            self._exec_task = task
            self.touch()
            outs = []
            def emit(o):
                outs.append(o)
                if on_output: on_output(dict(o))
            try: err = await self.run(code, emit, timeout)
            except asyncio.CancelledError: raise
            except Exception as e:
                err = f'{type(e).__name__}: {e}'
                emit(_error(type(e).__name__, e))
            finally:
                self.touch()
                if self._exec_task is task: self._exec_task = None
        self.count += 1
        return ExecOutcome(ok=err is None, execution_count=self.count, outputs=outs, error=err)
    async def run(self, code, emit, timeout=None): raise NotImplementedError

CARGO_TOML = '''[package]
name = "leela_cell"
version = "0.0.0"
edition = "2021"

[[bin]]
name = "leela_cell"
path = "src/main.rs"

[profile.dev]
debug = 0

[dependencies]
'''

#: What makes a top-level chunk an item rather than a statement. Items outlive the cell that
#: defined them; statements are the body of one `fn main`.
ITEM = re.compile(r'^(?:pub\s+|unsafe\s+|async\s+|extern\s+(?:"[^"]*"\s+)?|default\s+)*'
                  r'(?:fn|struct|enum|impl|trait|mod|use|const|static|type|union)\b|^macro_rules!')

DEP = re.compile(r'^\s*(?://[!/]\s*dep:|:dep\s)\s*(.+?)\s*$')

def rust_chunks(src):
    "Top-level chunks of Rust source, split where a statement or an item ends."
    out, buf, depth, i, n = [], [], 0, 0, len(src)
    def flush():
        if (t := ''.join(buf).strip()): out.append(t)
        buf.clear()
    while i < n:
        c = src[i]
        if c == '/' and i + 1 < n and src[i+1] == '/':
            j = src.find('\n', i)
            j = n if j < 0 else j
            buf.append(src[i:j]); i = j; continue
        if c == '/' and i + 1 < n and src[i+1] == '*':
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            buf.append(src[i:j]); i = j; continue
        if c in '"\'':
            j, esc = i + 1, False
            while j < n and (esc or src[j] != c):
                esc = (src[j] == '\\') and not esc
                j += 1
            buf.append(src[i:j+1]); i = j + 1; continue
        buf.append(c)
        if c in '{([': depth += 1
        elif c in '})]': depth = max(0, depth - 1)
        elif c == ';' and depth == 0: flush()
        elif c == '\n' and depth == 0 and ''.join(buf).strip().endswith('}'): flush()
        i += 1
    flush()
    return out

def _is_item(chunk):
    "An item, once its attributes and doc comments are stripped off the front."
    for line in chunk.splitlines():
        s = line.strip()
        if not s or s.startswith('#[') or s.startswith('#![') or s.startswith('//'): continue
        return bool(ITEM.match(s))
    return False

def rust_source(items, stmts):
    "The `main.rs` for a cell: everything defined so far, then this cell's statements in `main`."
    body = '\n    '.join(stmts) if stmts else ''
    return ('#![allow(dead_code, unused_imports)]\n\n' + '\n\n'.join(items)
            + f'\n\nfn main() {{\n    {body}\n}}\n')

class CargoRunner(Runner):
    "Rust cells as one scratch crate that grows."
    lang, tool = 'rust', 'cargo'
    TRAILING = re.compile(r'^(?:let|return|break|continue|use|fn|struct|enum|impl|trait|mod|'
                          r'const|static|type|for|while|loop|if|match|unsafe|pub)\b')
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.items, self.deps = [], {}
    @property
    def missing(self):
        return ('cargo is not installed, so Leela cannot run Rust cells. Install Rust from '
                'https://rustup.rs and restart this runtime.')
    async def setup(self):
        (self.dir/'src').mkdir(parents=True, exist_ok=True)
        self._write_toml()
    def _write_toml(self):
        deps = ''.join(f'{k} = {v}\n' for k, v in sorted(self.deps.items()))
        (self.dir/'Cargo.toml').write_text(CARGO_TOML + deps, encoding='utf-8')
    def _split(self, code):
        "This cell as `(dependency lines, items, statements)`."
        deps, body = {}, []
        for line in code.splitlines():
            if (m := DEP.match(line)) and '=' in m.group(1):
                k, _, v = m.group(1).partition('=')
                deps[k.strip()] = v.strip()
            else: body.append(line)
        chunks = rust_chunks('\n'.join(body))
        items = [c for c in chunks if _is_item(c)]
        stmts = [c for c in chunks if not _is_item(c)]
        if stmts and not stmts[-1].rstrip().endswith((';', '}')) and not self.TRAILING.match(stmts[-1]):
            stmts[-1] = f'println!("{{:?}}", {stmts[-1].rstrip()});'
        else: stmts = [s if s.rstrip().endswith((';', '}')) else s + ';' for s in stmts]
        return deps, items, stmts
    async def run(self, code, emit, timeout=None):
        deps, items, stmts = self._split(code)
        if deps:
            self.deps.update(deps)
            self._write_toml()
        (self.dir/'src'/'main.rs').write_text(rust_source(self.items + items, stmts), encoding='utf-8')
        failed = await self._build(emit)
        if failed: return failed
        self.items += items                     # only a crate that compiled is worth keeping
        return await self._exec(emit, timeout)
    async def _build(self, emit):
        "Compile, turning every diagnostic into an output. Returns the error summary, or None."
        out = await self._capture([self.exe, 'build', '--message-format=json'])
        first_error = None
        for line in out.splitlines():
            if not line.startswith('{'): continue
            try: row = json.loads(line)
            except ValueError: continue
            if row.get('reason') != 'compiler-message': continue
            m = row.get('message') or {}
            rendered = (m.get('rendered') or m.get('message') or '').rstrip()
            level, code = m.get('level'), (m.get('code') or {}).get('code') or ''
            if level in ('error', 'error: internal compiler error'):
                emit(_error(code or 'error', m.get('message', ''), rendered.splitlines()))
                first_error = first_error or f"{code or 'error'}: {m.get('message', '')}"
            elif level == 'warning' and rendered: emit(_stream('stderr', rendered + '\n'))
        if first_error is None and not (self.dir/'target'/'debug'/'leela_cell').exists():
            emit(_error('cargo', 'the build produced no binary', out.splitlines()[-40:]))
            return 'cargo: the build produced no binary'
        return first_error
    async def _capture(self, argv):
        p = await asyncio.create_subprocess_exec(*argv, cwd=str(self.dir), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await p.communicate()
        return out.decode('utf-8', 'replace')
    async def _exec(self, emit, timeout=None):
        "Run the compiled cell, streaming its output. A non-zero exit is the cell's error."
        p = await asyncio.create_subprocess_exec(str(self.dir/'target'/'debug'/'leela_cell'),
            cwd=self.cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        async def pump(reader, name):
            while (chunk := await reader.read(4096)): emit(_stream(name, chunk.decode('utf-8', 'replace')))
        try: await asyncio.wait_for(asyncio.gather(pump(p.stdout, 'stdout'), pump(p.stderr, 'stderr')), timeout)
        except asyncio.TimeoutError:
            p.kill()
            return 'TimeoutError: the cell did not finish'
        rc = await p.wait()
        if rc: return f'ProcessExit: the program exited with status {rc}'
        return None
    async def restart(self):
        "Forget every definition. The crate is rebuilt from the next cell that defines something."
        self.items, self.deps = [], {}
        await super().restart()

class NodeRunner(Runner):
    "JavaScript cells against one long-lived node process."
    lang, tool = 'javascript', 'node'
    @property
    def missing(self):
        return ('node is not installed, so Leela cannot run JavaScript cells. Install Node.js and '
                'restart this runtime.')
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.proc, self._seq, self._lines = None, 0, None
    @property
    def alive(self): return self.exe is not None and self.proc is not None and self.proc.returncode is None
    @property
    def pid(self): return getattr(self.proc, 'pid', None)
    async def setup(self):
        if not (self.dir/'package.json').exists():
            (self.dir/'package.json').write_text('{"type":"module","name":"leela-cell"}\n', encoding='utf-8')
        self.proc = await asyncio.create_subprocess_exec(
            self.exe, '--no-warnings', str(DRIVER), str(self.dir), cwd=self.cwd,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=8 * 1024 * 1024)
        row = await asyncio.wait_for(self._read(), 20)
        if (row or {}).get('t') != 'ready': raise KernelStartError('the node runtime did not start')
    async def _read(self):
        line = await self.proc.stdout.readline()
        if not line: return None
        try: return json.loads(line)
        except ValueError: return {}
    async def run(self, code, emit, timeout=None):
        if not self.alive: await self.setup()
        self._seq += 1
        ident = self._seq
        self.proc.stdin.write((json.dumps({'id': ident, 'code': code}) + '\n').encode())
        await self.proc.stdin.drain()
        while True:
            try: row = await asyncio.wait_for(self._read(), timeout)
            except asyncio.TimeoutError:
                await self.restart()
                return 'TimeoutError: the cell did not finish, and the runtime was restarted'
            if row is None:
                self.proc = None
                return 'RuntimeError: the node runtime exited'
            if row.get('id') != ident: continue
            if row.get('t') == 'stream': emit(_stream(row.get('name', 'stdout'), row.get('text', '')))
            elif row.get('t') == 'done':
                if row.get('ok'):
                    if (r := row.get('repr')) is not None: emit(_result(r, self.count + 1))
                    return None
                emit(_error(row.get('ename', 'Error'), row.get('evalue', ''), row.get('stack') or []))
                return f"{row.get('ename', 'Error')}: {row.get('evalue', '')}"
    async def interrupt(self):
        "node cannot be asked to stop a synchronous cell, so the process goes and the context with it."
        if self.proc is not None and self.proc.returncode is None: self.proc.kill()
    async def shutdown(self):
        if self.proc is not None and self.proc.returncode is None:
            self.proc.kill()
            try: await asyncio.wait_for(self.proc.wait(), 5)
            except asyncio.TimeoutError: pass
        self.proc, self.exe = None, None

RUNNERS = {r.lang: r for r in (CargoRunner, NodeRunner)}

def runner_for(lang):
    "The runner class for a language, or None when Leela has none."
    from ...core.langs import lang_named
    l = lang_named(lang)
    return RUNNERS.get(l.id) if l and l.runner else None
