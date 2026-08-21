"Layered settings: defaults, then user, then workspace, then language."

from __future__ import annotations

from ...core.web import fail
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
