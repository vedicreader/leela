"GitHub Actions, as something you can look at rather than a folder of YAML."

from __future__ import annotations

import re
from shutil import which

from fastcore.all import Path, first

from ..stack.packages import installed

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
    "Jobs arranged into rows: everything that can start, then what follows, by longest path."
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
        if not pending or not progressed: break
    cycle = max(depth.values(), default=-1) + 1
    for job in pending: depth[job['id']] = cycle
    rows = {}
    for job in jobs: rows.setdefault(depth[job['id']], []).append(job['id'])
    return [rows[k] for k in sorted(rows)]

class Workflows:
    "Every workflow in one repository: the files, the graph, the runs, and the secrets."
    def __init__(self, root): self.root = Path(root).expanduser().resolve()
    @property
    def dir(self): return self.root/WORKFLOW_DIR
    def files(self):
        try: return sorted(p for p in self.dir.iterdir() if p.suffix in ('.yml', '.yaml'))
        except OSError: return []
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
            elif isinstance(spec, list): detail = ', '.join(map(str, spec))
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
    @classmethod
    def _job(cls, job_id, job):
        "One entry of `jobs:`, with `needs` in either of its shapes and `environment` in either of its."
        job = job if isinstance(job, dict) else {}
        needs = job.get('needs') or []
        env = job.get('environment')
        return {'id': str(job_id), 'name': str(job.get('name') or job_id),
            'needs': [needs] if isinstance(needs, str) else [str(n) for n in needs],
            'runs_on': str(job.get('runs-on') or job.get('runs_on') or ''),
            'if': str(job.get('if') or ''), 'uses': str(job.get('uses') or ''),
            'environment': str(env.get('name') or '') if isinstance(env, dict) else str(env or ''),
            'steps': cls._steps(job.get('steps'))}
    def parse(self, path):
        "One workflow file as jobs and edges, or as the error that stopped it being read."
        path = Path(path)
        row = {'file': path.name, 'path': str(path), 'name': path.stem, 'triggers': [],
            'jobs': [], 'levels': [], 'dispatchable': False, 'error': ''}
        try: doc = _yaml().load(path.read_text(encoding='utf-8', errors='replace')) or {}
        except (OSError, WorkflowError) as e: return row | {'error': str(e)}
        except Exception as e:
            return row | {'error': f'{type(e).__name__}: {e}'}
        if not isinstance(doc, dict): return row | {'error': 'this file is not a workflow'}
        on = doc.get('on', doc.get(True, {}))
        row['name'] = str(doc.get('name') or path.stem)
        row['triggers'] = self._triggers(on)
        row['dispatchable'] = any(t['event'] == 'workflow_dispatch' for t in row['triggers'])
        jobs = doc.get('jobs') or {}
        row['jobs'] = [self._job(k, v) for k, v in (jobs.items() if isinstance(jobs, dict) else ())]
        row['levels'] = levels(row['jobs'])
        return row
    def parsed(self): return [self.parse(p) for p in self.files()]
    def repo(self):
        "`owner/name` from the origin remote, or `''` when there is no GitHub remote."
        try:
            core = _gheasy()
            owner, name = core._get_repo_slug(str(self.root))
            return f'{owner}/{name}'
        except Exception: return ''
    def _api(self):
        core = _gheasy()
        token = core._resolve_gh_token()
        if not token:
            raise WorkflowError('set GITHUB_TOKEN — add it in Environment below, or export it before starting Leela')
        owner, name, api = core._gh_api(token, str(self.root))
        return owner, name, _sync_api(core, owner, name, token, api)
    def status(self):
        "Whether the GitHub half is usable, and if not, which of gheasy, remote or token is missing."
        row = {'gheasy': True, 'dockeasy': installed('dockeasy'), 'repo': '', 'token': False,
            'gh_cli': bool(which('gh')), 'gh_auth': _gh_authed(), 'why': ''}
        try: core = _gheasy()
        except WorkflowError as e: return row | {'gheasy': False, 'why': str(e)}
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
        return [_run_row(run) for run in (raw.get('workflow_runs') or [])]
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
        if not str(workflow).strip(): raise WorkflowError('choose a workflow to run')
        ref = str(ref or '').strip() or _gheasy()._git_branch(str(self.root))
        api.actions.create_workflow_dispatch(workflow_id=str(workflow), ref=ref, inputs=dict(inputs or {}))
        return {'workflow': str(workflow), 'ref': ref}
    def cancel(self, run_id):
        owner, name, api = self._api()
        api.actions.cancel_workflow_run(run_id=int(run_id))
        return {'cancelled': int(run_id)}
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
        "Write it through gheasy's `gh_workflow`, the same call the CLI makes. Never commits."
        core = _gheasy()
        if not core.cfg_path(str(self.root)).exists():
            raise WorkflowError('this project has no .gheasy/config.json to generate from')
        core.gh_workflow(path=str(self.root))
        return {'path': str(self.dir/'gheasy.yml')}
    def detect(self):
        "What this project is, from the files that say so and from dockeasy's `detect_app`."
        root = self.root
        has = lambda *names: any((root/n).exists() for n in names)
        text = ''.join(_read(root/n) for n in ('pyproject.toml', 'requirements.txt')).lower()
        from ..pipelines.releases import nbdev_project
        row = {
            'python': has('pyproject.toml', 'requirements.txt', 'setup.py'),
            'node': has('package.json'), 'rust': has('Cargo.toml'), 'go': has('go.mod'),
            'nbdev': nbdev_project(root), 'docker': has('Dockerfile'),
            'compose': has('docker-compose.yml', 'compose.yml'),
            'deploy_script': has('deploy.py'), 'pages': has('_quarto.yml', 'nbs/_quarto.yml', 'docs'),
            'web': any(k in text for k in ('python-fasthtml', 'fastapi', 'django', 'flask')),
            'vps': any(k in text for k in ('vpseasy', 'cfeasy', 'hcloud')),
            'publish': any(k in text for k in ('hatchling', 'setuptools', 'flit')),
            'build': '', 'build_why': '',
        }
        try:
            from dockeasy.core import detect_app
            row['build'] = _from_line(detect_app(str(root)))
        except ImportError: row['build_why'] = 'install dockeasy to detect the build'
        except Exception as e: row['build_why'] = f'{type(e).__name__}: {e}'
        return row
    def catalogue(self):
        "The workflows on offer, every one of them gheasy's, each marked with whether this project wants."
        d = self.detect()
        present = {p.name for p in self.files()}
        rows = [
            {'id': 'ci', 'name': 'Python CI', 'file': 'ci.yml',
                'doc': 'ruff, then pytest, on push and pull request — uv for both.',
                'want': d['python'] and not d['nbdev'], 'why': 'a Python project'},
            {'id': 'nbdev', 'name': 'nbdev CI', 'file': 'ci.yml',
                'doc': 'nbdev_test and a clean-notebook check, which is what breaks in an nbdev repo.',
                'want': d['nbdev'], 'why': 'nbdev project'},
            {'id': 'pypi', 'name': 'PyPI on release', 'file': 'publish.yml',
                'doc': 'Build and publish through PyPI trusted publishing when a release is created.',
                'want': d['publish'], 'why': 'this project builds a distribution'},
            {'id': 'docker', 'name': 'Docker image', 'file': 'docker.yml',
                'doc': 'Build and push to GHCR with semver and sha tags from docker/metadata-action.',
                'want': d['docker'] or bool(d['build']), 'why': 'there is an image to build'},
            {'id': 'deploy', 'name': 'Deploy to a VPS', 'file': 'deploy.yml',
                'doc': 'Everything in env_schema as secrets and variables, the deploy key, then '
                'your deploy script — the shape lego uses.',
                'want': d['deploy_script'] or d['vps'], 'why': 'a deploy script or a VPS dependency'},
            {'id': 'pages', 'name': 'GitHub Pages', 'file': 'pages.yml',
                'doc': 'Build a static site and publish it to Pages.',
                'want': d['pages'] and d['node'], 'why': 'a static site with a node build'},
        ]
        for row in rows:
            row['present'] = row['file'] in present
            row['recommended'] = bool(row['want'])
            row['why'] = row['why'] if row['want'] else ''
        return {'detect': d, 'workflows': rows}
    def _build(self, choice):
        "One catalogue entry as a gheasy `WorkflowDoc`. Nothing here writes anything."
        from gheasy.workflow import Workflow, docker_build_push, pages_deploy, uv_ci
        from .wfbuild import nbdev_job
        cfg = self.config() or {}
        app = str(cfg.get('app') or self.root.name)
        if choice == 'ci': return uv_ci(f'{app} CI')
        if choice == 'nbdev':
            wfb = Workflow(f'{app} CI')
            wfb.on.push(branches=['main']).pull_request(branches=['main'])
            nbdev_job(wfb)
            return wfb.build()
        if choice == 'pypi':
            wfb = Workflow(f'{app} publish')
            wfb.on.release(types=['published'])
            wfb.uv_pypi_job(needs=None)
            return wfb.build()
        if choice == 'docker': return docker_build_push(f'{app} image')
        if choice == 'pages': return pages_deploy(f'{app} pages')
        if choice == 'deploy': return self._deploy_workflow(app, cfg)
        raise WorkflowError(f'unknown workflow: {choice}')
    def _deploy_workflow(self, app, cfg):
        "The deploy workflow, with the project's own `env_schema` rendered into its `env:` block."
        from gheasy.workflow import Workflow
        from .wfbuild import deploy_job
        wfb = Workflow(f'{app} deploy')
        wfb.on.push(branches=['main'])
        deploy_job(wfb, 'deploy', {}, cfg.get('env_schema') or {}, app)
        return wfb.build()
    def build(self, spec):
        "A spec from the builder as YAML, composed entirely with gheasy's DSL."
        _gheasy()
        from .wfbuild import compose
        cfg = self.config() or {}
        return compose(spec, schema=self.schema(), app=str(cfg.get('app') or self.root.name))
    def write_spec(self, spec, file=''):
        "Write a built workflow, and keep the spec beside it — reading YAML back into one is lossy."
        _gheasy()
        from .wfbuild import save_spec
        name = _wf_name(str(file or spec.get('file') or f"{spec.get('name') or 'ci'}.yml"))
        text = self.build(spec)
        path = self.dir/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        save_spec(self.root, name, {**spec, 'file': name})
        return {'path': str(path), 'file': name}
    def spec(self, file):
        "The spec a workflow was built from, plus whether the file on disk still matches it."
        from .wfbuild import load_spec
        spec = load_spec(self.root, file)
        if spec is None: return None
        try: current = (self.dir/file).read_text(encoding='utf-8')
        except OSError: current = ''
        try: stale = bool(current) and current.strip() != self.build(spec).strip()
        except WorkflowError: stale = False
        return {'spec': spec, 'stale': stale}
    def preview(self, choice):
        "The YAML a catalogue entry would write, without writing it."
        _gheasy()
        return self._build(str(choice)).to_yaml()
    def add(self, choice, file=''):
        "Write one catalogue entry into `.github/workflows`. Never overwrites silently."
        _gheasy()
        rows = {r['id']: r for r in self.catalogue()['workflows']}
        row = rows.get(str(choice))
        if row is None: raise WorkflowError(f'unknown workflow: {choice}')
        name = _wf_name(str(file or row['file']))
        path = self.dir/name
        if path.exists(): raise WorkflowError(f'{name} already exists — delete or rename it first')
        path.parent.mkdir(parents=True, exist_ok=True)
        self._build(row['id']).save(path)
        return {'path': str(path), 'workflow': row['id']}
    def docker(self):
        "What dockeasy makes of this project, and whether it already has a Dockerfile."
        row = {'dockerfile': (self.root/'Dockerfile').exists(), 'base': '', 'preview': '', 'why': ''}
        try: from dockeasy.core import detect_app
        except ImportError:
            return row | {'why': 'detecting the build needs dockeasy: pip install "leela[github]"'}
        try: text = str(detect_app(str(self.root)))
        except Exception as e: return row | {'why': f'{type(e).__name__}: {e}'}
        return row | {'preview': text, 'base': _from_line(text)}
    def write_dockerfile(self):
        "Write the Dockerfile dockeasy detected. Refuses to overwrite one that already exists."
        try: from dockeasy.core import detect_app
        except ImportError as e:
            raise WorkflowError('writing a Dockerfile needs dockeasy: pip install "leela[github]"') from e
        path = self.root/'Dockerfile'
        if path.exists(): raise WorkflowError('this project already has a Dockerfile')
        text = str(detect_app(str(self.root)))
        path.write_text(text if text.endswith('\n') else text + '\n', encoding='utf-8')
        return {'path': str(path)}
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
        "Send values up through gheasy's `gh_push_env`, one result per key; undeclared keys are skipped."
        core = _gheasy()
        if not which('gh'):
            raise WorkflowError('pushing secrets uses the GitHub CLI: install `gh` and run `gh auth login`')
        schema = self.schema()
        if not schema:
            raise WorkflowError('declare env_schema in .gheasy/config.json first — '
                'it is what says which keys are secrets and which are variables')
        rows = []
        wanted = keys or values
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

