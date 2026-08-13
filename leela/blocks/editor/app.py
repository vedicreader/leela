"""Editor services that are neither the kernel's job nor Pyright's.

Formatting never writes; the browser saves the returned text. ruff then black, both from the
*project* interpreter, so the result matches what the project's own CI does.
"""

from __future__ import annotations

import json, subprocess, sys
from pathlib import Path

from ...core.web import fail, off_loop

__all__ = ['CAPS', 'connect', 'project_package_rows']

CAPS = ('fs', 'pool')


def project_package_rows(path, python=None):
    "Declared pyproject requirements with installed versions and source-line addresses."
    import tomllib
    p = Path(path)
    source = p.read_text(encoding='utf-8')
    data = tomllib.loads(source)
    project = data.get('project') or {}
    declared = list(project.get('dependencies') or [])
    for values in (project.get('optional-dependencies') or {}).values(): declared += list(values or [])
    for values in (data.get('dependency-groups') or {}).values():
        declared += [x for x in (values or []) if isinstance(x, str)]
    try:
        from packaging.requirements import Requirement
        parsed = [(Requirement(x), x) for x in declared]
    except Exception: parsed = []
    names = list(dict.fromkeys(r.name for r, _raw in parsed))
    versions = {}
    if names:
        script = ('import importlib.metadata as m,json,sys\n'
                  'out={}\n'
                  'for n in json.loads(sys.argv[1]):\n'
                  ' try: out[n]=m.version(n)\n'
                  ' except m.PackageNotFoundError: out[n]=None\n'
                  'print(json.dumps(out))')
        try:
            proc = subprocess.run([str(python or sys.executable), '-c', script, json.dumps(names)],
                                  capture_output=True, text=True, timeout=8, check=True)
            versions = json.loads(proc.stdout)
        except Exception: versions = {n: None for n in names}
    rows, used = [], set()
    lines = source.splitlines()
    for req, raw in parsed:
        try:
            if req.marker and not req.marker.evaluate(): continue
        except Exception: pass
        # The whole quoted declaration, not the bare name: that also occurs in keywords and URLs.
        found = None
        for i, line in enumerate(lines, 1):
            for quote in ('"', "'"):
                token = f'{quote}{raw}{quote}'
                at = line.find(token)
                key = (i, at, token)
                if at >= 0 and key not in used:
                    found = (i, at + len(token)); used.add(key); break
            if found: break
        if not found: continue
        installed = versions.get(req.name)
        compatible = None
        if installed is not None and str(req.specifier):
            try: compatible = req.specifier.contains(installed, prereleases=True)
            except Exception: compatible = None
        rows.append({'line': found[0], 'column': found[1], 'name': req.name,
                     'required': str(req.specifier), 'marker': str(req.marker or ''),
                     'installed': installed, 'compatible': compatible,
                     'python': str(python or sys.executable)})
    return rows


def _format_cwd(ctx, path=''):
    "The directory whose formatter configuration applies to `path`, else the chosen project's."
    if str(path or '').strip():
        try:
            p = ctx.fs._check(path, must_exist=False)
            return str(ctx.fs.root_of(p))
        except Exception: pass
    root = ctx.session.project_root
    return str(root) if root else None


def connect(app, ctx):
    rt = app.route

    @rt('/editor/format')
    async def editor_format(req):
        "Format without writing; the browser reviews and saves the returned text."
        d = await req.json(); text = str(d.get('text') or ''); lang = d.get('lang') or ''
        if len(text) > 2_000_000: return fail('formatter input is larger than 2 MB')
        try:
            if lang == 'json':
                formatted = json.dumps(json.loads(text), indent=2, ensure_ascii=False) + '\n'
            elif lang == 'python':
                from ..runtime.kernels import project_python
                python = ctx.pool.default_python or project_python(ctx.fs.roots) or sys.executable
                # ruff finds `pyproject.toml` from `cwd`, so it must be the folder the *file* is in.
                cwd = _format_cwd(ctx, d.get('path'))
                def format_python():
                    choices = [[str(python), '-m', 'ruff', 'format', '-'], [str(python), '-m', 'black', '-q', '-']]
                    failures=[]
                    for cmd in choices:
                        result=subprocess.run(cmd,input=text,text=True,capture_output=True,cwd=cwd,timeout=30)
                        if result.returncode == 0: return result.stdout
                        failures.append(result.stderr.strip())
                    raise RuntimeError('install ruff or black in the project environment · ' + ' · '.join(x for x in failures if x))
                formatted = await off_loop(format_python)
            else: return fail(f'no formatter configured for {lang or "this file"}')
            return {'ok': True, 'text': formatted}
        except Exception as e: return fail(e)

    @rt('/editor/packages')
    def editor_packages(path: str):
        "Installed-version annotations for a workspace pyproject.toml."
        try:
            p = ctx.fs._check(path, must_exist=True)
            if p.name != 'pyproject.toml': return {'packages': [], 'summary': {}}
            python = ctx.pool.default_python or sys.executable
            rows = project_package_rows(p, python)
            return {'packages': rows, 'summary': {
                'total': len(rows), 'installed': sum(r['installed'] is not None for r in rows),
                'missing': sum(r['installed'] is None for r in rows),
                'mismatch': sum(r['compatible'] is False for r in rows),
                'python': str(python),
            }}
        except Exception as e: return fail(e)
