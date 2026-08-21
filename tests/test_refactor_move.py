"Moving a definition to another file: what travels with it, and what the files that used it become."

import ast
import pytest
from leela.blocks.refactor.move import module_of, move_plan, top_symbols


def tree(tmp_path, files, package=False):
    "Write `files` under `tmp_path` and hand back the reader `move_plan` wants."
    for name, text in files.items():
        p = tmp_path/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    if package:
        for d in {(tmp_path/n).parent for n in files}:
            (d/'__init__.py').touch()
    def read(path):
        p = tmp_path/path if not str(path).startswith(str(tmp_path)) else __import__('pathlib').Path(path)
        return p.read_text() if p.is_file() else None
    return read

def plan(tmp_path, files, src, names, dest, package=False, **kw):
    read = tree(tmp_path, files, package)
    rows, notes = move_plan(read, tmp_path/src, names, tmp_path/dest,
                            [tmp_path/n for n in files if n.endswith('.py')], **kw)
    return {str(r.path).replace(str(tmp_path) + '/', ''): r for r in rows}, notes


SRC = """\
import math

BASE = 2


def area(r):
    "circle"
    return math.pi * r ** 2 * BASE


def perimeter(r):
    return 2 * math.pi * r
"""


def test_a_function_takes_its_imports_and_leaves_what_it_did_not_use(tmp_path):
    rows, _ = plan(tmp_path, {'shapes.py': SRC}, 'shapes.py', ['area'], 'circle.py')
    made = rows['circle.py']
    assert made.before is None, 'a file that did not exist has to be created, not patched'
    assert 'import math' in made.after and 'def area(r):' in made.after
    assert 'def perimeter' not in made.after
    ast.parse(made.after)
    assert 'def area' not in rows['shapes.py'].after
    assert 'import math' in rows['shapes.py'].after, 'perimeter still needs it'


def test_a_module_level_name_the_moved_code_reads_comes_back_as_an_import(tmp_path):
    "`BASE` stays behind, so the new file has to import it or `area` is broken."
    rows, _ = plan(tmp_path, {'shapes.py': SRC}, 'shapes.py', ['area'], 'circle.py')
    assert 'from shapes import BASE' in rows['circle.py'].after


def test_the_re_export_keeps_the_old_import_path_working(tmp_path):
    files = {'shapes.py': SRC.replace('BASE = 2', 'BASE = 2  # noqa')}
    files['shapes.py'] = files['shapes.py'].replace('* BASE', '* 2')
    rows, _ = plan(tmp_path, files, 'shapes.py', ['area'], 'circle.py')
    assert 'from circle import area' in rows['shapes.py'].after


def test_the_re_export_can_be_declined(tmp_path):
    files = {'shapes.py': SRC.replace('* BASE', '* 2')}
    rows, _ = plan(tmp_path, files, 'shapes.py', ['area'], 'circle.py', shim=False)
    assert 'circle' not in rows['shapes.py'].after


def test_a_re_export_nobody_needs_is_dropped_instead_of_making_a_cycle(tmp_path):
    "`area` reads `BASE`, so the new file imports the old one. A re-export back would be a cycle."
    rows, notes = plan(tmp_path, {'shapes.py': SRC}, 'shapes.py', ['area'], 'circle.py')
    assert 'from circle import area' not in rows['shapes.py'].after
    assert any('re-export left out' in n for n in notes)


def test_a_real_mutual_import_is_refused_rather_than_written(tmp_path):
    "Here the source still calls `area` itself, so the two modules genuinely need each other."
    src = SRC + '\n\ndef report(r):\n    return area(r)\n'
    with pytest.raises(ValueError, match='would import each other over BASE'):
        plan(tmp_path, {'shapes.py': src}, 'shapes.py', ['area'], 'circle.py')


def test_every_file_that_imported_the_name_is_repointed(tmp_path):
    files = {'shapes.py': SRC.replace('* BASE', '* 2'),
             'app.py': 'from shapes import area, perimeter\n\nprint(area(1), perimeter(1))\n'}
    rows, _ = plan(tmp_path, files, 'shapes.py', ['area'], 'circle.py', shim=False)
    after = rows['app.py'].after
    assert 'from shapes import perimeter' in after and 'from circle import area' in after
    ast.parse(after)


def test_a_dotted_import_becomes_a_from_import_and_the_dead_one_goes(tmp_path):
    files = {'shapes.py': SRC.replace('* BASE', '* 2'),
             'app.py': 'import shapes\n\nprint(shapes.area(1))\n'}
    rows, _ = plan(tmp_path, files, 'shapes.py', ['area'], 'circle.py', shim=False)
    after = rows['app.py'].after
    assert 'from circle import area' in after and 'print(area(1))' in after
    assert 'import shapes' not in after, 'nothing reads it any more'
    ast.parse(after)


