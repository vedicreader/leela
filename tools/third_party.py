#!/usr/bin/env python
"""Write `leela/vendor/THIRD_PARTY_NOTICES.md`: each package in the vendored browser bundles, its version, its licence and the licence text.

Run `npm ci` in `frontend/` first. The widgets bundle is built in a scratch folder (see `leela/vendor/README`); pass that folder's
`node_modules` with `--widgets`. `--check` fails when the file lists another set of packages than `frontend/package-lock.json`.
"""
from __future__ import annotations
import json, sys
from fastcore.all import Path

ROOT = Path(__file__).resolve().parent.parent
OUT, LOCK = ROOT/'leela'/'vendor'/'THIRD_PARTY_NOTICES.md', ROOT/'frontend'/'package-lock.json'
TOOLS = ('esbuild', '@esbuild/')
LICENCE_FILES = ('LICENSE', 'LICENCE', 'COPYING', 'LICENSE.md', 'LICENSE.txt', 'LICENCE.md', 'license', 'license.md', 'LICENSE-MIT')
#: Vendored files that no npm lock describes: (what, version, licence, licence file under leela/vendor)
OTHERS = (('KaTeX (katex/)', '0.16.47', 'MIT', 'katex/LICENSE-KaTeX.txt'),
          ('Font Awesome Free (fonts/fa-solid-900.woff2)', '5.15.4', 'OFL-1.1 (font), MIT (code)', 'fonts/LICENSE-Font-Awesome.txt'),
          ('rupaka (lee-rupaka.js, lee-rupaka.css)', '0.0.15', 'MIT', None))

def lock_pkgs(lock=LOCK):
    "`{name: version}` of each package `lock` installs, without the build tools."
    ps = json.loads(Path(lock).read_text())['packages']
    return {k.split('node_modules/')[-1]: v['version'] for k, v in ps.items() if k and not k.split('node_modules/')[-1].startswith(TOOLS)}

def installed(nm):
    "`{name: (version, licence, text)}` of each package in the folder `nm`, without the build tools."
    res = {}
    for pj in sorted(Path(nm).glob('**/package.json')):
        d = pj.parent
        if d.parent.name != 'node_modules' and d.parent.parent.name != 'node_modules': continue
        try: m = json.loads(pj.read_text())
        except ValueError: continue
        if not (n := m.get('name')) or n.startswith(TOOLS) or 'version' not in m: continue
        lic = m.get('license') or m.get('licenses') or 'not stated'
        if isinstance(lic, dict): lic = lic.get('type', 'not stated')
        if isinstance(lic, list): lic = ' OR '.join(o.get('type', '?') if isinstance(o, dict) else str(o) for o in lic)
        f = next((d/o for o in LICENCE_FILES if (d/o).is_file()), None)
        res.setdefault(n, (m['version'], str(lic), f.read_text(errors='replace').strip() if f else ''))
    return res

def section(title, pkgs):
    rows = [f'| {n} | {v} | {l} |' for n, (v, l, _) in sorted(pkgs.items())]
    texts = [f'### {n} {v}\n\n```\n{t}\n```' if t else f'### {n} {v}\n\nThe package has no licence file. Its package.json gives the licence as {l}.'
             for n, (v, l, t) in sorted(pkgs.items())]
    return '\n'.join([f'## {title}', '', '| Package | Version | Licence |', '| --- | --- | --- |', *rows, '', *texts, ''])

def render(front, widgets):
    others = ['| What | Version | Licence |', '| --- | --- | --- |', *(f'| {w} | {v} | {l} |' for w, v, l, _ in OTHERS)]
    texts = [f'### {w}\n\n```\n{(OUT.parent/f).read_text().strip()}\n```' for w, _, _, f in OTHERS if f]
    return '\n'.join(['# Third-party notices', '',
        'Leela ships these browser files in `leela/vendor/`. Each is built from, or is a copy of, the packages below. Leela itself is Apache-2.0.', '',
        section('lee-cm6.js, lee-term.js, lee-term.css and htmx.min.js (frontend/package-lock.json)', front),
        section('lee-widgets.js', widgets) if widgets else '',
        '## Other vendored files', '', *others, '', *texts, ''])

def check():
    "The packages that the notice lists for the frontend lock, against the lock itself."
    s = OUT.read_text().split('## lee-widgets.js')[0]
    listed = {l.split(' | ')[0][2:]: l.split(' | ')[1] for l in s.splitlines() if l.startswith('| ') and not l.startswith(('| Package', '| ---', '| What'))}
    return listed == lock_pkgs()

if __name__ == '__main__':
    if '--check' in sys.argv: sys.exit(0 if check() else 'THIRD_PARTY_NOTICES.md is out of date: run tools/third_party.py')
    w = sys.argv[sys.argv.index('--widgets')+1] if '--widgets' in sys.argv else None
    front = {n: o for n, o in installed(ROOT/'frontend'/'node_modules').items() if n in lock_pkgs()}
    OUT.write_text(render(front, installed(w) if w else {}))
    print(f'wrote {OUT}')
