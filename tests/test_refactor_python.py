import pytest
from leela.blocks.refactor.python import extract, inline


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


def test_inline_undoes_extract_variable():
    """The two are inverses, up to the brackets inline adds to keep the value from reassociating.

    Those brackets are not noise it could drop: at the point of substitution the value is one
    node in a larger expression, and only the parent decides whether they matter.
    """
    src = 'total = price * qty\n'
    out = extract('a.py', src, 8, 19, 'variable', 'amount').after
    assert inline('a.py', out, out.index('amount')).after == 'total = (price * qty)\n'


def test_inline_rewrites_every_use_and_counts_them():
    src = 'amount = price * qty\ntotal = amount\nprint(amount)\n'
    row = inline('a.py', src, src.index('amount'))
    assert row.after == 'total = (price * qty)\nprint((price * qty))\n' and row.edits == 2


def test_inline_brackets_a_value_that_would_reassociate():
    "Unbracketed, `a if b else c` inlined into `x * 2` would bind the multiply to `c` alone."
    src = 'x = a if b else c\nprint(x * 2)\n'
    assert inline('a.py', src, 0).after == 'print((a if b else c) * 2)\n'


def test_inline_leaves_an_already_atomic_value_unbracketed():
    src = 'n = 3\nprint(n)\n'
    assert inline('a.py', src, src.index('n)')).after == 'print(3)\n'


@pytest.mark.parametrize('src,pos,why', [
    ('x = 1\nx = 2\nprint(x)\n', 0, 'exactly once'),          # rebound, so no single value
    ('for x in items:\n    print(x)\n', 4, 'exactly once'),    # loop target, not an assignment
    ('x = 1\nglobal x\n', 0, 'global or nonlocal'),
    ('x = 1; print(x)\n', 0, 'lines of its own'),              # deleting the line loses the call
    ('x = 1  # keep\nprint(x)\n', 0, 'lines of its own'),      # ...and would eat the comment
    ('x = 1\n', 0, 'never read'),
])
def test_inline_refuses_what_it_cannot_reverse(src, pos, why):
    with pytest.raises(ValueError, match=why): inline('a.py', src, pos)


def test_inline_needs_the_cursor_on_a_name():
    with pytest.raises(ValueError, match='cursor on a variable'): inline('a.py', 'x = 1\n', 4)
