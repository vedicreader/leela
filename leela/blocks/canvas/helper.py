"Sutradhara: the one helper in the margin. It answers, it edits the canvas, and it carries the trail."

from __future__ import annotations
import asyncio, re, textwrap
from dataclasses import dataclass, field
from fastcore.all import L, first
from ... import errstr
from .doc import brick_id

#: What one tool may hand back, so a whole namespace cannot fill the turn.
MAX_TOOL_CHARS = 4000

def clip(t, mx=MAX_TOOL_CHARS):
    t = str(t or '')
    return t if len(t) <= mx else t[:mx] + f'\n… {len(t) - mx} more characters'

__all__ = ['TOOLS', 'WRITES', 'Ask', 'Scripted', 'skill_text', 'section', 'defined_in',
           'canvas_tools', 'open_canvas']

#: What the helper may do to a document. The names, and only the names: what each one is for is in
#: the `canvas` skill, which Leela pushes onto the agent when a canvas is open.
TOOLS = ('canvas_read', 'canvas_insert', 'canvas_replace', 'canvas_remove',
         'canvas_bind', 'canvas_run', 'canvas_answer', 'canvas_values')
#: The ones that change the file. `ai.LEELA_WRITES` records `before` for them.
WRITES = ('canvas_insert', 'canvas_replace', 'canvas_remove', 'canvas_bind', 'canvas_answer')

def skill_text():
    "The canvas skill body. One source of truth for the model and for the stand-in."
    from ...skills import skill
    return skill('canvas').text()

def section(term):
    "The part of the skill that covers `term`: by heading first, else where it is talked about most."
    parts = re.split(r'\n## ', skill_text())[1:]
    term = term.lower().rstrip('s')
    hit = first(p for p in parts if term in p.split('\n', 1)[0].lower())
    if hit is None:
        scored = sorted(parts, key=lambda p: -len(re.findall(term, p.lower())))
        hit = first(p for p in scored if term in p.lower())
    return ('## ' + hit).strip() if hit else ''

def defined_in(canvas, term):
    "The sentence in this document that explains `term`. A document explains its own words."
    for b in canvas:
        if b.kind not in ('text', 'note', 'reply'): continue
        prose = ' '.join(l for l in b.body.splitlines() if not l.lstrip().startswith('#'))
        for line in re.split(r'(?<=[.!?])\s+', prose):
            if re.search(rf'\b{re.escape(term)}\w*\b', line, re.I) and len(line.split()) > 6: return line.strip()
    return ''

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

@dataclass
class Ask:
    "One turn's context: what was asked, from where, and what came before it."
    question: str
    canvas: object
    runtime: object
    brick_id: str = ''
    selection: str = ''
    nth: int = 0
    palette: list = field(default_factory=list)
    trail: list = field(default_factory=list)
    mode: str = 'make'
    #: The `Open` this question is against, which carries the trust `apply` refuses on.
    doc: object = None
    def apply(self, op):
        "Every edit a turn makes. An untrusted document runs nothing, whoever asked and however."
        from .ops import apply_op, runs_code
        if self.doc is not None and not self.doc.trusted and runs_code(op):
            return {'ok': False, 'error': 'this document has not been trusted to run; trust it first',
                    'refused': op.get('op', '')}
        return apply_op(self.canvas, self.runtime, op)
    def near(self):
        "The brick the question came from, and the two either side of it."
        i = self.canvas.index(self.brick_id)
        if i is None: return list(self.canvas)[-3:]
        return self.canvas.bricks[max(0, i - 1):i + 2]
    def names(self):
        "The public names the document has computed. The runtime answers, whichever one it is."
        return list(self.runtime.names())

def _kind_of(r):
    "What a resolved name looks like, for a summary the stand-in writes."
    if not r or not r.get('ok'): return 'unresolved'
    v = r.get('value')
    return {list: 'list', dict: 'dict', bool: 'bool', int: 'int', float: 'float',
            str: 'str', type(None): 'None'}.get(type(v), type(v).__name__)

def _words(text): return {w.strip('?.,!:;()`"\'') for w in (text or '').lower().split()}

def _bulletise(text):
    parts = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
    return '\n'.join('- ' + p.rstrip('.') for p in parts) if len(parts) > 1 else '- ' + text.strip()

def _tighten(text):
    out = re.sub(r'\b(really|very|quite|just|actually|basically|simply|in order to)\b ?', '', text, flags=re.I)
    out = re.sub(r'\bin order to\b', 'to', out, flags=re.I)
    return re.sub(r'\s{2,}', ' ', out).strip()

