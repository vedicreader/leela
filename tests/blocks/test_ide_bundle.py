"""What the client's bundles must hold true, whatever the modules say."""

from __future__ import annotations
import re, sys
from collections import Counter
from pathlib import Path
from fastcore.all import L

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder                                              # noqa: E402

CSS = (ROOT/'leela/static/lee-ide.css').read_text()
JS = ''.join((builder.OUTDIR/n).read_text() for n in builder.LAYERS)
DECL = re.compile(r'^(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)', re.M)

def test_every_bundle_is_its_modules_concatenated():
    for name in builder.LAYERS:
        assert (builder.OUTDIR/name).read_text() == builder.bundle(name), \
            f'{name} is stale; run python tools/build_ide_js.py'

def test_the_order_is_complete_and_names_nothing_that_is_not_there():
    "A module added to a block but left out of `LAYERS` would silently never load."
    assert builder.missing() == []
    assert builder.orphans() == []

def test_the_bundles_are_what_the_application_serves():
    "`core.web.IDE_BUNDLES` is the serving order; the build must produce exactly those."
    from leela.core.web import IDE_BUNDLES
    assert tuple(builder.LAYERS) == IDE_BUNDLES
    for name in IDE_BUNDLES: assert (builder.OUTDIR/name).is_file(), name

def test_the_dispatch_table_holds_thunks_and_not_bare_references():
    """`ACTIONS` used to hold `help: showHelp`, read the moment the module ran."""
    src = next(p for p in builder.modules() if p.name == 'actions.js').read_text()
    lines = src.split('\n')
    start = next(i for i, l in enumerate(lines) if l.startswith('const ACTIONS = {'))
    end = next(i for i, l in enumerate(lines) if i > start and l.startswith('};'))
    bare = [l.strip() for l in lines[start:end + 1]
            if re.match(r'^\s+[A-Za-z_$][\w$]*\s*:\s*[A-Za-z_$][\w$]*,?\s*$', l)]
    assert bare == [], f'bare references would pin the client to one script tag: {bare}'

def test_no_bundle_reads_a_later_bundles_declaration_at_load_time():
    """The failure this prevents is not graceful: the throw aborts the rest of that bundle, so every `let` after it stays in its temporal dead zone and the shell paints but does nothing."""
    mods = builder.modules()
    at, bundle_of = {}, {}
    for i, (name, names) in enumerate(builder.LAYERS.items()):
        for n in names: bundle_of[str(builder.PKG/n)] = i
    for i, p in enumerate(mods):
        for m in re.finditer(r'^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)', p.read_text(), re.M):
            at.setdefault(m.group(1), i)
    bad = []
    for i, p in enumerate(mods):
        for ln, line in enumerate(p.read_text().split('\n'), 1):
            m = (re.match(r'^\s+[A-Za-z_$][\w$]*\s*:\s*([A-Za-z_$][\w$]*),?\s*$', line)
                 or re.match(r'^ACTIONS(?:\.\w+|\[[^\]]+\])\s*=\s*([A-Za-z_$][\w$]*)\s*;?\s*$', line))
            if not m: continue
            j = at.get(m.group(1))
            if j is not None and bundle_of[str(mods[j])] > bundle_of[str(p)]:
                bad.append(f'{p.name}:{ln} reads {m.group(1)!r} from a later bundle')
    assert bad == [], bad

def test_every_module_ends_with_a_newline():
    "Without one a module's last line fuses into the next module's first."
    assert [p.name for p in builder.modules() if not p.read_text().endswith('\n')] == []

def test_no_name_is_declared_in_two_modules():
    "One shared scope, so the second declaration wins and the first silently stops existing."
    decls = L(builder.modules()).map(lambda p: set(DECL.findall(p.read_text())))
    dupes = sorted(n for n, c in Counter(n for s in decls for n in s).items() if c > 1)
    assert dupes == [], f'declared in more than one module: {dupes}'

