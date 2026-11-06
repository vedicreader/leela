"Layered settings: defaults, then user, then workspace, then language."

from __future__ import annotations

from ...core.web import fail, off_loop
from .settings import Settings

__all__ = ['CAPS', 'connect']

CAPS = ()

def connect(app, ctx):
    rt = app.route
    def _settings(): return Settings(ctx.session.project_root)
    @rt('/settings')
    def settings_get(language: str = ''):
        "Effective defaults + user + workspace + language values and their origins."
        return _settings().describe(language)
    @rt('/settings/save')
    async def settings_save(req):
        d = await req.json()
        try:
            return {'ok': True, **_settings().save(d.get('scope', 'user'), d.get('section', 'editor'),
                                                    d.get('values') or {}, d.get('language') or '')}
        except Exception as e: return fail(e)
    @rt('/settings/env')
    def settings_env():
        "Names Leela exports and names it found, never the value of a secret."
        from ...core.envs import env_rows, env_file
        return {'ok': True, 'entries': env_rows(), 'path': str(env_file()),
                'note': 'A kernel or terminal already running keeps the environment it started with.'}
    @rt('/settings/env/save')
    async def settings_env_save(req):
        "Set one name for Leela to export, over whatever the shell said."
        from ...core.envs import set_env, env_rows
        d = await req.json()
        try: return {'ok': True, **await off_loop(set_env, d.get('key'), d.get('value')),
                     'entries': env_rows()}
        except Exception as e: return fail(e)
    @rt('/settings/env/remove')
    async def settings_env_remove(req):
        "Forget one name Leela stored. What the shell exports is the shell's."
        from ...core.envs import unset_env, env_rows
        d = await req.json()
        try: return {'ok': True, **await off_loop(unset_env, d.get('key')), 'entries': env_rows()}
        except Exception as e: return fail(e)
    @rt('/settings/reset')
    async def settings_reset(req):
        d = await req.json()
        try:
            return {'ok': True, **_settings().reset(d.get('scope', 'user'), d.get('section'),
                                                     d.get('language') or '')}
        except Exception as e: return fail(e)
    @rt('/backups')
    def backups_list():
        "Every dated copy, what it holds, and the cadence taking them."
        from ...core.backups import backup_settings, backups, backup_dir, CADENCES, ENTRIES
        held = backup_settings()
        return {'ok': True, 'cadence': held['cadence'], 'cadences': sorted(CADENCES),
                'keep': held['keep'], 'ages': list(held['ages']), 'include': list(held['include']),
                'entries': [{'name': n, 'label': l, 'chosen': n in held['include']}
                            for n, l in ENTRIES.items()],
                'dir': str(backup_dir()), 'backups': list(reversed(backups()))}
    @rt('/backups/run')
    async def backups_run(req):
        "Take one now, whatever the cadence says."
        try: d = await req.json()
        except Exception: d = {}
        from ...core.backups import backup_settings, run_backup
        held = backup_settings()
        out = await off_loop(run_backup, None, str(d.get('reason') or 'asked for'),
                              held['ages'], held['keep'], False, held['include'])
        if not out['ok'] and out['problem']: return fail(out['problem'])
        return {**out, 'cadence': held['cadence']}
    @rt('/backups/restore')
    async def backups_restore(req):
        "Put one back. A restore writes over live state, so a copy of what it replaces is taken first."
        d = await req.json()
        name = str(d.get('name') or '')
        if not name: return fail('name the backup to restore')
        from ...core.backups import restore
        try: out = await off_loop(restore, name, None, d.get('only') or None, bool(d.get('dry_run')))
        except FileNotFoundError as e: return fail(e, 404)
        except Exception as e: return fail(e)
        return {'ok': True, **out, 'note': 'reload the window to read the restored state'}
    @rt('/update')
    async def update_offer():
        "Whether a newer Leela is out, and whether this app can install it."
        from ...core.update import offer
        return {'ok': True, **await off_loop(offer)}
    @rt('/update/install')
    def update_install():
        "Start installing the newer release in the background."
        from ...core.update import upgrade
        return {'ok': True, **upgrade()}
    @rt('/update/status')
    def update_status():
        from ...core.update import upgrade_status
        return {'ok': True, **upgrade_status()}
    @rt('/update/restart')
    def update_restart():
        "Quit and open the installed app, once an upgrade finished."
        from ...core.update import restart, upgrade_status
        if upgrade_status()['state'] != 'done': return fail('no finished update to restart into')
        return {'ok': restart()}
