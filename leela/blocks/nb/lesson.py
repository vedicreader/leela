import json, re, time
from itertools import zip_longest
from pathlib import Path
from fastcore.xtras import fenced, fenced_blocks
from fastcore.ansi import strip_ansi
from fastcore.basics import first
import abhyasa.tutor
from abhyasa.method import METHODS
from abhyasa.prompts import prompt
from abhyasa.tutor import HINTS
from .nb import Cell, Notebook, src_hash
from .exercise import exercise_cells, exercise_meta

CHARTER_TAIL = ('\nHint ladder:\n' + '\n'.join(f'{i}. {hint}' for i, hint in enumerate(HINTS, 1))
    + '\nAdd demos only with add_demo. Never write the reveal, Leela builds it.'
    + '\nWhen the learner asks for another way, re-explain with a method not yet used from abhyasa.method.METHODS:\n'
    + '\n'.join(f'- {name}: {text}' for name, text in METHODS.items())
    + '\nTo set a coding exercise, call add_exercise with a reference solution; Leela checks it and never stores it. Never show the solution or a hidden test\'s expected value.'
    + '\nTo grade, call check_exercise, then grade_exercise. Give one hint rung at a time; name a package only after confirming it is installed; name the module at rung 3 and the function at rung 4; never write the call.'
    + "\nAfter each learner message add at most one line 'Prompt note: ...' when it would help.")

def lesson_charter(step=None) -> str:
    "The tutor prompt as saved in abhyasa now, then `CHARTER_TAIL`."
    return prompt('tutor') + CHARTER_TAIL

def lesson_notebook(name, exercise=None) -> Notebook:
    code = Cell(source='pass')
    return Notebook([
        Cell(source=f'# {name}\n\nA lesson notebook. Predict the output before running the code. Then write your reasoning in the card.', cell_type='markdown'),
        Cell(source='No demo yet. Ask the tutor to add one.', cell_type='markdown'),
        Cell(cell_type='markdown', extra={'lesson': {'role': 'prediction', 'for': code.id}}),
        code,
        *(exercise_cells(exercise) if exercise is not None else []),
        Cell(source='### Question\n\n### Thinking\n\n<!-- Write the question under Question and your reasoning under Thinking. -->',
             cell_type='markdown', extra={'lesson': {'role': 'card', 'for': code.id}}),
    ], meta={'lesson': {'v': 1, 'name': name}})

def parse_card(text):
    text = re.sub(r'<!--[\s\S]*?-->', '', text)
    blocks = fenced_blocks(text) + fenced_blocks(text, ch='~')
    heads = [m for m in re.finditer(r'^###[ \t]+([^\n\r]+)[ \t]*\r?$', text, re.M)
             if not any(start <= m.start() < end for _, _, start, end in blocks)]
    parts = {m[1].strip().lower(): text[m.end():heads[i+1].start() if i+1 < len(heads) else len(text)].strip()
             for i, m in enumerate(heads)}
    return {key: parts.get(key, '') for key in ('question', 'thinking')}

def same_lines(guess, actual):
    g, a = ([' '.join(line.split()) for line in text.splitlines() if line.strip()] for text in (guess, actual))
    return [dict(guess=x, actual=y, kind='missing' if x is None else 'extra' if y is None else 'match' if x == y else 'mismatch')
            for x, y in zip_longest(g, a)]

def lock(cell, prediction, confidence=None):
    if confidence is not None and (type(confidence) is not int or confidence not in (10, 30, 50, 70, 90)):
        raise ValueError('Confidence must be 10, 30, 50, 70, 90 or None.')
    if prediction.strip(): cell.extra['lesson'] = dict(prediction=prediction, for_count=cell.execution_count, confidence=confidence)
    else: cell.extra.pop('lesson', None)

def lesson_actual(cell):
    text = lambda x: ''.join(x) if isinstance(x, list) else str(x or '')
    if (error := first(o for o in cell.outputs if o.get('output_type') == 'error')):
        last = strip_ansi('\n'.join(error.get('traceback') or [])).strip().split('\n')[-1]
        return 'It raised ' + (last or f'{error.get("ename", "")}: {error.get("evalue", "")}')
    return strip_ansi('\n'.join(t for o in cell.outputs if (t := text(o.get('text') if o.get('output_type') == 'stream' else o.get('data', {}).get('text/plain')))))