TOKENS = set('bg bg1 bg2 bg3 fg fg2 fg4 border accent sel selection-fg red green yellow orange blue '
             'purple aqua output warning log active-line bracket guide'.split())
BLOCK = re.compile(r'([^{}]*?)\{([^{}]*?)\}', re.S)
VARIANT = re.compile(r':root\[data-theme="(\w+)"\]\[data-mode="(dark|light)"\]\s*$')
LEGEND = ('accent', 'aqua', 'orange', 'green', 'blue')

def variants(values=False):
    "family, mode -> the `--lee-*` names that variant declares, or their values."
    out = {}
    for sel, body in BLOCK.findall(CSS):
        for one in sel.split(','):
            if m := VARIANT.search(one.strip()):
                out[m.groups()] = ({k: v.strip() for k, v in re.findall(r'--lee-([\w-]+):\s*([^;]+);', body)}
                                   if values else set(re.findall(r'--lee-([\w-]+):', body)))
    return out

def families():
    "The family names in the JS THEMES table."
    table = JS.split('const THEMES = {', 1)[1].split('\n};', 1)[0]
    return set(re.findall(r'^\s*(\w+):\s*\{', table, re.M))

def _lab(hex_):
    "sRGB hex to CIE Lab, so two colours compare the way an eye compares them."
    h = hex_.strip().lstrip('#')
    r, g, b = [int(h[i:i+2], 16)/255 for i in (0, 2, 4)]
    f = lambda c: c/12.92 if c <= .04045 else ((c + .055)/1.055)**2.4
    r, g, b = f(r), f(g), f(b)
    X, Y, Z = (.4124*r + .3576*g + .1805*b)/.95047, .2126*r + .7152*g + .0722*b, (.0193*r + .1192*g + .9505*b)/1.08883
    k = lambda t: t**(1/3) if t > .008856 else 7.787*t + 16/116
    X, Y, Z = k(X), k(Y), k(Z)
    return 116*Y - 16, 500*(X - Y), 200*(Y - Z)

def _dE(a, b): return sum((x - y)**2 for x, y in zip(_lab(a), _lab(b)))**.5

def test_every_theme_family_exists_in_both_css_and_js():
    fams = families()
    assert fams >= {'leela', 'cursor', 'vscode', 'jetbrains', 'solarized', 'gruvbox', 'nord', 'dracula'}
    assert {f for f, _ in variants()} == fams, 'a family exists in only one of CSS and JS'
    for f in fams: assert (f, 'dark') in variants() and (f, 'light') in variants(), f

def test_every_theme_variant_declares_every_token():
    for (family, mode), names in variants().items():
        assert not (TOKENS - names), f'{family}/{mode} is missing {sorted(TOKENS - names)}'
        assert 'space-mark' in names, f'{family}/{mode}'

def test_the_legend_colours_stay_distinguishable_in_every_variant():
    "Two identical legend colours make a chart unreadable, and dark modes drift together."
    import itertools
    for (fam, mode), tokens in variants(values=True).items():
        for a, b in [*itertools.combinations(LEGEND, 2), ('blue', 'purple')]:
            assert tokens[a].lower() != tokens[b].lower(), f'{fam} {mode}: {a} and {b} are both {tokens[a]}'
            assert _dE(tokens[a], tokens[b]) > 5, f'{fam} {mode}: {a} and {b} are indistinguishable'

def test_density_is_its_own_axis_and_not_a_property_of_a_family():
    "Tight chrome came from the cursor theme, but any family must be able to wear it."
    keyed = re.findall(r':root\[data-density="tight"\](\[data-mode="\w+"\])?\s+\.lee-', CSS)
    assert keyed and not all(keyed), 'density rules must exist and not all be mode-specific'
    assert re.findall(r':root\[data-theme="\w+"\]\s+\.lee-', CSS) == [], 'chrome keyed to a family'

