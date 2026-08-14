"The served `lee-ide.js` is generated: it must equal its `static/js/` modules."

import re, sys
from collections import Counter

from fastcore.all import L, Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT/'tools'))

import build_ide_js as builder  # noqa: E402


def test_every_module_ends_with_a_newline():
    "Without one, a module's last line fuses into the next module's first when concatenated."
    assert [p.name for p in builder.modules() if not p.read_text().endswith('\n')] == []


_DECL = re.compile(r'^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(', re.M)


def test_no_two_modules_declare_the_same_top_level_function():
    """The modules share one scope, so the later declaration silently wins.

    Nothing reports this: the build succeeds, the page loads, and the losing module's callers
    reach a function with the same name and a different signature. That is how the source
    control panel's branch kebab came to hand `openChromeMenu` a string and throw.
    """
    names = L(builder.modules()).map(lambda p: set(_DECL.findall(p.read_text())))
    dupes = sorted(n for n, c in Counter(n for s in names for n in s).items() if c > 1)
    assert dupes == [], f'declared in more than one module: {dupes}'


def test_the_committed_bundle_matches_its_modules():
    "Editing lee-ide.js directly is the drift this catches; edit the module and rebuild."
    assert builder.OUT.read_text() == builder.bundle(), 'run python tools/build_ide_js.py'


def test_the_bundle_defines_the_entry_points_the_server_renders():
    "app.py renders onclick=leeAct(...) and friends; the split must keep them all present."
    js = builder.OUT.read_text()
    for fn in ('function leeAct', 'function leeLeft', 'function leeRight', 'function leePane'): assert fn in js, fn


def test_the_empty_state_is_written_only_in_python():
    "`mountTab` clones `#leeempty`; a second copy in JS is the drift that put them out of step."
    from fasthtml.common import to_xml
    from leela.app import _editor_pane
    js = builder.OUT.read_text()
    assert 'lee-empty-features' not in js and '#leeempty' in js
    html = to_xml(_editor_pane(_NoTab()))
    assert '<template id="leeempty">' in html and 'lee-empty-features' in html


class _NoTab:
    tab = None


def test_the_branch_pill_and_its_icons_have_handlers_in_the_bundle():
    "The header renders these four names inline; a missing one is a dead control in the top bar."
    from fasthtml.common import to_xml
    from leela.app import _header
    from leela.workspace import Workspace
    js, html = builder.OUT.read_text(), to_xml(_header(Workspace(roots=[])))
    for name in ('leeBranchMenu', 'leeGitQuick'):
        assert f'function {name}' in js, name
        assert name in html, name
    # Reached from the popup rather than from the header, so the header cannot vouch for them.
    for name in ('leeCloneRepo', 'switchBranch', 'branchActions'): assert f'function {name}' in js, name