def lesson_feedback(cell):
    lesson = cell.extra['lesson']
    rows = same_lines(lesson['prediction'], lesson_actual(cell))
    different = [r for r in rows if r['kind'] != 'match']
    if not different: return 'Right. You saw that before running it.'
    lines = [r['actual'] for r in rows if r['kind'] == 'match']
    for r in different:
        lines.append(f'It printed {r["actual"]}, which you did not expect.' if r['kind'] == 'missing' else
                     f'You expected {r["guess"]}, which did not appear.' if r['kind'] == 'extra' else
                     f'You wrote {r["guess"]}. It printed {r["actual"]}.')
    if (lesson.get('confidence') or 0) >= 60: lines.append('You were sure, and it went another way. That is the part worth a look.')
    return '\n'.join(lines)

def record_card(memory, nb, cell, path):
    from abhyasa.store import Learning, slugify
    from abhyasa.model import update
    from litesearch.core import write_txn
    from ..memory.memory import _open_lock
    vault = memory._store('learning')
    with _open_lock(memory.path):
        lr = Learning(vault)
        lesson, name = cell.extra['lesson'], nb.meta['lesson']['name']
        slug, key = slugify(name), f'{cell.id}:{cell.execution_count}'
        with write_txn(lr.v.db):
            attempt = first(a for a in lr.attempts(slug, limit=10000) if a.get('card_key') == key)
            c = lr.concept(slug)
            if attempt is not None and c is None:
                u = update(lr.put(name, slug=slug), 1, attempt.correct, confidence=attempt.confidence)
                u.pop('kind')
                c = lr.update(slug, **u)
            if attempt is None:
                if c is None: c = lr.put(name, slug=slug)
                card = first(c for c in nb.cells if c.extra.get('lesson', {}).get('role') == 'card' and c.extra['lesson'].get('for') == cell.id)
                card = parse_card(card.source if card else '')
                actual, guess, confidence = lesson_actual(cell), lesson['prediction'], lesson.get('confidence')
                correct = all(r['kind'] == 'match' for r in same_lines(guess, actual))
                u = update(c, 1, correct, confidence=confidence)
                u.pop('kind')
                c = lr.update(slug, **u)
                attempt = lr.record(concept=slug, question=card['question'] or next(iter(cell.source.splitlines()), ''),
                    answer=guess, thinking=card['thinking'], correct=correct, confidence=confidence, depth=1, kind='predict',
                    feedback=lesson_feedback(cell), actual=actual, notebook=path, card_key=key)
            return _saved(c)

def _saved(c):
    from abhyasa.model import DEPTHS
    level = f'Your level: {DEPTHS[c.floor]}.' if c.floor else 'Not at a level yet.'
    days = (c.due - time.time())/86400
    when = 'due now' if days <= 0 else f'in {days*24:.0f} h' if days < 1 else f'in {days:.0f} d'
    return f'Saved to your learning shelf. {level} Next review {when}.'

def exercise_filing(nb, cell, path):
    "What `record_exercise` files, copied now so a later edit cannot change it."
    task = first(c for c in nb.cells if c.extra.get('exercise', {}).get('role') == 'task' and c.extra['exercise'].get('for') == cell.id)
    name = nb.meta.get('lesson', {}).get('name') or Path(path).stem
    return dict(name=name, question=task.source.split('\n\n')[0] if task else name, answer=cell.source, path=str(path),
                key=f'{cell.id}:{src_hash(cell.source)}', **exercise_meta(cell)['state']['grade'])