def test_no_rule_paints_one_activity_button_unlike_its_siblings():
    "A `[data-left=...]` background made the files tab a different colour from the rest of the rail."
    assert re.findall(r'\.lee-activity-btn\[data-left=[^\]]+\]', CSS) == []

def test_the_pill_neutralises_the_button_defaults():
    "`#runspill` is a button and `#kpill` a span, so the UA border and font must be overridden."
    rule = re.search(r'\.lee-pill \{(.*?)\}', CSS, re.S).group(1)
    for decl in ('appearance: none', '-webkit-appearance: none', 'border: 0', 'font-family: inherit',
                 'line-height:', 'align-items: center'): assert decl in rule, decl


def test_no_class_is_both_an_inline_badge_and_a_container():
    """`lee-help` was the `?` badge and the keyboard panel at once."""
    css = (ROOT/'leela'/'static'/'lee-ide.css').read_text()
    import re
    decls = {}
    for m in re.finditer(r'^\.(lee-[\w-]+)\s*\{([^}]*)\}', css, re.M):
        decls.setdefault(m.group(1), []).append(m.group(2))
    for name, bodies in decls.items():
        joined = ' '.join(bodies)
        inline = 'display: inline-flex' in joined or 'display: inline-block' in joined
        grid = 'display: grid' in joined or 'display: flex' in joined and 'inline' not in joined
        assert not (inline and 'display: grid' in joined), \
            f'.{name} is declared both inline and as a grid; two things are sharing one class'

def test_the_hint_badge_and_the_help_panel_are_different_classes():
    "The badge is `lee-hint`, the keyboard panel is `lee-help`. Neither may take the other's name."
    css = (ROOT/'leela'/'static'/'lee-ide.css').read_text()
    app = (ROOT/'leela'/'app.py').read_text()
    panel = (ROOT/'leela'/'blocks'/'agent'/'panel.js').read_text()
    assert '.lee-hint {' in css and 'display: inline-flex' in css.split('.lee-hint {')[1][:200]
    assert "cls='lee-hint'" in app and 'class="lee-hint"' in panel
    assert "cls='lee-help'" not in app and 'class="lee-help"' not in panel


def test_the_overview_stripe_redraws_when_a_panel_resizes():
    """It positions itself from `getBoundingClientRect` and redrew on scroll, document, viewport and geometry changes."""
    src = (ROOT/'frontend'/'editor.js').read_text()
    plugin = src[src.index('function overviewPlugin'):src.index('const stickyPlugin')]
    assert 'new ResizeObserver' in plugin, 'resize is the signal that was missing'
    assert 'this.ro?.disconnect()' in plugin or 'this.ro.disconnect()' in plugin, 'and it must be released'
    assert 'never `this.dom`' in plugin, 'observing what draw() resizes would loop'
    # The pane that scrolls can change; the old one must not keep the class that hides its bar.
    assert 'overviewGutter(previous, false, this.gutter)' in plugin


def test_hiding_the_scroll_bar_holds_back_the_width_it_was_taking():
    """Where the platform draws the bar in the flow, `has-overview` handed its width to the text."""
    src = (ROOT/'frontend'/'editor.js').read_text()
    gutter = src[src.index('export function overviewGutter'):src.index('// The element that really')]
    assert 'el.offsetWidth - el.clientWidth' in gutter, 'the thickness is measured, never assumed'
    assert 'paddingRight' in gutter and 'bar > .5' in gutter
    assert 'el.dataset.leeGutter' in gutter, 'and it is given back when the stripe goes'
    assert 'held.delete(by)' in gutter, 'to the stripes that took it, and to no others'
    for name in ('leela/static/lee-ide.js', 'leela/blocks/git/cwd.js'):
        nb = (ROOT/name).read_text()
        assert "LeeCM.overviewGutter(host, on, 'nb')" in nb, f'{name} toggles the same class'
        assert "host.classList.toggle('has-overview'" not in nb

