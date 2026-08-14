import pytest
from leela.blocks.refactor.python import extract


def test_extract_variable():
    src = 'total = price * qty\n'
    row = extract('a.py', src, 8, 19, 'variable', 'amount')
    assert row.after == 'amount = price * qty\ntotal = amount\n'


def test_extract_constant_rejects_non_literal():
    with pytest.raises(ValueError, match='literal'):
        extract('a.py', 'x = value\n', 4, 9, 'constant', 'default')


def test_extract_function_rejects_a_selection_starting_mid_line():
    "A partial line spliced a `def` into the middle of a statement: `y = cdef f(ompute, x):`."
    src = 'x = 1\ny = compute(x)\n'
    with pytest.raises(ValueError, match='complete statement lines'):
        extract('a.py', src, src.index('compute'), src.index(')') + 1, 'function', 'f')


def test_extract_function_does_not_pass_builtins_as_parameters():
    "`dir(__builtins__)` is `dir(dict)` in an imported module, which listed no builtin names."
    src = 'value = 1\nprint(len(value))\n'
    row = extract('a.py', src, src.index('print'), len(src), 'function', 'show')
    assert row.after == 'value = 1\ndef show(value):\n    print(len(value))\n\nshow(value)\n'
