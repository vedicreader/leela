"""GitHub Actions, as something you can look at rather than a folder of YAML.

A workflow file is a graph pretending to be a document. `needs:` is an edge, `if:` is a
guard, and the thing people actually want to know -- *what runs, in what order, and which
of those is red right now* -- is spread across a text file, a browser tab, and a run log.
This module answers those three from one place: the local files parsed into jobs and edges,
the recent runs from GitHub, and the trigger that starts one.

Everything except the reading is [gheasy](https://github.com/vedicreader/gheasy)'s.
Resolving this repository's `owner/name`, the token, an authenticated `GhApi`, the current
branch, the workflow generated from `.gheasy/config.json`, and the rule that decides whether
a key goes up as a secret or a variable -- all of it already exists there and none of it is
re-derived here. Even the YAML instance is gheasy's, so a file Leela reads and a file gheasy
writes are parsed by the same ruamel configuration. What is left in this module is the one
thing gheasy has no reason to own: turning a workflow file that *someone else* wrote into
jobs, edges and rows, because gheasy builds workflows and this has to read them.

gheasy is an optional extra. Without it the panel still lists the files and says what to
install, because a panel that shows nothing until you install something is a panel nobody
installs anything for.

Nothing here writes to GitHub implicitly. Dispatching a run, writing a generated workflow
and pushing a secret are each an explicit call, and `push_env` refuses a key the project's
`env_schema` does not declare -- gheasy's rule, kept, because "everything in .env goes up"
is how a personal token becomes an organisation's problem.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ['Workflows', 'WorkflowError', 'levels']

WORKFLOW_DIR = '.github/workflows'


class WorkflowError(RuntimeError):
    pass


def _gheasy():
    try:
        import gheasy.core as core
        return core
    except ImportError as e:
        raise WorkflowError('this needs gheasy: pip install "leela[github]"') from e


def _yaml():
    "gheasy's ruamel instance, so Leela reads what gheasy writes with the same parser."
    try:
        from gheasy.workflow import _yaml_instance
        return _yaml_instance()
    except ImportError as e:
        raise WorkflowError('reading workflow files needs gheasy: pip install "leela[github]"') from e


def levels(jobs):
    """Jobs arranged into the rows a reader sees: everything that can start, then what follows.

    A longest-path layering rather than a plain topological sort, so a job sits below the
    *last* thing it waits for instead of floating up beside its earliest dependency. Any job
    left over is in a `needs` cycle -- GitHub would reject the file, and drawing it in a
    final row is more useful than refusing to draw anything.
    """
    known = {j['id'] for j in jobs}
    depth, pending = {}, list(jobs)
    for _ in range(len(jobs) + 1):
        progressed = False
        for job in list(pending):
            needs = [n for n in job['needs'] if n in known]
            if all(n in depth for n in needs):
                depth[job['id']] = 1 + max((depth[n] for n in needs), default=-1)
                pending.remove(job)
                progressed = True
        if not pending or not progressed:
            break
    cycle = max(depth.values(), default=-1) + 1
    for job in pending:
        depth[job['id']] = cycle
    rows = {}
    for job in jobs:
        rows.setdefault(depth[job['id']], []).append(job['id'])
    return [rows[k] for k in sorted(rows)]


class Workflows:
    "Every workflow in one repository: the files, the graph, the runs, and the secrets."

    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    # -- local files -----------------------------------------------------------
    @property
    def dir(self): return self.root/WORKFLOW_DIR

    def files(self):
        try: found = sorted(p for p in self.dir.iterdir() if p.suffix in ('.yml', '.yaml'))
        except OSError: return []
        return found

    @staticmethod
    def _triggers(on):
        "`on:` in any of its three shapes -- a string, a list, or a mapping with filters."
        if isinstance(on, str): return [{'event': on, 'detail': ''}]
        if isinstance(on, list): return [{'event': str(x), 'detail': ''} for x in on]
        rows = []
        for event, spec in (on or {}).items():
            detail = ''
            if isinstance(spec, dict):
                parts = [f'{k}: {", ".join(map(str, v))}' if isinstance(v, list) else f'{k}: {v}'
                         for k, v in spec.items() if k in ('branches', 'tags', 'paths', 'types', 'cron')]
                detail = ' · '.join(parts)
            elif isinstance(spec, list):
                detail = ', '.join(map(str, spec))
            rows.append({'event': str(event), 'detail': detail})
        return rows

    @staticmethod
    def _steps(raw):
        rows = []
        for step in raw or ():
            if not isinstance(step, dict): continue
            uses, run = str(step.get('uses') or ''), str(step.get('run') or '')
            label = str(step.get('name') or '') or uses or (run.splitlines()[0] if run else '') or 'step'
            rows.append({'name': label, 'uses': uses, 'run': run, 'if': str(step.get('if') or '')})
        return rows

    def parse(self, path):
        "One workflow file as jobs and edges, or as the error that stopped it being read."
        path = Path(path)
        row = {'file': path.name, 'path': str(path), 'name': path.stem, 'triggers': [],
               'jobs': [], 'levels': [], 'dispatchable': False, 'error': ''}
        try:
            doc = _yaml().load(path.read_text(encoding='utf-8', errors='replace')) or {}
        except (OSError, WorkflowError) as e:
            row['error'] = str(e)
            return row
        except Exception as e:                                  # a YAML error names the line
            row['error'] = f'{type(e).__name__}: {e}'
            return row
        if not isinstance(doc, dict):
            row['error'] = 'this file is not a workflow'
            return row
        # `on:` is the YAML 1.1 boolean `True` once parsed -- the single sharpest edge in
        # reading Actions files, and the reason a naive `doc['on']` finds nothing.
        on = doc.get('on', doc.get(True, {}))
        row['name'] = str(doc.get('name') or path.stem)
        row['triggers'] = self._triggers(on)
        row['dispatchable'] = any(t['event'] == 'workflow_dispatch' for t in row['triggers'])
        jobs = doc.get('jobs') or {}
        for job_id, job in jobs.items() if isinstance(jobs, dict) else ():
            job = job if isinstance(job, dict) else {}
            needs = job.get('needs') or []
            needs = [needs] if isinstance(needs, str) else [str(n) for n in needs]
            row['jobs'].append({
                'id': str(job_id), 'name': str(job.get('name') or job_id), 'needs': needs,
                'runs_on': str(job.get('runs-on') or job.get('runs_on') or ''),
                'if': str(job.get('if') or ''), 'uses': str(job.get('uses') or ''),
                'environment': str(job.get('environment') or '') if not isinstance(job.get('environment'), dict)
                               else str((job.get('environment') or {}).get('name') or ''),
                'steps': self._steps(job.get('steps')),
            })
        row['levels'] = levels(row['jobs'])
        return row

    def parsed(self):
        return [self.parse(p) for p in self.files()]

    # -- the GitHub side -------------------------------------------------------
    def repo(self):
        "`owner/name` from the origin remote, or `''` when there is no GitHub remote."
        try:
            core = _gheasy()
            owner, name = core._get_repo_slug(str(self.root))
            return f'{owner}/{name}'
        except Exception:
            return ''

    def _api(self):
        core = _gheasy()
        token = core._resolve_gh_token()
        if not token:
            raise WorkflowError('set GITHUB_TOKEN — add it in Environment below, or export it before starting Leela')
        owner, name, api = core._gh_api(token, str(self.root))
        return owner, name, api

    def status(self):
        """Whether the GitHub half is usable, and if not, exactly which part is missing.

        Three different failures -- no gheasy, no remote, no token -- each need a different
        thing done about them, so the panel is told which one it is rather than being handed
        a blank list.
        """
        row = {'gheasy': True, 'dockeasy': _installed('dockeasy'), 'repo': '', 'token': False,
               'gh_cli': bool(_which('gh')), 'why': ''}
        try: core = _gheasy()
        except WorkflowError as e:
            return row | {'gheasy': False, 'why': str(e)}
        row['repo'] = self.repo()
        row['token'] = bool(core._resolve_gh_token())
        if not row['repo']: row['why'] = 'no GitHub remote on this repository'
        elif not row['token']: row['why'] = 'no GITHUB_TOKEN'
        return row

    def runs(self, limit=20, workflow=''):
        "Recent runs, newest first. `workflow` is a file name, matching what `files` returns."
        owner, name, api = self._api()
        kw = {'per_page': max(1, min(int(limit), 100))}
        raw = (api.actions.list_workflow_runs(workflow_id=workflow, **kw) if workflow
               else api.actions.list_workflow_runs_for_repo(**kw))
        rows = []
        for run in (raw.get('workflow_runs') or []):
            head = run.get('head_commit') if isinstance(run.get('head_commit'), dict) else {}
            title = str(run.get('display_title') or (head.get('message') or '')).split('\n')[0]
            rows.append({'id': run.get('id'), 'name': run.get('name') or '', 'file': _wf_file(run),
                         'number': run.get('run_number'), 'status': run.get('status') or '',
                         'conclusion': run.get('conclusion') or '', 'branch': run.get('head_branch') or '',
                         'event': run.get('event') or '', 'created_at': run.get('created_at') or '',
                         'updated_at': run.get('updated_at') or '', 'url': run.get('html_url') or '',
                         'actor': ((run.get('actor') or {}).get('login') or ''), 'title': title})
        return rows

    def run_jobs(self, run_id):
        "The jobs of one run, so a red workflow says which box is red."
        owner, name, api = self._api()
        raw = api.actions.list_jobs_for_workflow_run(run_id=int(run_id), per_page=100)
        return [{'id': j.get('id'), 'name': j.get('name') or '', 'status': j.get('status') or '',
                 'conclusion': j.get('conclusion') or '', 'url': j.get('html_url') or '',
                 'started_at': j.get('started_at') or '', 'completed_at': j.get('completed_at') or '',
                 'steps': [{'name': s.get('name') or '', 'status': s.get('status') or '',
                            'conclusion': s.get('conclusion') or '', 'number': s.get('number')}
                           for s in (j.get('steps') or [])]}
                for j in (raw.get('jobs') or [])]

    def dispatch(self, workflow, ref='', inputs=None):
        "Start a run. The workflow must declare `workflow_dispatch`; GitHub refuses otherwise."
        owner, name, api = self._api()
        if not str(workflow).strip():
            raise WorkflowError('choose a workflow to run')
        ref = str(ref or '').strip() or _gheasy()._git_branch(str(self.root))
        api.actions.create_workflow_dispatch(workflow_id=str(workflow), ref=ref, inputs=dict(inputs or {}))
        return {'workflow': str(workflow), 'ref': ref}

    def cancel(self, run_id):
        owner, name, api = self._api()
        api.actions.cancel_workflow_run(run_id=int(run_id))
        return {'cancelled': int(run_id)}

    # -- gheasy's generated workflow -------------------------------------------
    def config(self):
        "The project's `.gheasy/config.json`, or None when gheasy has not been set up here."
        try: core = _gheasy()
        except WorkflowError: return None
        if not core.cfg_path(str(self.root)).exists(): return None
        return core.GheasyConfig.load(str(self.root)).to_dict()

    def generate(self):
        "The workflow gheasy would write for this project, as text, without writing it."
        core = _gheasy()
        if not core.cfg_path(str(self.root)).exists():
            raise WorkflowError('this project has no .gheasy/config.json to generate from')
        return core.mk_workflow(core.GheasyConfig.load(str(self.root)))

    def write_generated(self):
        """Write it, with gheasy doing the writing.

        `gh_workflow` is the same call the `gheasy` CLI makes, so the file this panel
        produces is byte-for-byte the one the command line produces. Without a token it
        writes locally and stops there, which is what a button in an editor should do --
        committing and pushing stay the user's.
        """
        core = _gheasy()
        if not core.cfg_path(str(self.root)).exists():
            raise WorkflowError('this project has no .gheasy/config.json to generate from')
        core.gh_workflow(path=str(self.root))
        return {'path': str(self.dir/'gheasy.yml')}

    # -- what the docker job would build ---------------------------------------
    def docker(self):
        """What dockeasy makes of this project, and whether it already has a Dockerfile.

        gheasy's `docker_job` builds *something*, and a workflow whose docker job points at
        a file that is not there is the failure this answers before it happens. The
        detection and the Dockerfile are both dockeasy's -- `detect_app` reads the project
        and returns the file it would write.
        """
        row = {'dockerfile': (self.root/'Dockerfile').exists(), 'base': '', 'preview': '', 'why': ''}
        try:
            from dockeasy.core import detect_app
        except ImportError:
            return row | {'why': 'detecting the build needs dockeasy: pip install "leela[github]"'}
        try:
            text = str(detect_app(str(self.root)))
        except Exception as e:
            return row | {'why': f'{type(e).__name__}: {e}'}
        row['preview'] = text
        row['base'] = next((l for l in text.splitlines() if l.startswith('FROM ')), '')
        return row

    def write_dockerfile(self):
        "Write the Dockerfile dockeasy detected. Refuses to overwrite one that already exists."
        try:
            from dockeasy.core import detect_app
        except ImportError as e:
            raise WorkflowError('writing a Dockerfile needs dockeasy: pip install "leela[github]"') from e
        path = self.root/'Dockerfile'
        if path.exists():
            raise WorkflowError('this project already has a Dockerfile')
        text = str(detect_app(str(self.root)))
        path.write_text(text if text.endswith('\n') else text + '\n', encoding='utf-8')
        return {'path': str(path)}

    # -- secrets and variables -------------------------------------------------
    def schema(self):
        "gheasy's `env_schema`: `{KEY: None}` is a secret, `{KEY: default}` is a variable."
        cfg = self.config() or {}
        return dict(cfg.get('env_schema') or {})

    def remote_env(self):
        "What GitHub already has. Secret *values* are not readable, by GitHub's design."
        owner, name, api = self._api()
        secrets = [{'name': s.get('name'), 'updated_at': s.get('updated_at') or ''}
                   for s in (api.actions.list_repo_secrets(per_page=100).get('secrets') or [])]
        variables = [{'name': v.get('name'), 'value': v.get('value') or '', 'updated_at': v.get('updated_at') or ''}
                     for v in (api.actions.list_repo_variables(per_page=100).get('variables') or [])]
        return {'secrets': secrets, 'variables': variables}

    def push_env(self, values, keys=(), dry_run=False):
        """Send values up as secrets or variables, one result per key.

        gheasy's `gh_push_env` decides which of the two each key is, from the project's
        schema, and skips anything undeclared. That rule is kept and made visible: an
        undeclared key comes back as `skipped`, not as a silent no-op, because the reason
        nothing happened is the thing worth knowing.
        """
        core = _gheasy()
        if not _which('gh'):
            raise WorkflowError('pushing secrets uses the GitHub CLI: install `gh` and run `gh auth login`')
        schema = self.schema()
        if not schema:
            raise WorkflowError('declare env_schema in .gheasy/config.json first — '
                                'it is what says which keys are secrets and which are variables')
        wanted = [k for k in (keys or values.keys())]
        rows = []
        for key in wanted:
            value = values.get(key, '')
            if key not in schema:
                rows.append({'key': key, 'ok': True, 'skipped': 'not in env_schema', 'target': ''})
                continue
            target = 'secret' if schema[key] is None else 'variable'
            if not value:
                rows.append({'key': key, 'ok': True, 'skipped': 'no value set', 'target': target})
                continue
            try:
                core.gh_push_env({key: value}, dry_run=dry_run, path=str(self.root))
                rows.append({'key': key, 'ok': True, 'skipped': '', 'target': target})
            except Exception as e:
                rows.append({'key': key, 'ok': False, 'error': f'{type(e).__name__}: {e}', 'target': target})
        return rows


def _which(name):
    from shutil import which
    return which(name)


def _installed(name):
    from importlib.util import find_spec
    try: return find_spec(name) is not None
    except (ImportError, ValueError): return False


def _wf_file(run):
    "The file a run came from; GitHub reports it as a path on the workflow, not a name."
    path = str((run.get('path') or ''))
    return re.sub(r'^\.github/workflows/', '', path)