def test_the_built_editor_bundle_matches_its_source():
    """`lee-cm6.js` is committed, so a change to `frontend/editor.js` that was never built is a lie."""
    bundle = (ROOT/'leela'/'vendor'/'lee-cm6.js').read_text()
    assert 'ResizeObserver' in bundle, 'rebuild with frontend/node_modules/@esbuild/*/bin/esbuild'
    from tests.assets import cm_exports
    assert {'undo', 'redo'} <= cm_exports()


def test_the_setup_modal_renders_into_the_box_and_not_over_it():
    """`renderSetup` assigned to the element `modal()` returns, which is the backdrop."""
    src = (ROOT/'leela/blocks/agent/panel.js').read_text()
    render = src[src.index('function renderSetup('):src.index('async function leeSetupModal')]
    assert '.lee-setup-body' in render, 'only the middle region may be rewritten'
    assert not re.search(r'\bhost\.innerHTML\s*=|\bbox\.innerHTML\s*=', render), \
        'assigning the box its own markup discards the chrome modal() built'
    opener = src[src.index('async function leeSetupModal'):src.index('async function pollSetup')]
    for part in ('lee-mhead', 'lee-setup-body', 'lee-mfoot'): assert part in opener, part
    assert "$('.lee-modalbox', m)" in opener, 'renderSetup takes the box, never the backdrop'
    assert 'm.remove()' in opener, "done must close through modal()'s own teardown"


def test_the_setup_body_scrolls_and_every_colour_it_names_exists():
    """`.lee-setup-pane` asked for `var(--lee-bd)`, which nothing defines, so the whole border shorthand was invalid and the panes drew no edge at all."""
    assert '.lee-modalbox > .lee-setup-body { min-height: 0; flex: 1 1 auto; overflow: auto; }' in CSS
    declared = set(re.findall(r'(--lee-[\w-]+)\s*:', CSS))
    # Some are written onto an element as an inline style instead: the indent guides from
    # `frontend/editor.js`, the cell and code line counts from the bundles.
    runtime = set(re.findall(r'--lee-[\w-]+', JS + (ROOT/'frontend/editor.js').read_text()))
    used = set(re.findall(r'var\((--lee-[\w-]+)\s*\)', CSS))
    assert used - declared - runtime == set(), f'undefined and nothing sets them: {sorted(used - declared - runtime)}'


def test_a_routing_row_keeps_its_help_mark_out_of_the_control_column():
    """`.lee-routing-popover label` is a two-column row: name, then control."""
    assert '.lee-routing-popover label > .lee-routing-name' in CSS
    app = (ROOT/'leela/app.py').read_text()
    panel = (ROOT/'leela/blocks/agent/panel.js').read_text()
    popover = app[app.index("Details(Summary('settings')"):app.index("cls='lee-routing-popover'")]
    for mark in re.finditer(r'help_mark\(', popover):
        head = popover[:mark.start()].rindex('Label(')
        assert 'lee-routing-name' in popover[head:popover.index(')', mark.end()) + 60], \
            'a help mark outside a lee-routing-name is a third grid item'
    rows = panel[panel.index('function paintJobModels'):panel.index('window.leeLoadModels')]
    assert re.search(r'lee-routing-name">\$\{esc\(job\)\}\$\{helpMark\(job\)\}</span>', rows)


def test_a_cell_run_blocked_by_a_failed_save_keeps_the_reason():
    """`saveTab` reports why it failed, in the status line or the conflict dialog, and the run guard then wrote `save the notebook before running this cell` over the top of it."""
    src = (ROOT/'leela/blocks/nb/motion.js').read_text()
    assert 'save the notebook before running this cell' not in src
    assert re.search(r"\.dirty'\) && !await saveTab\(true\)\) return;", src)


