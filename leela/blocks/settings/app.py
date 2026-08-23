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
