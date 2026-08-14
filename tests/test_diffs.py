"""Tests for `leela.core.text`.

Plain unit tests, because this module is pure text in and text out. The line numbers on
diff rows get the most attention: they exist so a frontend can jump from a changed line
to the place it lives, and they are derived from the hunk header rather than from the
rows themselves, which is exactly the kind of arithmetic that is wrong until it is tested.
"""

import pytest

from leela.core.text import (DiffRow, closest, diff_label, diff_rows, diff_stat,
                                did_you_mean, fuzzy_rank, udiff)

A = 'def f(x):\n    return x\n\nz = 1\n'
B = 'def f(x, y=0):\n    return x + y\n\nz = 1\nw = 2\n'


def test_identical_texts_have_no_diff():
    assert udiff(A, A) == ''
    assert list(diff_rows(udiff(A, A))) == []
    assert diff_label(A, A) == ''


def test_rows_carry_the_new_side_line_numbers():
    "Added and context rows number into the *new* text; deletions have no line there."
    rows = diff_rows(udiff(A, B))
    added = [(r.line, r.text) for r in rows if r.kind == 'add']
    assert added == [(1, 'def f(x, y=0):'), (2, '    return x + y'), (5, 'w = 2')]
    assert all(r.line == 0 for r in rows if r.kind == 'del')
    assert [(r.line, r.text) for r in rows if r.kind == 'ctx'] == [(3, ''), (4, 'z = 1')]


def test_markers_are_stripped_so_frontends_can_paint_them():
    "No row's text starts with its own +/- marker; that is the renderer's job, not the parser's."
    for r in diff_rows(udiff(A, B)):
        if r.kind in ('add', 'del', 'ctx'):
            assert not r.text.startswith(('+', '-')) or r.text == ''


def test_stat_and_label():
    assert diff_stat(A, B) == (3, 2)
    assert diff_label(A, B) == '+3 −2'
    assert diff_label('', 'one\ntwo\n') == '+2'
    assert diff_label('one\ntwo\n', '') == '−2'


def test_rows_are_serialisable():
    "Routes hand these to JSON, so `.dict()` has to be the whole row."
    assert diff_rows(udiff(A, B))[0].dict().keys() == {'kind', 'text', 'line'}


def test_names_add_a_header():
    assert udiff(A, B, names=('old', 'new')).startswith('--- old\n+++ new\n')
    assert not udiff(A, B).startswith('---')


def test_none_is_treated_as_empty():
    "Reading a file that does not exist yet gives None; a diff against it is a pure addition."
    assert diff_stat(None, 'x\n') == (1, 0)


# -- did you mean ----------------------------------------------------------
def test_nameerror_gets_a_suggestion():
    got = did_you_mean("NameError: name 'df2' is not defined", ['df_2', 'ns', 'x'])
    assert "did you mean 'df_2'?" in got


def test_no_suggestion_when_nothing_is_close():
    err = "NameError: name 'zzzz' is not defined"
    assert did_you_mean(err, ['df_2', 'total']) == err


@pytest.mark.parametrize('err', [None, '', 'TypeError: unsupported operand', 'ZeroDivisionError: x'])
def test_other_errors_are_untouched(err):
    assert did_you_mean(err, ['df']) == err


def test_closest_is_ordered_best_first():
    assert closest('dfram', ['df', 'dframe', 'frame'])[0] == 'dframe'


# -- fuzzy ranking ---------------------------------------------------------
FILES = ['a/web/app.py', 'a/some_long_app_helper.py', 'a/ide/panels/app.py',
         'a/README.md', 'a/apple/pie.txt']


def test_exact_basename_beats_a_scattered_match():
    assert list(fuzzy_rank('app', FILES))[0] == 'a/web/app.py'


def test_subsequence_spans_directories():
    "A fuzzy finder should let `wapp` mean web/app.py."
    assert list(fuzzy_rank('wapp', FILES)) == ['a/web/app.py']


def test_no_match_returns_nothing():
    assert list(fuzzy_rank('zzz', FILES)) == []


def test_empty_query_keeps_everything_in_order():
    assert list(fuzzy_rank('', FILES)) == FILES
    assert len(fuzzy_rank('', FILES, limit=2)) == 2


def test_ranking_is_case_insensitive():
    assert list(fuzzy_rank('README', FILES))[0] == 'a/README.md'