def _sync_api(core, owner, name, token, api):
    "gheasy's client rebuilt synchronous: ghapi 2 is async by default and nothing here awaits."
    from inspect import signature
    GhApi = getattr(core, 'GhApi', None)
    if GhApi is None or 'sync' not in signature(GhApi).parameters: return api
    return GhApi(owner=owner, repo=name, token=token, sync=True)

def _gh_authed():
    "Is the GitHub CLI logged in? `gh auth status` is the only thing that knows."
    if not which('gh'): return False
    import subprocess
    try:
        return subprocess.run(['gh', 'auth', 'status'], capture_output=True, timeout=8).returncode == 0
    except (OSError, subprocess.SubprocessError): return False

def _run_row(run):
    "One run as the panel shows it; the title falls back to the head commit's first line."
    head = run.get('head_commit') if isinstance(run.get('head_commit'), dict) else {}
    return {'id': run.get('id'), 'name': run.get('name') or '', 'file': _wf_file(run),
        'number': run.get('run_number'), 'status': run.get('status') or '',
        'conclusion': run.get('conclusion') or '', 'branch': run.get('head_branch') or '',
        'event': run.get('event') or '', 'created_at': run.get('created_at') or '',
        'updated_at': run.get('updated_at') or '', 'url': run.get('html_url') or '',
        'actor': ((run.get('actor') or {}).get('login') or ''),
        'title': str(run.get('display_title') or (head.get('message') or '')).split('\n')[0]}

def _read(path):
    "A file's text, or `''` when it is not there -- what a detector wants of a missing file."
    try: return Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError: return ''

def _wf_file(run):
    "The file a run came from; GitHub reports it as a path on the workflow, not a name."
    return re.sub(r'^\.github/workflows/', '', run.get('path') or '')

def _from_line(text):
    "The `FROM` line of a Dockerfile, which is what a panel shows of a detected build."
    return first(str(text).splitlines(), lambda l: l.startswith('FROM ')) or ''

def _wf_name(name):
    "A workflow file name, or the error that says why it is not one -- no directories, no other."
    if '/' in name or not name.endswith(('.yml', '.yaml')):
        raise WorkflowError(f'not a workflow file name: {name}')
    return name
