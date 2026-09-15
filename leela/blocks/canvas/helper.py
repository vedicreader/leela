"The canvas as tools: what an agent may do to a document, and which document it means."

from __future__ import annotations
from ... import errstr

#: What one tool may hand back, so a whole namespace cannot fill the turn.
MAX_TOOL_CHARS = 4000

def clip(t, mx=MAX_TOOL_CHARS):
    t = str(t or '')
    return t if len(t) <= mx else t[:mx] + f'\n… {len(t) - mx} more characters'

__all__ = ['TOOLS', 'WRITES', 'canvas_tools', 'open_canvas', 'clip', 'MAX_TOOL_CHARS']

#: What an agent may do to a document. The names only; what each is for is in the `canvas` skill,
#: which Leela pushes while a canvas tab is open.
TOOLS = ('canvas_read', 'canvas_insert', 'canvas_replace', 'canvas_remove',
         'canvas_bind', 'canvas_run', 'canvas_answer', 'canvas_values')
#: The ones that change the file. `ai.LEELA_WRITES` records `before` for them.
WRITES = ('canvas_insert', 'canvas_replace', 'canvas_remove', 'canvas_bind', 'canvas_answer')

def open_canvas(host, path=''):
    "The canvas the active tab is showing, opened. None when that tab is not one."
    from .store import store_for
    ws = getattr(host, 'ws', host)      # the agent holds a `WorkspaceHost`; the tabs are behind it
    if not path:
        t = getattr(ws, 'tab', None)
        if t is None or getattr(t, 'kind', '') != 'canvas': return None
        path = t.path
    if not path: return None
    return store_for(getattr(ws, 'fs', None), pool=getattr(ws, 'pool', None)).get(path)

def canvas_tools(host):
    "The canvas as tools on the workspace agent, each resolving the open document when it runs."
    from .ops import apply_op, runs_code

    def _doc(path=''):
        o = open_canvas(host, path)
        if o is None: raise LookupError('no canvas is open; open a .canvas.md tab first')
        return o

    def _apply(op, path=''):
        o = _doc(path)
        if runs_code(op) and not o.trusted:
            return "this document has not been trusted to run; the person clicks 'run it' first"
        was = o.canvas.md()
        r = apply_op(o.canvas, o.runtime, op)
        if not r.get('ok'): return f"canvas_{op['op']} failed: {r.get('error', 'refused')}"
        o.bump()
        _write(o, was)
        return r

    def _write(o, was):
        "Save through the sandbox. The turn journals it, from the `before` the write hook recorded."
        now = o.canvas.md()
        if now == was: return
        ws = getattr(host, 'ws', host)
        try: ws.fs.write(o.canvas.path, now)
        except Exception: o.canvas.save()           # no sandbox: the spike, and the tests

    def _rows(o):
        return '\n'.join(f"{b.id}  {b.kind:8} {(b.title or b.body).strip().splitlines()[0][:60] if (b.title or b.body).strip() else ''}"
                          for b in o.canvas)

    def canvas_read(path: str = '') -> str:
        """Every brick in the open canvas: its id, its kind and its first line.
        Read this before editing: every other canvas tool addresses a brick by id."""
        try: o = _doc(path)
        except Exception as e: return errstr(e)
        return f'{o.canvas.path}  ({len(o.canvas)} bricks, {"trusted" if o.trusted else "not trusted"})\n' + _rows(o)

    def canvas_insert(kind: str, body: str, after: str = '', path: str = '') -> str:
        """Add a brick. `kind` is one of text, note, code, ask, goal, task, source; `after` is the brick id to put it below.
        Prose goes in as `text` or `note`. Code goes in as `code` and runs only once the person has trusted the document."""
        r = _apply({'op': 'insert', 'kind': kind, 'body': body, 'after': after}, path)
        return r if isinstance(r, str) else f"inserted {r['brick']['id']} ({kind})"

    def canvas_replace(id: str, body: str, path: str = '') -> str:
        """Rewrite one brick's body, leaving its kind, id and attributes alone."""
        r = _apply({'op': 'replace', 'id': id, 'body': body}, path)
        return r if isinstance(r, str) else f'replaced {id}'

    def canvas_remove(id: str, path: str = '') -> str:
        "Delete one brick, and drop whatever its code defined."
        r = _apply({'op': 'remove', 'id': id}, path)
        return r if isinstance(r, str) else f'removed {id}'

    def canvas_bind(id: str, port: str, expr: str, path: str = '') -> str:
        """Point a component's port at an expression, so it redraws when that value moves.
        An empty `expr` unbinds it."""
        r = _apply({'op': 'bind', 'id': id, 'port': port, 'expr': expr}, path)
        return r if isinstance(r, str) else f'{id}.{port} = {expr}'

    def canvas_run(id: str, path: str = '') -> str:
        "Run one code brick, and everything downstream of what it defines."
        r = _apply({'op': 'run', 'id': id}, path)
        if isinstance(r, str): return r
        outs = r.get('run', {}).get('outputs') or []
        return f'ran {id}: ' + (clip('\n'.join(str(o.get('text') or o.get('evalue') or
            (o.get('data') or {}).get('text/plain', '')) for o in outs)) or 'no output')

    def canvas_answer(of: str, markdown: str, path: str = '') -> str:
        """Write the answer to an `ask` brick back into the document, under the question.
        This is how a canvas keeps its reasoning: the reply is a brick in the file, not chat history."""
        r = _apply({'op': 'answer', 'of': of, 'markdown': markdown}, path)
        return r if isinstance(r, str) else f'answered {of}'

    def canvas_values(names: str = '', path: str = '') -> str:
        "What the document has computed. `names` is comma separated; empty means every public name."
        want = [n.strip() for n in str(names).replace(',', ' ').split() if n.strip()]
        r = _apply({'op': 'values', 'names': want or None}, path)
        if isinstance(r, str): return r
        return clip('\n'.join(f"{k} = {v.get('value') if v.get('ok') else v.get('error')}"
                               for k, v in (r.get('values') or {}).items()) or 'nothing computed yet')

    return [canvas_read, canvas_insert, canvas_replace, canvas_remove, canvas_bind, canvas_run,
            canvas_answer, canvas_values]
