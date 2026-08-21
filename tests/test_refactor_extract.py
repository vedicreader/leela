"Extraction of real code: indented selections, values in, results out."

import ast
import pytest
from leela.blocks.refactor.python import extract


def _cut(src, first, after):
    "The offsets the editor sends: the start of `first`, and the newline ending the last line."
    return src.index(first), src.index(after) - 1


FUNC = """def outer():
    total = 0
    for n in range(10):
        total = total + n
    scaled = total * 2
    print(scaled)
"""

METHOD = """class A:
    def run(self, n):
        base = self.seed + n
        out = base * 2
        print(out)

    def other(self): pass
"""


def test_an_indented_selection_extracts_at_all():
    """`ast` will not parse an indented block, and the selection carries its own indentation, so
    every extraction from inside a function or class used to raise a bare IndentationError."""
    start, end = _cut(FUNC, '    total = 0', '    print(scaled)')
    after = extract('x.py', FUNC, start, end, 'function', 'accumulate').after
    ast.parse(after)
    assert 'def accumulate():' in after


def test_what_the_caller_still_needs_comes_back_from_the_function():
    "Refusing every selection that assigns anything refused nearly every real selection."
    start, end = _cut(FUNC, '    total = 0', '    print(scaled)')
    after = extract('x.py', FUNC, start, end, 'function', 'accumulate').after
    ast.parse(after)
    assert 'return scaled' in after, 'the value the rest of the function reads is handed back'
    assert 'scaled = accumulate()' in after, 'and the call receives it'
    assert 'total' not in after.split('def accumulate')[0], 'a value nobody reads after is not returned'


def test_a_value_read_before_it_is_written_arrives_as_a_parameter():
    "`total = total + n` is both a parameter and a result; subtracting the two would lose it."
    src = """def outer(total):
    total = total + 1
    print(total)
"""
    start, end = _cut(src, '    total = total + 1', '    print(total)')
    after = extract('x.py', src, start, end, 'function', 'bump').after
    ast.parse(after)
    assert 'def bump(total):' in after and 'return total' in after
    assert 'total = bump(total)' in after


def test_an_extracted_method_is_a_sibling_of_the_one_it_came_from():
    """Nested inside its own caller, `self.name` is not an attribute of anything, so the call the
    extraction writes would fail at runtime."""
    start, end = _cut(METHOD, '        base =', '        print(out)')
    after = extract('y.py', METHOD, start, end, 'method', 'scale').after
    tree = ast.parse(after)
    assert [n.name for n in tree.body[0].body] == ['run', 'scale', 'other'], 'a sibling, not a nested def'
    assert 'out = self.scale(n)' in after and 'return out' in after
    assert 'self' not in after.split('def scale(self')[1].split(')')[0], 'self is not passed to itself'


def test_a_selection_that_returns_cannot_be_lifted_out():
    src = """def outer():
    x = 1
    return x
"""
    start, end = src.index('    x = 1'), len(src) - 1
    with pytest.raises(ValueError, match='returns or yields'):
        extract('x.py', src, start, end, 'function', 'nope')


def test_a_method_extracted_outside_a_class_is_refused_with_a_reason():
    src = """def plain():
    x = 1
    print(x)
"""
    start, end = _cut(src, '    x = 1', '    print(x)')
    with pytest.raises(ValueError, match="class's own methods"):
        extract('x.py', src, start, end, 'method', 'nope')


def test_half_a_statement_is_refused_rather_than_guessed_at():
    src = """def outer():
    x = compute(
        1, 2)
    print(x)
"""
    with pytest.raises(ValueError):
        extract('x.py', src, src.index('    x = compute('), src.index('        1, 2)') - 1, 'function', 'nope')
