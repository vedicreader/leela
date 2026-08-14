"The web block end to end: routes, themes and the served bundle."

from __future__ import annotations
from pathlib import Path
from fasthtml.common import first, to_xml
from starlette.testclient import TestClient
from leela.blocks.term.term import TerminalGate
from leela.app import _shell, ide_app
from leela.workspace import Workspace
ROOT = Path(__file__).resolve().parents[2]
import re
from fastcore.all import L
import re, sys
from collections import Counter
from fastcore.all import L, Path

JS = (ROOT / 'leela/static/lee-ide.js').read_text()
CSS = (ROOT / 'leela/static/lee-ide.css').read_text()

def test_cursor_theme_is_default_and_keeps_light_dark_system():
    assert "const THEME_DEFAULT = 'cursor:light:tight'" in JS
    assert "localStorage.getItem('lee-theme')" in JS
    assert ':root[data-theme="cursor"][data-mode="light"]' in CSS
    assert ':root[data-theme="cursor"][data-mode="dark"]' in CSS
    assert 'thin quiet chrome' in JS
    assert ':root[data-density="tight"] .lee-btn.go' in CSS
    assert ':root[data-density="tight"] .lee-phead' in CSS
    assert ':root[data-density="tight"] .lee-node.sel' in CSS

def test_file_click_sets_the_same_selected_state_as_keyboard_navigation(tmp_path):
    "Mouse opens used to stopPropagation without painting `.sel`; keys already did."
    from leela.blocks.fs.ui import tree_node as _tree_node
    (tmp_path / 'alpha.py').write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    file_entry = first(ws.fs.ls(str(tmp_path)))
    html = to_xml(_tree_node(file_entry))
    assert 'leeOpenFile(' in html
    open_fn = JS[JS.index('async function leeOpenFile'):JS.index('window.leeOpenFile')]
    assert 'selectTreeNode(treeNode)' in open_fn, 'paint before the await, so the click feels instant'
    assert 'selectTreeNode(after)' in open_fn, 'and again after the tab bar swaps'
    assert 'function selectTreeNode(n)' in JS
    assert "n.classList.add('sel')" in JS
    assert 'window.selectTreeNode = selectTreeNode' in JS

def test_source_control_refreshes_when_the_working_directory_switches():
    "Which repository a panel asks about travels in `gitUI.repo`, via `gitUrl`."
    assert 'function gitUrl(path, params = {})' in JS
    assert "if (gitUI.repo) q.set('repo', gitUI.repo)" in JS
    assert 'gitUI.repoRoot' not in JS, 'one root-tracking field, not two'
    assert 'function scmPanelOpen()' in JS and 'function refreshScmIfOpen(' in JS
    cwd = JS[JS.index('async function leeCwd'):JS.index('window.leeCwd')]
    assert 'refreshScmIfOpen()' in cwd, 'a new cwd can imply a different repository'
    branch = JS[JS.index('async function leeBranchMenu'):JS.index('window.leeBranchMenu')]
    assert "api(gitUrl('/git/info'))" in branch
    assert "async def git_info(repo: str = '')" in (ROOT / 'leela/blocks/git/app.py').read_text()

def test_nbdev_prepare_uses_settings_ini_and_initialises_uv(tmp_path):
    (tmp_path / 'settings.ini').write_text(
        '[DEFAULT]\nlib_name = demo\nlib_path = demo\nnbs_path = nbs\n')
    (tmp_path / 'nbs').mkdir()
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        r = client.post('/project/nbdev_prepare', json={})
        body = r.json()
        assert r.status_code in (200, 400)
        if body.get('ok'):
            assert body['root'] == str(tmp_path)
            assert body['nbs_path'] == 'nbs'
        else:
            assert 'nbdev' in body.get('error', '').lower() or 'uv' in body.get('error', '').lower() \
                or 'settings.ini' in body.get('error', '').lower()
    assert "leeNbdevPrepare" in JS
    assert "'nbdev prepare…'" in JS or 'nbdev prepare…' in JS
    assert '/project/nbdev_prepare' in JS

def test_shell_still_exposes_workspace_and_git_switchers(tmp_path):
    html = to_xml(_shell(Workspace(roots=[tmp_path]), TerminalGate()))
    assert 'id="workspacepill"' in html and 'leeWorkspaceMenu(this)' in html
    assert 'id="gitpill"' in html and 'leeBranchMenu(this)' in html
    assert 'data-left="git"' in html

def test_agent_focus_action_opens_the_right_panel_before_prompt_fill():
    assert 'focus_agent:' in JS
    assert "leeRight('agent')" in JS
    assert "$('#agentprompt')?.focus()" in JS
    assert "applyTheme('cursor')" in (ROOT / 'tools/webshots.py').read_text()
    assert "leeAct('focus_agent')" in (ROOT / 'tools/webshots.py').read_text()

JS = (ROOT/'leela/static/lee-ide.js').read_text()
CSS = (ROOT/'leela/static/lee-ide.css').read_text()

TOKENS = set('bg bg1 bg2 bg3 fg fg2 fg4 border accent sel selection-fg red green yellow orange blue '
             'purple aqua output warning log active-line bracket guide'.split())
BLOCK = re.compile(r'([^{}]*?)\{([^{}]*?)\}', re.S)
VARIANT = re.compile(r':root\[data-theme="(\w+)"\]\[data-mode="(dark|light)"\]\s*$')

def css_variants():
    "family, mode -> the --lee-* names that variant's block declares."
    out = {}
    for sel, body in BLOCK.findall(CSS):
        for one in sel.split(','):
            if m := VARIANT.search(one.strip()):
                out[m.groups()] = set(re.findall(r'--lee-([\w-]+):', body))
    return out

