"Sutradhara: the one helper in the margin. It answers, it edits the canvas, and it carries the trail."

from __future__ import annotations
import asyncio, re, textwrap
from dataclasses import dataclass, field
from fastcore.all import L, first
from .doc import brick_id

__all__ = ['TOOLS', 'Ask', 'Helper', 'Scripted', 'Agentic', 'helper_for', 'skill_text', 'section', 'defined_in']

#: What the helper may do to a document. The names, and only the names: what each one is for is in
#: the `canvas` skill, which Leela pushes onto the agent when a canvas is open.
TOOLS = ('canvas_read', 'canvas_insert', 'canvas_replace', 'canvas_remove',
         'canvas_bind', 'canvas_run', 'canvas_answer', 'canvas_values')

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

class Helper:
    "The contract. `turn` yields `(event, payload)` and may be steered while it runs."
    name = 'helper'
    async def turn(self, ask, steer=None): raise NotImplementedError

def _words(text): return {w.strip('?.,!:;()`"\'') for w in (text or '').lower().split()}

def _bulletise(text):
    parts = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
    return '\n'.join('- ' + p.rstrip('.') for p in parts) if len(parts) > 1 else '- ' + text.strip()

def _tighten(text):
    out = re.sub(r'\b(really|very|quite|just|actually|basically|simply|in order to)\b ?', '', text, flags=re.I)
    out = re.sub(r'\bin order to\b', 'to', out, flags=re.I)
    return re.sub(r'\s{2,}', ' ', out).strip()

class Scripted(Helper):
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

class Agentic(Helper):
    "The real turn. `Agent` is ramabana's, and canvas mode is what it knows about a canvas."
    name = 'agentic'
    #: The registry as it was before `open`, so `close` restores it rather than approximating it.
    _before = None

    def __init__(self, agent): self.agent = agent

    def open(self, ask):
        "Turn canvas mode on for this agent: the skill, then the tools that make it true."
        from ...skills import push
        self._before = list(self.agent.registry.tools)
        push(self.agent, 'canvas')
        for nm in TOOLS: self.agent.registry.tool(self._tool(nm, ask))
        return self.agent

    def close(self):
        "Turn it off. A canvas the person has closed is not a document the agent may still edit."
        from ...skills import drop
        drop(self.agent, 'canvas')
        if self._before is None:
            self.agent.registry.tools[:] = [t for t in self.agent.registry.tools if t.__name__ not in TOOLS]
        else: self.agent.registry.tools[:] = self._before
        self._before = None
        self.agent._forget()

    def _tool(self, nm, ask):
        from .ops import apply_op
        def f(**kw): return apply_op(ask.canvas, ask.runtime, {'op': nm.removeprefix('canvas_'), **kw})
        f.__name__ = nm
        f.__doc__ = f'{nm}. See `read_skill("canvas")` for what a canvas is and how to work in one.'
        return f

    async def turn(self, ask, steer=None):
        "Canvas mode comes off however the turn ends. A raised ask used to leave the tools registered."
        self.open(ask)
        try:
            yield 'step', {'id': 'm', 'label': 'canvas mode', 'detail': f'{len(TOOLS)} tools, skill pushed'}
            yield 'step', {'id': 'k', 'label': 'model', 'detail': str(getattr(self.agent, 'model', ''))}
            r = await asyncio.to_thread(self.agent.ask, self._prompt(ask))
            yield 'chunk', {'text': str(r)}
        finally: self.close()

    def _prompt(self, ask):
        "The question, with where it was asked from. The skill says what to do with that."
        bits = [ask.question]
        if ask.brick_id: bits.append(f'\n\nasked from brick `{ask.brick_id}`')
        if ask.selection: bits.append(f', with this selected:\n\n> {ask.selection}')
        if ask.trail: bits.append('\n\ntrail: ' + '; '.join(t['question'][:60] for t in ask.trail[-4:]))
        return ''.join(bits)

def helper_for(agent=None):
    "The real helper where a model is configured, the stand-in where none is."
    return Agentic(agent) if agent is not None else Scripted()
