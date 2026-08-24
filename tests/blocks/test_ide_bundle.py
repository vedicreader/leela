"""What the client's bundles must hold true, whatever the modules say.

They are concatenations into one shared lexical scope, so order is a contract and a name
declared twice is the last one winning silently. These are structural checks over the built
assets, not assertions about anyone's source text.
"""

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
    """`ACTIONS` used to hold `help: showHelp`, read the moment the module ran. A function
    declaration hoists to the top of its own script and no further, so that pinned the whole
    client to one script tag. Every entry is a thunk now; a bare name would pin it again.
    """
    src = next(p for p in builder.modules() if p.name == 'actions.js').read_text()
    lines = src.split('\n')
    start = next(i for i, l in enumerate(lines) if l.startswith('const ACTIONS = {'))
    end = next(i for i, l in enumerate(lines) if i > start and l.startswith('};'))
    bare = [l.strip() for l in lines[start:end + 1]
            if re.match(r'^\s+[A-Za-z_$][\w$]*\s*:\s*[A-Za-z_$][\w$]*,?\s*$', l)]
    assert bare == [], f'bare references would pin the client to one script tag: {bare}'

def test_no_bundle_reads_a_later_bundles_declaration_at_load_time():
    """The failure this prevents is not graceful: the throw aborts the rest of that bundle, so
    every `let` after it stays in its temporal dead zone and the shell paints but does nothing.
    A bare name used as a value in a top-level literal is read when the module runs, so it must
    not name a function some later bundle declares.
    """
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
    """`lee-help` was the `?` badge and the keyboard panel at once. The panel's rule is later in the
    file, so it won, and every badge rendered as a padded two-column grid with a 50% radius."""
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
    """It positions itself from `getBoundingClientRect` and redrew on scroll, document, viewport and
    geometry changes. Moving a panel resizes the pane that scrolls without any of those, so the
    stripe kept its old top and height and stranded itself where the pane used to be."""
    src = (ROOT/'frontend'/'editor.js').read_text()
    plugin = src[src.index('function overviewPlugin'):src.index('const stickyPlugin')]
    assert 'new ResizeObserver' in plugin, 'resize is the signal that was missing'
    assert 'this.ro?.disconnect()' in plugin or 'this.ro.disconnect()' in plugin, 'and it must be released'
    assert 'never `this.dom`' in plugin, 'observing what draw() resizes would loop'
    # The pane that scrolls can change; the old one must not keep the class that hides its bar.
    assert "previous.classList.remove('has-overview')" in plugin

def test_the_built_editor_bundle_matches_its_source():
    """`lee-cm6.js` is committed, so a change to `frontend/editor.js` that was never built is a lie.

    The export map is read by the names it exports, not by the minifier's name for the call that
    builds it: that one is chosen per build, and any edit to the source could rename it.
    """
    bundle = (ROOT/'leela'/'vendor'/'lee-cm6.js').read_text()
    assert 'ResizeObserver' in bundle, 'rebuild with frontend/node_modules/@esbuild/*/bin/esbuild'
    from tests.assets import cm_exports
    assert {'undo', 'redo'} <= cm_exports()


def test_the_setup_modal_renders_into_the_box_and_not_over_it():
    """`renderSetup` assigned to the element `modal()` returns, which is the backdrop. That threw
    away the `.lee-modalbox` wrapper and with it every style, the grip and the close button, and the
    two panes plus Tools lay transparent over the page. It re-renders, so overwriting the box itself
    is no better: the second render would drop the chrome again."""
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
    """`.lee-setup-pane` asked for `var(--lee-bd)`, which nothing defines, so the whole border
    shorthand was invalid and the panes drew no edge at all. The box is `overflow: hidden`, so the
    middle region has to be the one that scrolls or the Updates rows are unreachable."""
    assert '.lee-modalbox > .lee-setup-body { min-height: 0; flex: 1 1 auto; overflow: auto; }' in CSS
    declared = set(re.findall(r'(--lee-[\w-]+)\s*:', CSS))
    # Some are written onto an element as an inline style instead: the indent guides from
    # `frontend/editor.js`, the cell and code line counts from the bundles.
    runtime = set(re.findall(r'--lee-[\w-]+', JS + (ROOT/'frontend/editor.js').read_text()))
    used = set(re.findall(r'var\((--lee-[\w-]+)\s*\)', CSS))
    assert used - declared - runtime == set(), f'undefined and nothing sets them: {sorted(used - declared - runtime)}'


