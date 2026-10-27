import json, re, time
from itertools import zip_longest
from fastcore.xtras import fenced, fenced_blocks
from fastcore.ansi import strip_ansi
from fastcore.basics import first
from abhyasa.method import METHODS
from abhyasa.tutor import HINTS, TUTOR_SP
from .nb import Cell, Notebook
from .exercise import exercise_cells

LESSON_CHARTER = (TUTOR_SP + '\nHint ladder:\n' + '\n'.join(f'{i}. {hint}' for i, hint in enumerate(HINTS, 1))
    + '\nAdd demos only with add_demo. Never write the reveal, Leela builds it.'
    + '\nWhen the learner asks for another way, re-explain with a method not yet used from abhyasa.method.METHODS:\n'
    + '\n'.join(f'- {name}: {text}' for name, text in METHODS.items())
    + '\nTo set a coding exercise, call add_exercise with a reference solution; Leela checks it and never stores it. Never show the solution or a hidden test\'s expected value.')

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
    from abhyasa.model import DEPTHS, update
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
            level = f'Your level: {DEPTHS[c.floor]}.' if c.floor else 'Not at a level yet.'
            days = (c.due - time.time())/86400
            when = 'due now' if days <= 0 else f'in {days*24:.0f} h' if days < 1 else f'in {days:.0f} d'
            return f'Saved to your learning shelf. {level} Next review {when}.'

def fence(spec): return fenced(json.dumps(spec, ensure_ascii=False), 'rupaka')
def demo_refusal(errors): return '\n'.join(errors)