class Scripted:
    "A deterministic stand-in for the model, so the canvas can be driven with no key and no network."
    name = 'scripted'

    async def turn(self, ask, steer=None):
        q = (ask.question or '').strip()
        yield 'step', {'id': 'read', 'label': 'canvas_read', 'detail': f'{len(ask.canvas)} bricks, {len(ask.names())} live names'}
        await asyncio.sleep(.32)
        if steer and not steer.empty():
            extra = await steer.get()
            q = f'{q}. {extra}'
            yield 'step', {'id': 'steer', 'label': 'steering taken', 'detail': extra}
        for event in self._plan(ask, q):
            if steer and not steer.empty():
                extra = await steer.get()
                yield 'step', {'id': 'steer' + brick_id(), 'label': 'steering taken', 'detail': extra}
                for e in self._plan(ask, extra): yield e; await asyncio.sleep(.3)
            yield event
            await asyncio.sleep(.32)

    def _plan(self, ask, q):
        low = q.lower()
        for test, fn in ((self._is_rewrite, self._rewrite), (self._is_help, self._help), (self._is_chart, self._chart),
                         (self._is_embed, self._embed), (self._is_wire, self._wire), (self._is_quiz, self._quiz),
                         (self._is_summary, self._summary), (self._is_note, self._note)):
            if test(low, ask): return list(fn(ask, q, low))
        return list(self._fallback(ask, q))

    # --- intents ---
    def _is_rewrite(self, low, ask): return bool(ask.selection) and any(w in low for w in ('tighten', 'shorten', 'bullet', 'rewrite', 'plainer'))
    def _rewrite(self, ask, q, low):
        text = _bulletise(ask.selection) if 'bullet' in low else _tighten(ask.selection)
        yield 'step', {'id': 'rw', 'label': 'canvas_replace', 'detail': f'{len(ask.selection)} chars in {ask.brick_id}'}
        yield 'op', {'op': 'replace_selection', 'id': ask.brick_id, 'was': ask.selection, 'nth': ask.nth, 'text': text}
        yield 'chunk', {'text': 'Rewritten in place. The original is one undo away.'}

    #: Questions about the canvas itself are answered out of the skill, so there is one text to keep
    #: right rather than two.
    HELP_WORDS = ('canvas', 'brick', 'bind', 'binding', 'emit', 'port', 'component', 'sketch', 'ask', 'data', 'trail')
    def _is_help(self, low, ask):
        return bool(self._help_term(low)) and any(w in low for w in ('what', 'how', 'why', 'help', '?'))
    def _help_term(self, low): return first(w for w in self.HELP_WORDS if w in _words(low))
    def _help(self, ask, q, low):
        term = self._help_term(low) or 'canvas'
        text = section(term) or f'The skill has nothing under `{term}`.'
        yield 'step', {'id': 'h', 'label': 'read_skill', 'detail': f'canvas: {term}'}
        for part in textwrap.wrap(text.split('\n\n')[1] if '\n\n' in text else text, 90): yield 'chunk', {'text': part + ' '}
        yield 'answer', {'markdown': text}

    def _is_chart(self, low, ask): return any(w in low for w in ('chart', 'plot', 'graph it', 'draw it'))
    def _chart(self, ask, q, low):
        got = ask.runtime.snapshot(ask.names())
        names = [n for n, r in got.items() if r.get('ok') and isinstance(r.get('value'), list)]
        target = first(n for n in names if n in low) or first(names) or 'series'
        yield 'step', {'id': 'c', 'label': 'canvas_insert', 'detail': f'viz.series bound to {target}'}
        yield 'op', {'op': 'insert', 'after': ask.brick_id, 'kind': 'brick',
                     'attrs': {'src': 'lego.bricks:viz.series'},
                     'binds': {'series': f'[{{"name": "{target}", "values": {target}}}]',
                               'labels': f'list(range(len({target})))'}}
        yield 'chunk', {'text': f'Charted `{target}`. Change the cell above and the line follows.'}

    def _is_embed(self, low, ask):
        return bool(ask.palette) and any(w in low for w in ('embed', 'show me', 'add the', 'put the', 'insert'))

    #: Which component is scored against what the host publishes, not against a table kept here. A
    #: package that ships a new brick is reachable the day it ships.
    def _pick(self, low, palette):
        words = _words(low) - {'embed', 'the', 'a', 'an', 'add', 'put', 'insert', 'show', 'me', 'this', 'here'}
        def score(b):
            hay = _words(f"{b.get('name','')} {b.get('title','')} {b.get('doc','')} {b.get('group','')}".replace('.', ' '))
            return sum(1 for w in words if any(w in h or h in w for h in hay))
        best = max(palette, key=score, default=None)
        return best if best and score(best) else None

    def _embed(self, ask, q, low):
        b = self._pick(low, ask.palette)
        if b is None:
            yield 'chunk', {'text': f'Nothing in the palette matches that. It has: ' +
                                    ', '.join(x['title'] for x in ask.palette[:8]) + '.'}
            return
        yield 'step', {'id': 'e', 'label': 'canvas_insert', 'detail': b['src']}
        yield 'op', {'op': 'insert', 'after': ask.brick_id, 'kind': 'brick',
                     'attrs': {'src': b['src']}, 'props': {'height': str(b.get('height', 260))}, 'wire': True}
        yield 'chunk', {'text': f"Embedded **{b['title']}** with the snippet `{b['src'].split(':')[0]}` ships. "
                                'Click a port to repoint it.'}

    def _is_wire(self, low, ask): return low.startswith(('connect', 'wire', 'bind'))
    def _wire(self, ask, q, low):
        m = re.search(r'(?:connect|wire|bind)\s+(\S+)\s+(?:to|=)\s+(.+)', q, re.I)
        target = ask.brick_id
        if not m:
            yield 'chunk', {'text': 'Say it as `connect <port> to <expression>`.'}
            return
        yield 'step', {'id': 'w', 'label': 'canvas_bind', 'detail': f'{m[1]} = {m[2]}'}
        yield 'op', {'op': 'bind', 'id': target, 'port': m[1], 'expr': m[2].strip()}
        yield 'chunk', {'text': f'`{m[1]}` now reads `{m[2].strip()}`.'}

    def _is_quiz(self, low, ask): return 'quiz' in low or 'test me' in low
    def _quiz(self, ask, q, low):
        heads = L(ask.canvas.bricks).filter(lambda b: b.kind == 'text' and b.body.startswith('#')).map(lambda b: b.body.splitlines()[0].lstrip('# '))
        items = list(heads)[:4] or ['this document']
        body = '\n'.join(f'{i+1}. {h}?' for i, h in enumerate(items))
        yield 'step', {'id': 'q', 'label': 'canvas_insert', 'detail': f'{len(items)} questions'}
        yield 'op', {'op': 'insert', 'after': ask.brick_id, 'kind': 'quiz', 'body': body}
        yield 'chunk', {'text': 'Four questions from the headings, at the end of the document.'}

    def _is_summary(self, low, ask): return any(w in low for w in ('summar', 'what do i have', 'state of'))
    def _summary(self, ask, q, low):
        seen = ask.names()[:12]
        got = ask.runtime.snapshot(seen)
        rows = [f'- `{n}`, {_kind_of(got.get(n))}' for n in seen]
        body = 'What this document holds right now:\n\n' + ('\n'.join(rows) or '- nothing yet')
        yield 'step', {'id': 's', 'label': 'canvas_values', 'detail': f'{len(rows)} names'}
        yield 'op', {'op': 'insert', 'after': ask.brick_id, 'kind': 'note', 'body': body}
        yield 'chunk', {'text': 'Written as a note under the question.'}

    #: A document explains its own words. The stand-in has no model, so it quotes the document
    #: rather than inventing a fact, and says so when the document is silent.
    def _is_note(self, low, ask): return bool(self._term(low, ask))
    def _term(self, low, ask):
        return first(w for w in _words(low) if len(w) > 3 and defined_in(ask.canvas, w))
    def _note(self, ask, q, low):
        term = self._term(low, ask)
        text = defined_in(ask.canvas, term)
        yield 'step', {'id': 'n', 'label': 'canvas_read', 'detail': f'{term}, from this document'}
        for part in textwrap.wrap(text, 90): yield 'chunk', {'text': part + ' '}
        yield 'answer', {'markdown': text}

    def _fallback(self, ask, q):
        trail = ', '.join(t.get('question', '')[:28] for t in ask.trail[-3:]) or 'nothing yet'
        text = ('No pattern for that one. This is the stand-in, not a model: it answers questions about the '
                'canvas out of the `canvas` skill, explains a word by finding where this document already '
                'explains it, charts a list, embeds a brick, wires a port, quizzes you and summarises the '
                f'namespace. Trail so far: {trail}.')
        yield 'step', {'id': 'f', 'label': 'canvas_read', 'detail': 'no intent matched'}
        for part in textwrap.wrap(text, 90): yield 'chunk', {'text': part + ' '}
