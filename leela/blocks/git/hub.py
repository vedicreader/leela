"The pull request a branch belongs to, when the github extra is installed."

from __future__ import annotations

from fastcore.all import first
from fastcore.xtras import flexicache, time_policy

from ramabana.git import GitError

__all__ = ['pr_context', 'hub_available']

MISSING = ('Install leela[github] to see the pull request a branch belongs to, whether its '
           'base has moved, and whether its checks are green.')

def hub_available():
    try:
        import gheasy.core  # noqa: F401
        return True
    except ImportError: return False

def _api(root):
    "gheasy owns the token and the client; `GhApi` binds owner and repo, so calls do not repeat them."
    from gheasy.core import _gh_api, _resolve_gh_token
    try: owner, name, api = _gh_api(token=_resolve_gh_token(), path=root)
    except ValueError as e: raise GitError(f'this repository has no GitHub remote ({e})') from e
    return api, owner, name

def _checks(api, sha):
    "Check runs for one commit, as counts and the names that are not green."
    try: runs = api.checks.list_for_ref(sha, per_page=100)['check_runs']
    except Exception: return {}
    bad = [r['name'] for r in runs if r['conclusion'] not in (None, 'success', 'neutral', 'skipped')]
    return {'total': len(runs), 'failing': bad[:12],
            'pending': sum(1 for r in runs if r['status'] != 'completed')}

@flexicache(time_policy(60), maxsize=32)
def pr_context(root, branch):
    "A branch's pull request, its base, how far that base has moved, and how its checks stand."
    if not hub_available(): return {'available': False, 'note': MISSING}
    try:
        api, owner, name = _api(root)
        prs = api.pulls.list(head=f'{owner}:{branch}', state='open', per_page=5)
        pr = first(prs)
        if pr is None: return {'available': True, 'pr': None, 'note': f'no open pull request for {branch}'}
        cmp = api.repos.compare_commits(f"{pr['base']['ref']}...{branch}")
        return {'available': True, 'note': '', 'pr': {
            'number': pr['number'], 'title': pr['title'], 'url': pr['html_url'],
            'base': pr['base']['ref'], 'draft': bool(pr.get('draft')),
            'mergeable_state': pr.get('mergeable_state') or '',
            'behind_base': cmp['behind_by'], 'ahead_of_base': cmp['ahead_by'],
            'checks': _checks(api, pr['head']['sha'])}}
    except Exception as e:
        return {'available': True, 'pr': None, 'note': f'GitHub: {e}'}
