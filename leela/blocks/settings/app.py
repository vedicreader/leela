"""Layered settings: defaults, then user, then workspace, then language.

Every reply reports the *origin* of each effective value, not just the value, because the
question a settings panel actually has to answer is "why is it this" -- and with four
layers, the value alone cannot say.

`Settings` is rebuilt per request rather than cached. It reads files that the user may be
editing in the very editor this serves, and one of them is workspace-scoped, so a cached
instance would go stale exactly when someone is looking at it.
"""

from __future__ import annotations

from ...core.web import fail
from .settings import Settings

__all__ = ['CAPS', 'connect']

CAPS = ('fs',)


def connect(app, ctx):
    rt = app.route

    # Workspace settings belong to the folder that holds them, so this follows the chosen one:
    # with two checkouts open, `.leela/settings.json` was read from and written to the first of
    # them whichever project you were working in.
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