def test_the_overview_stripe_does_not_decide_from_a_measure_it_changes_itself():
    """`shown` compared `scrollHeight` against `clientHeight`, and `has-overview` sets `scrollbar-width: none`."""
    src = (ROOT/'frontend'/'editor.js').read_text()
    helper = src[src.index('const OVER_SHOW'):src.index('function scrollerFor')]
    assert 'getBoundingClientRect().height' in helper, 'the border box is what a bar cannot move'
    # And hysteresis on top, because rendered markdown settles over several frames.
    assert 'shown ? OVER_HIDE : OVER_SHOW' in helper
    assert 'OVER_SHOW = 24' in helper and 'OVER_HIDE = 8' in helper
    plugin = src[src.index('function overviewPlugin'):src.index('const stickyPlugin')]
    decision = plugin[plugin.index('const shown ='):plugin.index('this.dom.hidden')]
    assert 'overflowsDown(scroller,' in decision
    assert 'clientHeight' not in decision, 'the decision may not read what the class changes'


def test_the_stripe_hides_the_bar_of_whatever_it_actually_replaced():
    """`has-overview` goes on the element that really scrolls, which is not always `.lee-editor`: a markdown preview scrolls itself."""
    assert '.has-overview { scrollbar-width:none; }' in CSS
    assert '.has-overview::-webkit-scrollbar' in CSS
    assert '.lee-editor.has-overview {' not in CSS, 'the rule follows the class, not one element'
    rule = CSS[CSS.index('.lee-md-preview { border'):]
    assert 'scrollbar-gutter: stable' in rule[:rule.index('}')], 'the gutter is always there'


def test_the_scroller_walk_never_reaches_the_document():
    """In a browser the document overflows where the app window does not, so the walk returned `<body>`."""
    src = (ROOT/'frontend'/'editor.js').read_text()
    walk = src[src.index('function scrollerFor'):src.index('function overviewPlugin')]
    assert 'e !== document.body' in walk.replace('el', 'e'), 'body ends the walk, never answers it'
    assert 'overflowsDown(el)' in walk
    bundle = (ROOT/'leela'/'vendor'/'lee-cm6.js').read_text()
    assert 'e!==document.body' in bundle, 'rebuild with frontend/node_modules/@esbuild/*/bin/esbuild'
    assert 'getBoundingClientRect().height' in bundle and 'scrollHeight' in bundle


def test_indent_runs_against_the_cell_or_the_file_the_caret_is_in():
    """Indent has to work in a notebook cell and in a python file."""
    from tests.assets import cm_exports
    assert {'indentMore', 'indentLess', 'indentSelection'} <= cm_exports(), \
        'rebuild frontend/editor.js with frontend/node_modules/@esbuild/*/bin/esbuild'
    router = (ROOT/'leela/blocks/keys/keymap.js').read_text()
    deferred = router[router.index('const DEFER_IN_TEXT'):router.index('function textEditorOf')]
    for action, cmd in (('indent_more', 'indentMore'), ('indent_less', 'indentLess'),
                        ('indent_selection', 'indentSelection')):
        assert f'{action}: ' in deferred and cmd in deferred, action
    # `textEditorOf` matches any mounted editor, so a cell qualifies as much as a file.
    assert '[...lee.editors.values()].find' in router
    focus = (ROOT/'leela/static/js/focus.js').read_text()
    body = focus[focus.index('function leeIndent'):focus.index('function kernelComplete')]
    assert 'curEditor()' in body and "editors.get('file')" not in body
    actions = (ROOT/'leela/static/js/actions.js').read_text()
    for action in ('indent_more', 'indent_less', 'indent_selection'):
        assert f'{action}:' in actions, f'{action} has no entry in the action table'


