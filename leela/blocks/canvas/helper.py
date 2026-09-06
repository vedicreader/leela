"Sutradhara: the one helper in the margin. It answers, it edits the canvas, and it carries the trail."

from __future__ import annotations
import asyncio, re, textwrap
from dataclasses import dataclass, field
from fastcore.all import L, first, ifnone
from .doc import Brick, brick_id

__all__ = ['TOOLS', 'Ask', 'Helper', 'Scripted', 'Agentic', 'helper_for', 'HELP', 'NOTES']

#: What the helper may do to a document. One list, read by the scripted brain, the ramabana seam,
#: and `docs/canvas.md`. A tool that is not here cannot reach the canvas.
TOOLS = {
    'canvas_read':    'The document as it stands: every brick, its kind, its bindings, what it defines.',
    'canvas_insert':  'Put a new brick at a position. kind, body, attrs, binds.',
    'canvas_replace': 'Rewrite one brick in place, by id.',
    'canvas_remove':  'Take a brick out, by id.',
    'canvas_bind':    'Point one port of one brick at an expression in the namespace.',
    'canvas_run':     'Run a code brick and let the dataflow settle.',
    'canvas_answer':  'Write prose back into the document, attached to the question that asked for it.',
    'canvas_values':  'Read names out of the live namespace, to see what the person is looking at.'}

HELP = {
    'canvas': 'A canvas is one markdown file. Prose is prose; everything else is a fenced brick. '
              'Code bricks share one namespace and run in dependency order, not top to bottom.',
    'brick':  'A brick is an embedded component from a package. It declares ports it draws from and '
              'values it hands back when you click it. `bind port = expression` is the whole wiring model.',
    'bind':   'A binding is an expression evaluated against the canvas namespace. When a name it reads '
              'changes, the binding is resolved again and the brick redraws. That is what makes the document live.',
    'emit':   'Clicking inside a brick sets a name in the namespace. Every cell that reads that name reruns. '
              'A component is an input as much as an output.',
    'trail':  'The trail is where you have asked from, in order. It is the helper context, and it is why '
              'a follow-up question needs no preamble.',
    'ask':    'An ask brick is a question that stays in the document. Its answer is written under it as '
              'ordinary markdown, so the file still reads as a file.'}

NOTES = {
    'tithi':    'A tithi is the twelve degrees the moon gains on the sun. Thirty of them make a lunar month, '
                'and because the two move at their own rates a tithi is not a fixed number of hours.',
    'nakshatra':'The twenty-seven divisions of the ecliptic the moon passes through, each 13°20′. The moon '
                'spends roughly a day in each, so it names the day.',
    'hora':     'The planetary hour: the daylight and the night each cut into twelve, with the lords running '
                'in the Chaldean order. The first hora of the day belongs to the lord of the weekday.',
    'yoga':     'The sum of the solar and lunar longitudes, cut into twenty-seven. It reads as the temper of the day.',
    'karana':   'Half a tithi. Eleven karanas cycle through the month, four of them fixed.',
    'mitochondrion': 'The mitochondrion makes ATP by oxidative phosphorylation. It carries its own circular '
                     'genome and divides on its own schedule, which is why it is thought to have been a bacterium.',
    'nucleus':  'The nucleus holds the chromosomes and does transcription. Translation happens outside it, '
                'which is the reason messenger RNA exists at all.',
    'golgi':    'The Golgi apparatus modifies what the endoplasmic reticulum makes and addresses it. Think of '
                'it as the post room rather than the factory.',
    'tunnelling':'A particle meeting a barrier taller than its energy still has amplitude on the far side, '
                 'falling off as exp(-2κa). Thin barriers leak; thick ones do not. Nothing goes over the top.',
    'wavepacket':'A wavepacket is a sum of plane waves. Its centre moves at the group velocity and its width '
                 'grows, because the components disagree about how fast to travel.',
    'funnel':   'A sales funnel is a chain of conditional probabilities. The stage with the worst conversion '
                'is where the work is, not the stage with the smallest number.',
    'cac':      'Customer acquisition cost is the whole go-to-market spend over the customers it won, not the '
                'marketing line alone. Compare it against gross margin, never revenue.'}

@dataclass
class Ask:
    "One turn's context: what was asked, from where, and what came before it."
    question: str
    canvas: object
    runtime: object
    brick_id: str = ''
    selection: str = ''
    trail: list = field(default_factory=list)
    mode: str = 'make'
    def near(self):
        "The brick the question came from, and the two either side of it."
        i = self.canvas.index(self.brick_id)
        if i is None: return list(self.canvas)[-3:]
        return self.canvas.bricks[max(0, i - 1):i + 2]
    def names(self):
        return sorted(k for k in getattr(self.runtime, 'ns', {}) if not k.startswith('_') and not callable(self.runtime.ns[k]))

class Helper:
    "The contract. `turn` yields `(event, payload)` and may be steered while it runs."
    name = 'helper'
    async def turn(self, ask, steer=None): raise NotImplementedError

def _topic(q, table):
    q = q.lower()
    return first(k for k in table if k in q)

def _bulletise(text):
    parts = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
    return '\n'.join('- ' + p.rstrip('.') for p in parts) if len(parts) > 1 else '- ' + text.strip()

def _tighten(text):
    out = re.sub(r'\b(really|very|quite|just|actually|basically|simply|in order to)\b ?', '', text, flags=re.I)
    out = re.sub(r'\bin order to\b', 'to', out, flags=re.I)
    return re.sub(r'\s{2,}', ' ', out).strip()