def test_a_dotted_import_still_used_for_something_else_stays(tmp_path):
    files = {'shapes.py': SRC.replace('* BASE', '* 2'),
             'app.py': 'import shapes\n\nprint(shapes.area(1), shapes.perimeter(1))\n'}
    rows, _ = plan(tmp_path, files, 'shapes.py', ['area'], 'circle.py', shim=False)
    after = rows['app.py'].after
    assert 'import shapes' in after and 'shapes.perimeter(1)' in after and 'print(area(1)' in after


def test_relative_imports_are_written_relative_inside_a_package(tmp_path):
    files = {'pkg/shapes.py': SRC.replace('* BASE', '* 2'),
             'pkg/app.py': 'from .shapes import area\n\nprint(area(1))\n'}
    rows, _ = plan(tmp_path, files, 'pkg/shapes.py', ['area'], 'pkg/circle.py', package=True, shim=False)
    assert 'from .circle import area' in rows['pkg/app.py'].after
    assert module_of(tmp_path/'pkg/shapes.py') == 'pkg.shapes'


def test_decorators_and_the_comment_above_travel_with_the_definition(tmp_path):
    src = ('import functools\n\n\n# why this exists\n@functools.cache\n'
           'def slow(n):\n    return n * 2\n\n\ndef other(): pass\n')
    rows, _ = plan(tmp_path, {'a.py': src}, 'a.py', ['slow'], 'b.py', shim=False)
    made = rows['b.py'].after
    assert '# why this exists' in made and '@functools.cache' in made and 'import functools' in made
    assert '@functools.cache' not in rows['a.py'].after


def test_imports_fold_into_the_block_the_destination_already_has(tmp_path):
    files = {'a.py': 'import os\nimport re\n\n\ndef f():\n    return os.sep + re.escape("x")\n',
             'b.py': '"target"\n\nimport re\n\nX = 1\n'}
    rows, _ = plan(tmp_path, files, 'a.py', ['f'], 'b.py', shim=False)
    after = rows['b.py'].after
    assert after.count('import re') == 1, 'the existing import must not be duplicated'
    assert 'import os' in after and after.index('import os') < after.index('X = 1')
    ast.parse(after)


def test_from_imports_of_the_same_module_merge_into_one_line(tmp_path):
    files = {'a.py': 'from pathlib import Path\n\n\ndef f():\n    return Path(".")\n',
             'b.py': 'from pathlib import PurePath\n\nX = 1\n'}
    rows, _ = plan(tmp_path, files, 'a.py', ['f'], 'b.py', shim=False)
    after = rows['b.py'].after
    assert 'from pathlib import Path, PurePath' in after and after.count('from pathlib') == 1


def test_all_is_updated_at_both_ends(tmp_path):
    files = {'a.py': "__all__ = ['f', 'g']\n\n\ndef f(): pass\n\n\ndef g(): pass\n",
             'b.py': "__all__ = ['h']\n\n\ndef h(): pass\n"}
    rows, _ = plan(tmp_path, files, 'a.py', ['f'], 'b.py', shim=False)
    assert "__all__ = ['g']" in rows['a.py'].after
    assert "__all__ = ['h', 'f']" in rows['b.py'].after


def test_a_name_the_destination_already_defines_is_refused(tmp_path):
    files = {'a.py': 'def f(): pass\n', 'b.py': 'def f(): pass\n'}
    with pytest.raises(ValueError, match='already defines f'):
        plan(tmp_path, files, 'a.py', ['f'], 'b.py')


def test_a_name_that_would_arrive_unbound_is_refused(tmp_path):
    "`helper` is neither moved nor importable from the source, so the move would break `f`."
    src = 'from mystery import *\n\n\ndef f():\n    return helper()\n'
    with pytest.raises(ValueError, match='would lose helper'):
        plan(tmp_path, {'a.py': src}, 'a.py', ['f'], 'b.py', shim=False)


def test_moving_a_method_is_refused_because_only_top_level_names_move(tmp_path):
    files = {'a.py': 'class C:\n    def m(self): pass\n'}
    with pytest.raises(ValueError, match='not a top-level'):
        plan(tmp_path, files, 'a.py', ['m'], 'b.py')


def test_a_class_moves_with_everything_its_body_reads(tmp_path):
    src = 'import json\n\nSEP = ","\n\n\nclass Row:\n    def dump(self):\n        return json.dumps(SEP)\n'
    rows, _ = plan(tmp_path, {'a.py': src}, 'a.py', ['Row'], 'b.py', shim=False)
    after = rows['b.py'].after
    assert 'import json' in after and 'from a import SEP' in after and 'class Row:' in after
    ast.parse(after)


def test_top_symbols_reports_what_can_be_moved(tmp_path):
    rows = top_symbols(SRC)
    assert [r['name'] for r in rows] == ['area', 'perimeter']
    assert all(r['kind'] == 'function' for r in rows)
    assert SRC[rows[0]['start']:rows[0]['end']].startswith('def area')