def test_the_setup_rows_are_not_the_keyboard_help_row():
    """`.lee-krow` is a flex line with `nowrap` and an ellipsis on every span."""
    panel = (ROOT/'leela/blocks/agent/panel.js').read_text()
    assert 'lee-krow' not in panel, 'the help row is not this row'
    rule = CSS[CSS.index('.lee-setup-row {'):]
    rule = rule[:rule.index('}') + 1]
    assert 'display: grid' in rule and 'minmax(0, 1fr) auto' in rule
    # The state beside the name is the one column that may refuse to wrap; the sentence may not.
    for m in re.finditer(r'(\.lee-setup-row[^{]*)\{([^}]*)\}', CSS):
        if 'nowrap' in m.group(2):
            assert 'lee-dim' in m.group(1) or 'warn' in m.group(1), m.group(1).strip()


def test_the_setup_modal_can_be_started_over():
    "Dismissed once, there was no way back to the first-run prompt. The route already took a false."
    panel = (ROOT/'leela/blocks/agent/panel.js').read_text()
    assert 'id="setupreset"' in panel, 'the modal offers it'
    reset = panel[panel.index("$('#setupreset', box)"):panel.index("$('#setupdone', box)")]
    assert "'/agent/setup/dismiss', {dismissed: false}" in reset, 'and it clears the dismissal'
    assert 'leeSetupPane()' in reset and 'leeSetupModal()' in reset, 'then shows it again'


def test_a_splitter_drag_does_no_work_that_has_to_wait_for_a_disk():
    """`localStorage` is synchronous and disk-backed, and the drag handler wrote to it on every pointer event."""
    src = (ROOT/'leela/blocks/editor/split.js').read_text()
    def body(at):
        "The `move` handler's own braces, so init code that clamps a stored width is not read as one."
        start = src.index('{', at); depth = 0
        for i in range(start, len(src)):
            depth += (src[i] == '{') - (src[i] == '}')
            if depth == 0: return src[start:i]
        raise AssertionError('unbalanced move handler')
    moves = [body(m.end()) for m in re.finditer(r'const move = ', src)]
    assert len(moves) >= 2, 'both splitters have one'
    for handler in moves:
        assert 'setProperty' in handler, 'it still moves the pane'
        assert 'localStorage' not in handler, f'this runs per pointer event: {handler.strip()[:90]}'
    assert src.count('localStorage.setItem') >= 2, 'and both still remember where they were left'


def test_the_overview_stripe_settles_after_a_resize_rather_than_chasing_it():
    """A splitter drag resizes every mounted editor at pointer rate, and each redraw resizes and repaints a canvas."""
    src = (ROOT/'frontend'/'editor.js').read_text()
    plugin = src[src.index('function overviewPlugin'):src.index('const stickyPlugin')]
    assert 'new ResizeObserver(() => this.later())' in plugin, 'resize goes through the debounce'
    assert "addEventListener('scroll', this.queue, true)" in plugin, 'scroll does not'
    assert 'clearTimeout(this.settle)' in plugin.split('destroy()')[1], 'and it is released'
    bundle = (ROOT/'leela'/'vendor'/'lee-cm6.js').read_text()
    assert 'ResizeObserver' in bundle, 'rebuild with frontend/node_modules/@esbuild/*/bin/esbuild'


def test_the_first_history_read_is_paid_for_before_anybody_clicks():
    """The agent's log is one append-only file that grows without bound."""
    boot = (ROOT/'leela/static/js/boot.js').read_text()
    live = (ROOT/'leela/blocks/agent/live.js').read_text()
    assert 'warmAgentHistory' in boot and 'requestIdleCallback' in boot, 'at idle, not on the boot path'
    warm = live[live.index('function warmAgentHistory'):live.index('async function leeAgentHistory')]
    assert 'historyGroups()' in warm and 'catch' in warm, 'and it never speaks up if it fails'
    # The same fetch the list itself uses, so the warm answer is the one the click is served.
    groups = live[live.index('async function historyGroups'):live.index('async function showHistorySession')]
    assert "'/agent/history'" in groups and 'everything=1' in groups


