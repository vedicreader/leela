"Ramabana's porcelain, and the notebook half the IDE adds to it."

from __future__ import annotations

import json

from fastcore.all import Path
from ramabana.git import GitError, GitRepo as _GitRepo, _unborn, clone, clone_target, gateway, repo_root

from ..nb.nb import source_spans as _source_spans

__all__ = ['GitRepo', 'GitError', 'repo_root', 'clone', 'clone_target', 'wire_env']

def _project_env(cwd):
    "The virtualenv a checkout's own hooks and filters run under."
    from ..runtime.kernels import project_python, venv_env
    p = Path(cwd).expanduser().resolve()
    for d in (p, *p.parents):
        if (py := project_python([d])): return venv_env(py)
        if (d/'.git').exists(): break
    return None

def wire_env():
    "Git runs under the checkout's own virtualenv. `Workspace` calls this."
    gateway().env_for = _project_env
    return gateway()

class GitRepo(_GitRepo):
    "The harness's repository, plus what only an IDE that opens notebooks can say about one."
    def blame_notebook(self, path):
        "`git blame` for a notebook, grouped into the cells you actually wrote."
        rows = self.blame(path)
        by_line = {r['line']: r for r in rows}
        raw = self._version(path, 'worktree')
        if not raw:
            try: raw = (self.root/path).read_text(errors='replace')
            except OSError: raw = ''
        try: cells = (json.loads(raw) or {}).get('cells') or []
        except (TypeError, json.JSONDecodeError):
            return {'notebook': False, 'path': path, 'cells': [], 'lines': rows,
                'error': 'this file is not a notebook Leela can read'}
        spans = _source_spans(raw, cells)
        out, seen = [], {}
        for i, (cell, span) in enumerate(zip(cells, spans), 1):
            source = cell.get('source') or ''
            source = source if isinstance(source, list) else str(source).splitlines(True)
            lines = []
            if span:
                for n, text in zip(range(span[0], span[1] + 1), source):
                    r = by_line.get(n)
                    if r is None: continue
                    lines.append({'line': n, 'n': n - span[0] + 1, 'text': str(text).rstrip('\n'),
                        'oid': r['oid'], 'author': r['author'], 'summary': r['summary'],
                        'timestamp': r['timestamp'], 'uncommitted': _unborn(r['oid'])})
                    seen.setdefault(r['oid'], {'oid': r['oid'], 'author': r['author'],
                        'summary': r['summary'], 'timestamp': r['timestamp'],
                        'uncommitted': _unborn(r['oid'])})
            commits, last = {}, None
            for row in lines:
                commits[row['oid']] = commits.get(row['oid'], 0) + 1
                if last is None or row['timestamp'] >= last['timestamp']: last = row
            out.append({
                'index': i, 'id': str(cell.get('id') or ''), 'kind': str(cell.get('cell_type') or 'code'),
                'first': span[0] if span else 0, 'last': span[1] if span else 0,
                'lines': lines, 'commits': [{'oid': k, 'lines': v} for k, v in commits.items()],
                'authors': sorted({row['author'] for row in lines if row['author']}),
                'touched': {k: last[k] for k in ('oid', 'author', 'summary', 'timestamp',
                    'uncommitted')} if last else {},
                'mapped': bool(span),
            })
        return {'notebook': True, 'path': path, 'cells': out, 'lines': rows,
            'commits': sorted(seen.values(), key=lambda c: -c['timestamp']), 'error': ''}
