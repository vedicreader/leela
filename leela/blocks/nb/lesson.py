import json, re
from itertools import zip_longest
from fastcore.xtras import fenced, fenced_blocks
from abhyasa.method import METHODS
from abhyasa.tutor import HINTS, TUTOR_SP
from .nb import Cell, Notebook

LESSON_CHARTER = (TUTOR_SP + '\nHint ladder:\n' + '\n'.join(f'{i}. {hint}' for i, hint in enumerate(HINTS, 1))
    + '\nAdd demos only with add_demo. Never write the reveal, Leela builds it.'
    + '\nWhen the learner asks for another way, re-explain with a method not yet used from abhyasa.method.METHODS:\n'
    + '\n'.join(f'- {name}: {text}' for name, text in METHODS.items()))

def lesson_notebook(name) -> Notebook:
    code = Cell(source='pass')
    return Notebook([
        Cell(source=f'# {name}\n\nA lesson notebook. Predict the output before running the code. Then write your reasoning in the card.', cell_type='markdown'),
        Cell(source='No demo yet. Ask the tutor to add one.', cell_type='markdown'),
        Cell(cell_type='markdown', extra={'lesson': {'role': 'prediction', 'for': code.id}}),
        code,
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

def fence(spec): return fenced(json.dumps(spec, ensure_ascii=False), 'rupaka')
def demo_refusal(errors): return '\n'.join(errors)