def test_a_cell_wears_its_id_rather_than_hiding_it_behind_a_hover():
    "It was reachable only by hovering the meta button, and it is wanted often enough to be read."
    src = (ROOT/'leela/blocks/nb/cells.js').read_text()
    head = src[src.index('lee-cell-meta'):src.index('lee-cell-summary')]
    assert 'lee-cell-id' in head, 'the id is not in the header markup'
    assert '${esc(c.id)}' in head, 'and it is escaped'
    # A repaint must move it too, or an id goes stale the moment a cell is inserted above it.
    paint = src[src.index('function paintCellMeta'):src.index('function copyCellId')]
    assert 'lee-cell-id' in paint and 'c.id' in paint
    assert '.lee-cell-id' in CSS, 'and it is styled rather than inheriting the size run-on'
    assert 'lee-cell-id' in JS, 'and the built bundle carries it'


def test_rebuilding_the_shell_repaints_the_git_pill():
    """Opening a folder swaps the whole shell, which puts the server's `no git` placeholder back."""
    boot = (ROOT/'leela/static/js/boot.js').read_text()
    swap = boot[boot.index("htmx:afterSwap"):]
    shell = swap[swap.index("id === 'shell'"):swap.index('});')]
    assert 'refreshProjectPills' in shell, 'a rebuilt shell never asks what repository it is in'
    tabs = swap[swap.index("id === 'tabbar'"):swap.index("id === 'shell'")]
    assert 'refreshProjectPills' in tabs, 'and the tab swap must keep doing it'


def test_the_git_pill_tells_a_broken_request_apart_from_a_folder_with_no_repository():
    "One catch rendered both as `no git`, so a failure read as a fact about the user's project."
    src = (ROOT/'leela/blocks/git/cwd.js').read_text()
    fn = src[src.index('async function refreshProjectPills'):src.index('async function gitInfo')]
    body, _, handler = fn.rpartition('} catch (e) {')
    assert handler, 'the git branch no longer catches the error it needs to report'
    code = '\n'.join(l for l in handler.splitlines() if not l.strip().startswith('//'))
    assert 'no git' not in code, 'a request that failed still claims the folder is not a checkout'
    assert 'git ?' in handler and 'console.error' in handler, 'and it says so both on screen and in the console'
    # The absence is still reported, but only where the server actually said so.
    assert "d.repo === false" in body and 'no git' in body
    # `gitInfo` throws for a folder outside a repository, which would land in the catch again.
    assert 'await api(' in body and 'await gitInfo()' not in body


def test_the_pill_repaint_survives_a_broken_tree_or_notice():
    "`paintGitTree` and `noticeGitState` run after the label, so neither can blank a good branch."
    src = (ROOT/'leela/blocks/git/cwd.js').read_text()
    fn = src[src.index('async function refreshProjectPills'):src.index('async function gitInfo')]
    assert fn.index('git.textContent = `${d.branch}') < fn.index('paintGitTree(d)')


def test_a_finished_run_stops_its_clock_and_loses_its_stop_button():
    """The strip drew every row from `Date.now()`, so a subagent that had stopped counted on."""
    src = (ROOT/'leela/blocks/agent/steer.js').read_text()
    fn = src[src.index('function updateAgentRunstrip'):src.index('async function pauseAgentAfterCurrent')]
    assert 'r.ended' in fn, 'the clock still ignores when the run actually ended'
    assert 'TERMINAL.has(r.state)' in fn, 'and nothing tells a finished run from a working one'
    stop = fn[fn.index('data-stop-run'):]
    assert 'done ?' in fn[:fn.index('data-stop-run')], 'Stop is offered for a run that already stopped'
    # The states must match ramabana's `Run.terminal`, or a row is called live that the server dropped.
    assert set(re.findall(r"'(\w+)'", src[src.index('const TERMINAL'):src.index('function updateAgentRunstrip')])) \
        == {'completed', 'cancelled', 'detached', 'terminated', 'failed'}
    assert 'TERMINAL' in JS, 'and the built bundle carries it'