def js_families():
    "The family names in the JS THEMES table."
    table = JS.split('const THEMES = {', 1)[1].split('\n};', 1)[0]
    return set(re.findall(r'^\s*(\w+):\s*\{', table, re.M))

def test_every_family_ships_a_dark_and_a_light_variant():
    variants = css_variants()
    families = js_families()
    assert families >= {'leela', 'cursor', 'vscode', 'jetbrains', 'solarized', 'gruvbox', 'nord', 'dracula'}
    assert {f for f, _ in variants} == families, 'a family exists in only one of CSS and JS'
    for family in families:
        assert (family, 'dark') in variants and (family, 'light') in variants, family

def test_every_variant_declares_every_colour_token():
    "Missing tokens fall through to whatever :root had, which is another theme's colour."
    for (family, mode), names in css_variants().items():
        assert not (TOKENS - names), f'{family}/{mode} is missing {sorted(TOKENS - names)}'

def test_whitespace_marks_have_their_own_token_in_every_variant():
    "The dots are drawn inside the selection, so --lee-fg4 washed out on light themes."
    assert 'var(--lee-space-mark)' in CSS.split('.cm-lee-space-mark')[1].split('}')[0]
    assert 'var(--lee-space-mark)' in CSS.split('.cm-lee-tab-mark')[1].split('}')[0]
    for (family, mode), names in css_variants().items():
        assert 'space-mark' in names, f'{family}/{mode}'

def test_colour_scheme_is_only_ever_dark_or_light():
    "A family name is not a valid `color-scheme`; it is silently ignored when one lands there."
    assigns = L(re.findall(r'colorScheme\s*=\s*([^;\n]+)', JS + (ROOT/'leela/app.py').read_text()))
    assert assigns, 'nothing sets colorScheme any more'
    for a in assigns: assert a.strip() in ('resolved', 'resolved;'), a

def test_density_is_its_own_axis_and_carries_the_chrome():
    "Tight chrome came from the cursor theme, but any family must be able to wear it."
    assert ':root[data-density="tight"] .lee-phead' in CSS
    assert ':root[data-density="tight"] .lee-node.sel' in CSS
    keyed = re.findall(r':root\[data-density="tight"\](\[data-mode="\w+"\])?\s+\.lee-', CSS)
    assert keyed and not all(keyed)
    assert re.findall(r':root\[data-theme="\w+"\]\s+\.lee-', CSS) == []
    assert "const THEME_DENSITIES = ['tight', 'relaxed']" in JS

def test_density_reaches_the_document_before_the_first_paint():
    "Painting relaxed chrome and then tightening it a frame later is the flash this avoids."
    app = (ROOT/'leela/app.py').read_text()
    assert 'dataset.density' in app and 'dataset.density' in JS
    for value in re.findall(r'dataset\.density\s*=\s*([^;\n]+)', JS):
        assert value.strip() == 'density'

def test_a_pre_family_preference_still_resolves():
    "`lee-theme` held system|dark|light|cursor; both readers must migrate it, not reset it."
    for reader in (JS, (ROOT/'leela/app.py').read_text()):
        assert "dark: 'leela:dark:relaxed'" in reader and "cursor: 'cursor:light:tight'" in reader

def _lab(hex_):
    "sRGB hex to CIE Lab, so two colours can be compared the way an eye compares them."
    h = hex_.strip().lstrip('#')
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
    r, g, b = f(r), f(g), f(b)
    X, Y, Z = (.4124*r + .3576*g + .1805*b)/.95047, .2126*r + .7152*g + .0722*b, (.0193*r + .1192*g + .9505*b)/1.08883
    k = lambda t: t ** (1/3) if t > .008856 else 7.787 * t + 16/116
    X, Y, Z = k(X), k(Y), k(Z)
    return 116*Y - 16, 500*(X - Y), 200*(Y - Z)

def _dE(a, b): return sum((x - y) ** 2 for x, y in zip(_lab(a), _lab(b))) ** .5

LEGEND = ('accent', 'aqua', 'orange', 'green', 'blue')

def variant_colours():
    "family, mode -> the declared `--lee-*` values, not just their names."
    out = {}
    for sel, body in BLOCK.findall(CSS):
        for one in sel.split(','):
            if m := VARIANT.search(one.strip()):
                out[m.groups()] = {k: v.strip() for k, v in re.findall(r'--lee-([\w-]+):\s*([^;]+);', body)}
    return out

def test_no_variant_paints_two_legend_colours_the_same():
    "A duplicated hex is a copy-paste, not a palette choice, and it makes a legend unreadable."
    import itertools
    for (fam, mode), tokens in variant_colours().items():
        for a, b in [*itertools.combinations(LEGEND, 2), ('blue', 'purple')]:
            assert tokens[a].lower() != tokens[b].lower(), f'{fam} {mode}: {a} and {b} are both {tokens[a]}'
            assert _dE(tokens[a], tokens[b]) > 5, f'{fam} {mode}: {a} and {b} are indistinguishable'

sys.path.insert(0, str(ROOT/'tools'))

import build_ide_js as builder  # noqa: E402

def test_every_module_ends_with_a_newline():
    "Without one, a module's last line fuses into the next module's first when concatenated."
    assert [p.name for p in builder.modules() if not p.read_text().endswith('\n')] == []

_DECL = re.compile(r'^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(', re.M)

def test_no_two_modules_declare_the_same_top_level_function():
    "The modules share one scope, so the later declaration silently wins."
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
    for name in ('leeCloneRepo', 'switchBranch', 'branchActions'): assert f'function {name}' in js, name
