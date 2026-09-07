"Editor services that are neither the kernel's job nor Pyright's."

from __future__ import annotations

import json, subprocess, sys
from pathlib import Path

from ...core.web import fail, off_loop
from kunda.pythons import clean_env
from ..runtime.kernels import venv_env, _runtime_python

__all__ = ['CAPS', 'connect', 'project_package_rows']

CAPS = ('fs', 'pool')   # `pool` is read by `python_for(session=ctx)`, not here

_VERSIONS_SCRIPT = ('import importlib.metadata as m,json,sys\n'
                    'out={}\n'
                    'for n in json.loads(sys.argv[1]):\n'
                    ' try: out[n]=m.version(n)\n'
                    ' except m.PackageNotFoundError: out[n]=None\n'
                    'print(json.dumps(out))')

def _declared(data):
    "Every requirement string a pyproject states, across dependencies, extras and groups."
    project = data.get('project') or {}
    out = list(project.get('dependencies') or [])
    for values in (project.get('optional-dependencies') or {}).values(): out += list(values or [])
    for values in (data.get('dependency-groups') or {}).values():
        out += [x for x in (values or []) if isinstance(x, str)]
    return out

def _installed_versions(names, python):
    "What `python` actually has installed, asked of that interpreter rather than of ours."
    if not names: return {}
    try:
        proc = subprocess.run([str(python), '-c', _VERSIONS_SCRIPT, json.dumps(names)],
                              capture_output=True, text=True, timeout=8, check=True, env=clean_env())
        return json.loads(proc.stdout)
    except Exception: return {n: None for n in names}

def _locate(lines, raw, used):
    "Where `raw` is declared, as `(line, end column)`. `used` keeps repeats on separate lines."
    for i, line in enumerate(lines, 1):
        for quote in ('"', "'"):
            token = f'{quote}{raw}{quote}'
            at = line.find(token)
            if at >= 0 and (key := (i, at, token)) not in used:
                used.add(key)
                return i, at + len(token)
    return None

def _applies(req):
    "Whether this requirement's environment marker is satisfied here. An unreadable marker is not a no."
    try: return not (req.marker and not req.marker.evaluate())
    except Exception: return True

def _compatible(req, installed):
    "Whether the installed version satisfies the declared specifier. `None` when nothing is declared."
    if installed is None or not str(req.specifier): return None
    try: return req.specifier.contains(installed, prereleases=True)
    except Exception: return None

def project_package_rows(path, python=None):
    "Declared pyproject requirements with installed versions and source-line addresses."
    import tomllib
    python = str(python or sys.executable)
    source = Path(path).read_text(encoding='utf-8')
    declared = _declared(tomllib.loads(source))
    try:
        from packaging.requirements import Requirement
        parsed = [(Requirement(x), x) for x in declared]
    except Exception: parsed = []
    versions = _installed_versions(list(dict.fromkeys(r.name for r, _raw in parsed)), python)
    lines, used, rows = source.splitlines(), set(), []
    for req, raw in parsed:
        if not _applies(req): continue
        found = _locate(lines, raw, used)
        if not found: continue
        installed = versions.get(req.name)
        rows.append({'line': found[0], 'column': found[1], 'name': req.name,
                     'required': str(req.specifier), 'marker': str(req.marker or ''),
                     'installed': installed, 'compatible': _compatible(req, installed),
                     'python': python})
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
                from ..runtime.kernels import python_for
                # ruff finds `pyproject.toml` from `cwd`, so it must be the folder the *file* is in.
                cwd = _format_cwd(ctx, d.get('path'))
                # The formatter comes from that folder's own environment. `_runtime_python` rather
                # than `sys.executable`: in the bundle that name is the app itself.
                python = python_for(cwd, session=ctx) or _runtime_python()
                def format_python():
                    "ruff first, then black, whichever the project has."
                    failures = []
                    for cmd in ([str(python), '-m', 'ruff', 'format', '-'], [str(python), '-m', 'black', '-q', '-']):
                        result = subprocess.run(cmd, input=text, text=True, capture_output=True, cwd=cwd,
                                                timeout=30, env=venv_env(python))
                        if result.returncode == 0: return result.stdout
                        failures.append(result.stderr.strip())
                    raise RuntimeError('install ruff or black in the project environment · '
                                       + ' · '.join(x for x in failures if x))
                formatted = await off_loop(format_python)
            else: return fail(f'no formatter configured for {lang or "this file"}')
            return {'ok': True, 'text': formatted}
        except Exception as e: return fail(e)
    @rt('/editor/packages')
    def editor_packages(path: str):
        "Installed-version annotations for a workspace pyproject.toml."
        from ..runtime.kernels import python_for
        try:
            p = ctx.fs._check(path, must_exist=True)
            if p.name != 'pyproject.toml': return {'packages': [], 'summary': {}}
            # `python_for`, not `sys.executable`: in a frozen app that is the bundle, and running
            # it relaunches Leela.
            python = python_for(p.parent, session=ctx)
            if python is None and getattr(sys, 'frozen', False):
                return {'packages': [], 'summary': {}, 'note': 'no interpreter for this project'}
            python = python or sys.executable
            rows = project_package_rows(p, python)
            return {'packages': rows, 'summary': {
                'total': len(rows), 'installed': sum(r['installed'] is not None for r in rows),
                'missing': sum(r['installed'] is None for r in rows),
                'mismatch': sum(r['compatible'] is False for r in rows),
                'python': str(python),
            }}
        except Exception as e: return fail(e)