def record_exercise(memory, f):
    "File a graded full pass as one `code` attempt at depth 4 per source version; a new grade of the same source replaces the note."
    from abhyasa.store import Learning, slugify
    from abhyasa.model import update
    from litesearch.core import write_txn
    from ..memory.memory import _open_lock
    slug = slugify(f['name'])
    vault = memory._store('learning')
    with _open_lock(memory.path):
        lr = Learning(vault)
        with write_txn(lr.v.db):
            attempt = first(a for a in lr.attempts(slug, limit=10000) if a.get('card_key') == f['key'])
            c = lr.concept(slug) or lr.put(f['name'], slug=slug)
            if attempt is None or not c.seen:
                u = update(c, 4, True)
                u.pop('kind')
                c = lr.update(slug, **u)
            if attempt is None:
                lr.record(concept=slug, question=f['question'], answer=f['answer'], correct=True, depth=4, kind='code',
                          grade=f['score'], feedback=f['note'], notebook=f['path'], card_key=f['key'])
            else: lr.mark_attempt(attempt.id, grade=f['score'], feedback=f['note'])
            return _saved(c)

def _gates(bs):
    for b in bs if isinstance(bs, list) else []:
        if not isinstance(b, dict): continue
        if b.get('type') == 'gate': yield b
        yield from _gates(b.get('blocks'))

def demo_gate(cell, demo, gate):
    "`(spec, block)` of gate `gate` in demo `demo` among the `rupaka` fences of markdown `cell`; ValueError when there is none or more than one."
    src = cell.source if cell.cell_type == 'markdown' else ''
    specs = []
    for info, body, *_ in fenced_blocks(src) + fenced_blocks(src, ch='~'):
        if info != 'rupaka': continue
        try: s = json.loads(body)
        except ValueError: continue
        if isinstance(s, dict): specs.append(s)
    hits = [(s, g) for s in specs if (s.get('id') or '') == (demo or '') for g in _gates(s.get('blocks')) if g.get('id') == gate]
    if not hits: raise ValueError(f'This cell has no gate {gate!r}.')
    if len(hits) > 1: raise ValueError(f'This cell has more than one gate {gate!r}. Give each gate its own id.')
    return hits[0]

def _js(v):
    "`String(v)` as the rupaka runtime makes it, for a JSON scalar."
    if isinstance(v, bool): return str(v).lower()
    if v is None: return 'null'
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)

def prediction_filing(nb, cell, path, demo, gate, picked, why='', ans=None, ok=None):
    "What `record_prediction` files for one gate, copied now; ValueError for a bad gate, or for a state-path gate without a valid `ans` and `ok`."
    spec, g = demo_gate(cell, demo, gate)
    if not spec.get('id'): raise ValueError('This demo has no id. Give it one, then try.')
    if isinstance(a := g.get('answer'), dict): ans, ok = a.get('is'), _js(picked) == _js(a.get('is'))
    elif type(ok) is not bool: raise ValueError('This check needs ok as true or false.')
    elif ans is not None and not isinstance(ans, (str, int, float)): raise ValueError('This check needs ans as one value: a string, a number, true, false or null.')
    return dict(name=nb.meta['lesson']['name'], spec=spec, gate=gate, picked=_js(picked), ans=_js(ans), ok=ok, why=str(why or ''),
                notebook=str(path or ''), card_key=f'{cell.id}:{src_hash(cell.source)}:{spec["id"]}:{gate}')

def record_prediction(memory, f):
    "File one rupaka prediction through abhyasa once per source version; None when its key is already filed."
    from abhyasa.store import Learning, slugify
    import abhyasa.demo  # adds Learning.put_demo and Learning.record_prediction
    from litesearch.core import write_txn
    from ..memory.memory import _open_lock
    slug = slugify(f['name'])
    vault = memory._store('learning')
    with _open_lock(memory.path):
        lr = Learning(vault)
        with write_txn(lr.v.db):
            if any(x.get('card_key') == f['card_key'] for x in lr.attempts(slug, limit=10000)): return None
            if lr.concept(slug) is None: lr.put(f['name'], slug=slug)
            d = lr.put_demo(f['spec'], slug, by='leela:lesson')
            lr.record_prediction(d.slug, f['gate'], f['picked'], f['ans'], f['ok'], f['why'], notebook=f['notebook'], card_key=f['card_key'])
            return _saved(lr.concept(slug))

def fence(spec): return fenced(json.dumps(spec, ensure_ascii=False), 'rupaka')
def demo_refusal(errors): return '\n'.join(errors)
