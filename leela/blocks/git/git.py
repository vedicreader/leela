"Ramabana's porcelain, and the notebook half the IDE adds to it."

from __future__ import annotations

import json

from fastcore.all import Path, first
from ramabana.git import (GitError, GitRepo as _GitRepo, _invalidate, _plural, _unborn, clone,
    clone_target, gateway, repo_root)

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
    #: `(path, text) -> None`, set per instance to the sandbox's atomic write. The overrides below
    #: are Ramabana's, with the one call that touches bytes routed through it.
    saver = None
    def save(self, target, text):
        "One worktree write, through `saver` when the block set one."
        if self.saver is None: Path(target).write_text(str(text), encoding='utf-8')
        else: self.saver(Path(target), str(text))
    #: `paths -> None`, set per instance beside `saver`. The index a mutation replaces cannot be
    #: read back out of the journal's text, so it is read here, before the staging happens.
    stager = None
    def stage(self, paths):
        "Stage, handing `stager` the index as it stands first, so an undo can put it back."
        if self.stager is not None: self.stager([str(p) for p in paths])
        return super().stage(paths)
    #: `(target, before, after, oid) -> None`, set per instance beside `saver`. A whole-side
    #: resolution is a Git checkout, which writes the worktree file itself and cannot be expressed
    #: as a write through `saver`: `git show :2:` hands back the cleaned blob, so writing that would
    #: clean it a second time and stage content that is on neither side. What the checkout replaced
    #: is read here instead. `oid` is the blob the replaced file hashed to.
    sider = None
    #: `path -> None`, set per instance beside `saver`. Taking the side of a modify/delete conflict
    #: that deleted the file removes a file that may be binary, executable or a symlink, and none of
    #: those survives being journal text, so the block moves it aside whole instead.
    dropper = None
    def drop(self, target):
        "One worktree removal, through `dropper` when the block set one."
        if self.dropper is None: Path(target).unlink()
        else: self.dropper(Path(target))
    def stages(self, path):
        "`stage -> (mode, oid)` for one path's unmerged index entries, empty when it is settled."
        out = {}
        for line in self.index_entries([path]):
            mode, oid, stage = line.split('\t')[0].split(' ')
            if stage != '0': out[stage] = (mode, oid)
        return out
    def resolve_conflict(self, path, choice, content=None):
        "Ramabana's, plus the side of a modify/delete that has no file, and what a checkout replaced."
        stages = self.stages(path) if choice in ('ours', 'theirs') else {}
        if stages and {'ours': '2', 'theirs': '3'}[choice] not in stages:
            return self._drop_side(path, choice, stages)
        if choice not in ('ours', 'theirs') or self.sider is None:
            return super().resolve_conflict(path, choice, content)
        before, oid = self._version(path, 'worktree'), self._ask('hash-object', '--', str(path))
        try: return super().resolve_conflict(path, choice, content)
        finally: self.sider(self.root/str(path), before, self._version(path, 'worktree'), oid)
    def _drop_side(self, path, choice, stages):
        """Take the side of a modify/delete conflict that deleted the file.

        `git checkout --ours` refuses outright when the stage is not there, and writing `git show
        :2:path` would stage an empty file where a deletion is meant. Taking the file away and
        staging that is what the button says it does.
        """
        if first(m for m, _ in stages.values() if m == '160000'):
            raise GitError(f'{path} is a submodule: resolve it with Git directly')
        self.drop(self.root/str(path))
        self.stage([path])
        remaining = [c['path'] for c in self._changes_uncached() if c['conflicted']]
        return {'path': path, 'choice': choice, 'conflicted': remaining, 'deleted': True,
            'operation': self._operation(),
            'summary': f'{_plural(len(remaining), "file")} still conflicted' if remaining else
                'every conflict is resolved -- commit to finish the merge'}
    def index_entries(self, paths):
        "`update-index --index-info` lines for these paths, unmerged stages and all."
        return [l for l in self.run('ls-files', '-s', '--', *paths).splitlines() if l.strip()]
    def restore_index(self, paths, entries):
        "Put these index entries back, dropping whatever staged over them."
        lines = [f"0 {'0' * 40}\t{p}" for p in paths] + [str(e) for e in entries]
        self._mutate('update-index', '--index-info', input='\n'.join(lines) + '\n')
        return {'paths': [str(p) for p in paths], 'entries': len(entries)}
    def write_worktree(self, path, content):
        target = (self.root/str(path)).resolve()
        if not target.is_relative_to(self.root.resolve()): raise GitError('file is outside the repository')
        if target.exists() and not target.is_file(): raise GitError(f'{path} is not a working-tree file')
        if not target.parent.exists(): raise GitError(f'the parent directory for {path} does not exist')
        self.save(target, content)
        _invalidate(self.root)
    def ignore(self, path, directory=False):
        "Add one repository-relative path to .gitignore without duplicating an existing rule."
        rule = str(path).strip().strip('/') + ('/' if directory else '')
        if not rule or rule.startswith('../') or '/..' in rule: raise GitError('invalid ignore path')
        target = self.root/'.gitignore'
        lines = target.read_text(encoding='utf-8').splitlines() if target.exists() else []
        if rule not in lines:
            self.save(target, '\n'.join(lines + [rule]) + '\n')
            _invalidate(self.root)
        return {'path': str(target), 'rule': rule}
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
