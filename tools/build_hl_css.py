#!/usr/bin/env python
"""Write `leela/static/lee-hl.css`: the token colours for every Leela theme and mode.

The `hl-*` spans come from `ramabana.hl.diff_html` in diffs and from mdhtml in Markdown code blocks.
A family takes a fastpylight theme by name, or a palette of its own from `PALETTES`.
`--check` fails when the file and this mapping have drifted.
"""
from __future__ import annotations
import sys
import fastpylight
from fastcore.all import Path

OUT = Path(__file__).resolve().parent.parent/'leela'/'static'/'lee-hl.css'

#: family -> mode -> role -> colour. Roles are the editor's highlight style plus what diffs and prose add.
PALETTES = {
    'ember': {
        'dark': dict(keyword='#cc8a6e', string='#adb276', number='#cc9aaf', function='#d2b07a', definition='#e0c49a',
                     type='#9eb28c', operator='#c4a58a', comment='#a08f78', fg='#c9bba4', added='#a9b86e', removed='#e08a6e'),
        'light': dict(keyword='#99472a', string='#5b6320', number='#88486a', function='#7a5a1e', definition='#6b4a28',
                      type='#476845', operator='#7a5640', comment='#6b5e4f', fg='#4a3f33', added='#56622a', removed='#9c4430')},
    'dusk': {
        'dark': dict(keyword='#8fa9d4', string='#a2bf9a', number='#c3a5c9', function='#88bfcc', definition='#b7c7e6',
                     type='#92c2b4', operator='#a9b7cc', comment='#8f99a9', fg='#c4ccd7', added='#a3c19f', removed='#d49297'),
        'light': dict(keyword='#3a5c91', string='#3e663a', number='#744a7c', function='#1e6370', definition='#4a4c8a',
                      type='#2e6656', operator='#4d5a6e', comment='#566273', fg='#2f3b4a', added='#3f6440', removed='#94404a')}}

#: Leela theme family -> the Lumis theme, or the palette, for its dark and its light mode.
THEMES = {'leela': ('github_dark', 'github_light'), 'cursor': ('github_dark', 'github_light'),
          'vscode': ('vscode_dark', 'vscode_light'), 'jetbrains': ('onedark', 'onelight'),
          'solarized': ('solarized_osaka_dark', 'solarized_osaka_light'), 'gruvbox': ('gruvbox_dark', 'gruvbox_light'),
          'nord': ('nord', 'onenord_light'), 'dracula': ('dracula', 'github_light'),
          'github': ('github_dark', 'github_light'),
          **{f: (p['dark'], p['light']) for f, p in PALETTES.items()}}

#: scope prefix -> (role, extra declarations). mdhtml classes a span by its whole scope only, so a rule
#: matches every class that starts with its prefix, and a longer prefix comes later and wins.
SCOPES = {'normal': ('fg', ''), 'variable': ('fg', ''), 'punctuation': ('fg', ''), 'markup': ('fg', ''),
          'keyword': ('keyword', ''), 'tag': ('keyword', ''), 'markup-list': ('keyword', ''),
          'string': ('string', ''), 'character': ('string', ''), 'markup-raw': ('string', ''), 'markup-math': ('string', ''),
          'number': ('number', ''), 'boolean': ('number', ''), 'constant': ('number', ''), 'variable-builtin': ('number', ''),
          'function': ('function', ''), 'markup-heading': ('function', 'font-weight: bold; '),
          'variable-parameter': ('definition', ''), 'type-definition': ('definition', ''),
          'type': ('type', ''), 'constructor': ('type', ''), 'module': ('type', ''), 'namespace': ('type', ''), 'label': ('type', ''),
          'operator': ('operator', ''), 'property': ('operator', ''), 'attribute': ('operator', ''), 'tag-attribute': ('operator', ''),
          'variable-member': ('operator', ''), 'string-escape': ('operator', ''), 'string-special': ('operator', ''),
          'markup-link': ('operator', 'text-decoration: underline; '),
          'comment': ('comment', 'font-style: italic; '), 'markup-quote': ('comment', 'font-style: italic; '),
          'markup-italic': ('fg', 'font-style: italic; '), 'markup-strong': ('fg', 'font-weight: bold; '),
          'markup-strikethrough': ('fg', 'text-decoration: line-through; '), 'markup-underline': ('fg', 'text-decoration: underline; '),
          'diff-plus': ('added', ''), 'diff-minus': ('removed', ''), 'diff-delta': ('function', ''), 'error': ('removed', '')}

#: The editor's highlight style reads these, so its spans take the palette (`frontend/editor.js` `hl`).
EDITOR = dict(red='keyword', green='string', purple='number', blue='function', orange='definition', yellow='type', aqua='operator',
              fg4='comment')

def palette_css(p, sel):
    "Rules for palette `p` under `sel`: the `hl-*` spans, then the editor's highlight spans."
    out = [f'{sel} [class*="hl-{k}"] {{ color: {p[r]}; {x}}}' for k, (r, x) in sorted(SCOPES.items(), key=lambda o: len(o[0]))]
    out.append(f'{sel} .hl-highlighted {{ background-color: color-mix(in srgb, {p["function"]} 16%, transparent); }}')
    out.append(f'{sel} .cm-line span:not([class*="cm-"]):not([class*="lee-"]) {{ '
               + ' '.join(f'--lee-{v}: {p[r]};' for v, r in EDITOR.items()) + ' }')
    return '\n'.join(out)

def colors(theme):
    "role-ish scope -> foreground, for a fastpylight theme name or a palette."
    if isinstance(theme, dict): return {k: theme[r] for k, (r, _) in SCOPES.items()}
    return {k: v['fg'] for k, v in fastpylight.theme_colors(theme).items() if v.get('fg')}

def css():
    "The stylesheet. Rules come sorted, so a longer scope follows its prefix and wins where a theme names both."
    out = ['/* Generated by tools/build_hl_css.py from fastpylight themes and its own palettes. Do not edit. */']
    for fam, modes in THEMES.items():
        for mode, theme in zip(('dark', 'light'), modes):
            sel = f':root[data-theme="{fam}"][data-mode="{mode}"]'
            out.append(palette_css(theme, sel) if isinstance(theme, dict) else fastpylight.theme_css(theme, selector=sel))
    out.append(fastpylight.theme_css('github_dark', selector=':root:not([data-mode])'))
    out.append('@media (prefers-color-scheme: light) {\n' + fastpylight.theme_css('github_light', selector=':root:not([data-mode])') + '\n}')
    return '\n'.join(out) + '\n'

if __name__ == '__main__':
    if '--check' in sys.argv:
        if not OUT.exists() or OUT.read_text() != css(): sys.exit(f'{OUT.name} is stale: run tools/build_hl_css.py')
        print(f'{OUT.name} is current')
    else:
        OUT.write_text(css())
        print(f'wrote {OUT.name}: {len(css().splitlines())} lines')