class Scripted(Helper):
    """A deterministic stand-in for the model, so the canvas can be driven with no key and no network.

    It reads the same `Ask`, calls the same tools and emits the same events as the real turn. What it
    does not have is judgement: the intents below are patterns, not understanding."""
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
        yield 'op', {'op': 'replace_selection', 'id': ask.brick_id, 'was': ask.selection, 'text': text}
        yield 'chunk', {'text': 'Rewritten in place. The original is one undo away.'}

    def _is_help(self, low, ask): return _topic(low, HELP) and any(w in low for w in ('what', 'how', 'why', 'help', '?'))
    def _help(self, ask, q, low):
        k = _topic(low, HELP)
        yield 'step', {'id': 'h', 'label': 'canvas_answer', 'detail': f'help: {k}'}
        for part in textwrap.wrap(HELP[k], 90): yield 'chunk', {'text': part + ' '}
        yield 'answer', {'markdown': HELP[k]}

    def _is_chart(self, low, ask): return any(w in low for w in ('chart', 'plot', 'graph it', 'draw it'))
    def _chart(self, ask, q, low):
        names = [n for n in ask.names() if isinstance(ask.runtime.ns.get(n), (list, tuple))]
        target = first(n for n in names if n in low) or first(names) or 'series'
        yield 'step', {'id': 'c', 'label': 'canvas_insert', 'detail': f'viz.series bound to {target}'}
        yield 'op', {'op': 'insert', 'after': ask.brick_id, 'kind': 'brick',
                     'attrs': {'src': 'lego.bricks:viz.series'},
                     'binds': {'series': f'[{{"name": "{target}", "values": {target}}}]',
                               'labels': f'list(range(len({target})))'}}
        yield 'chunk', {'text': f'Charted `{target}`. Change the cell above and the line follows.'}

    def _is_embed(self, low, ask): return any(w in low for w in ('embed', 'show me the', 'add the', 'put the', 'insert'))
    def _embed(self, ask, q, low):
        catalog = {'cell': 'learn.cell', 'organelle': 'learn.cell', 'wheel': 'panchanga.wheel', 'rasi': 'panchanga.wheel',
                   'hora': 'panchanga.horas', 'panchang': 'panchanga.day', 'cost': 'thrifty.costs', 'price': 'thrifty.costs',
                   'funnel': 'viz.funnel', 'tile': 'viz.tiles', 'orbit': 'learn.orbit', 'wave': 'learn.wavepacket',
                   'tunnel': 'learn.wavepacket', 'quantum': 'learn.wavepacket'}
        src = catalog.get(_topic(low, catalog) or '', 'viz.tiles')
        yield 'step', {'id': 'e', 'label': 'canvas_insert', 'detail': f'lego.bricks:{src}'}
        yield 'op', {'op': 'insert', 'after': ask.brick_id, 'kind': 'brick', 'attrs': {'src': f'lego.bricks:{src}'}, 'wire': True}
        yield 'chunk', {'text': f'Embedded `{src}` with the snippet its package ships. Click a port to repoint it.'}

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
        ns = ask.runtime.ns
        rows = [f'- `{n}`, {type(ns[n]).__name__}' for n in ask.names()[:12]]
        body = 'What this document holds right now:\n\n' + ('\n'.join(rows) or '- nothing yet')
        yield 'step', {'id': 's', 'label': 'canvas_values', 'detail': f'{len(rows)} names'}
        yield 'op', {'op': 'insert', 'after': ask.brick_id, 'kind': 'note', 'body': body}
        yield 'chunk', {'text': 'Written as a note under the question.'}

    def _is_note(self, low, ask): return bool(_topic(low, NOTES))
    def _note(self, ask, q, low):
        k = _topic(low, NOTES)
        text = NOTES[k]
        yield 'step', {'id': 'n', 'label': 'canvas_answer', 'detail': k}
        for part in textwrap.wrap(text, 90): yield 'chunk', {'text': part + ' '}
        yield 'answer', {'markdown': text}

    def _fallback(self, ask, q):
        trail = ', '.join(t.get('question', '')[:28] for t in ask.trail[-3:]) or 'nothing yet'
        text = (f'No pattern for that one. The stand-in brain answers questions about the canvas itself, '
                f'explains {len(NOTES)} terms, charts a list, embeds a brick, wires a port, quizzes you and '
                f'summarises the namespace. Trail so far: {trail}.')
        yield 'step', {'id': 'f', 'label': 'canvas_read', 'detail': 'no intent matched'}
        for part in textwrap.wrap(text, 90): yield 'chunk', {'text': part + ' '}

class Agentic(Helper):
    """The real turn. `Agent` is ramabana's, and the tools are the same eight `TOOLS` names.

    Not exercised in the spike: it needs a model. It is here so the seam is code rather than a promise."""
    name = 'agentic'
    def __init__(self, agent): self.agent = agent
    def _bind(self, ask):
        from .ops import apply_op
        for nm in TOOLS: self.agent.add_tool(self._tool(nm, ask, apply_op))
        return self.agent
    def _tool(self, nm, ask, apply_op):
        def f(**kw): return apply_op(ask.canvas, ask.runtime, {'op': nm.removeprefix('canvas_'), **kw})
        f.__name__, f.__doc__ = nm, TOOLS[nm]
        return f
    async def turn(self, ask, steer=None):
        agent = self._bind(ask)
        yield 'step', {'id': 'm', 'label': 'model', 'detail': str(getattr(agent, 'model', ''))}
        r = await asyncio.to_thread(agent.ask, ask.question)
        yield 'chunk', {'text': str(r)}

def helper_for(agent=None):
    "The real helper where a model is configured, the stand-in where none is."
    return Agentic(agent) if agent is not None else Scripted()