def test_a_routing_row_keeps_its_help_mark_out_of_the_control_column():
    """`.lee-routing-popover label` is a two-column row: name, then control. A row with a `?` had
    three children, so the mark took the control's column and the select wrapped onto a second line
    into the 82px name column, where every model name was clipped. The name and its mark are one
    item, in both the server-rendered rows and the ones `paintJobModels` draws."""
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
    """`saveTab` reports why it failed, in the status line or the conflict dialog, and the run guard
    then wrote `save the notebook before running this cell` over the top of it. The only diagnosable
    part of the failure was replaced by advice to do the thing that had just failed."""
    src = (ROOT/'leela/blocks/nb/motion.js').read_text()
    assert 'save the notebook before running this cell' not in src
    assert re.search(r"\.dirty'\) && !await saveTab\(true\)\) return;", src)


def test_the_overview_stripe_does_not_decide_from_a_measure_it_changes_itself():
    """`shown` compared `scrollHeight` against `clientHeight`, and `has-overview` sets
    `scrollbar-width: none`. `clientHeight` excludes a horizontal bar, so hiding one grew it by the
    bar's thickness: a pane overflowing by less than that said yes, took the class, then said no on
    the next frame, and the bar flickered. Code cells have the horizontal bar, and an agent pane
    streaming tokens re-measures every frame."""
    src = (ROOT/'frontend'/'editor.js').read_text()
    helper = src[src.index('const overflowsDown'):src.index('function scrollerFor')]
    assert 'getBoundingClientRect().height' in helper, 'the border box is what a bar cannot move'
    plugin = src[src.index('function overviewPlugin'):src.index('const stickyPlugin')]
    decision = plugin[plugin.index('const shown ='):plugin.index('this.dom.hidden')]
    assert 'overflowsDown(scroller)' in decision
    assert 'clientHeight' not in decision, 'the decision may not read what the class changes'


def test_the_scroller_walk_never_reaches_the_document():
    """In a browser the document overflows where the app window does not, so the walk returned
    `<body>`. `has-overview` on `<body>` matches no rule, so the bar it was meant to hide stayed:
    the leftover scroll bar that was fixed in the app and not on the web."""
    src = (ROOT/'frontend'/'editor.js').read_text()
    walk = src[src.index('function scrollerFor'):src.index('function overviewPlugin')]
    assert 'e !== document.body' in walk.replace('el', 'e'), 'body ends the walk, never answers it'
    assert 'overflowsDown(el)' in walk
    bundle = (ROOT/'leela'/'vendor'/'lee-cm6.js').read_text()
    assert 'e!==document.body' in bundle, 'rebuild with frontend/node_modules/@esbuild/*/bin/esbuild'
    assert 'getBoundingClientRect().height;return e>0&&i.scrollHeight>e+4' in bundle


def test_indent_runs_against_the_cell_or_the_file_the_caret_is_in():
    """Indent has to work in a notebook cell and in a python file. The router hands the chord to
    CodeMirror's own command on the editor the event came from, which is either; the palette path
    goes through `curEditor`, which answers for either. Neither may reach for the file editor."""
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
    """`.lee-krow` is a flex line with `nowrap` and an ellipsis on every span. The setup modal
    borrowed it, so `ready` rendered as `rea…` and every blurb was cut mid-sentence: these rows
    are a name, a state and a sentence, and the sentence has to be allowed to wrap."""
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
