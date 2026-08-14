"Exact text edits: preview first, then apply the approved file contents."

from __future__ import annotations
import re
from dataclasses import dataclass

from fastcore.all import Path

from ..fs.fs import is_texty

__all__ = ['FileEdit', 'replace_plan']

@dataclass
class FileEdit:
    path: str
    before: str
    after: str
    edits: int
    def dict(self):
        return dict(path=self.path, before=self.before, after=self.after, edits=self.edits)

def _pattern(query, regex=False, case=False, word=False):
    if not query: raise ValueError('find text is empty')
    text = query if regex else re.escape(query)
    if word: text = r'\b' + text + r'\b'
    try: return re.compile(text, 0 if case else re.I)
    except re.error as e: raise ValueError(f'invalid regular expression: {e}') from e

def replace_plan(fs, query, replacement, regex=False, case=False, word=False, limit=20000):
    "Changed editable workspace files for one literal or regular-expression replacement."
    pat = _pattern(str(query), bool(regex), bool(case), bool(word))
    repl = str(replacement) if regex else str(replacement).replace('\\', '\\\\')
    rows, skipped = [], []
    for path in fs.walk(limit=limit):
        if path.suffix.lower() == '.ipynb' or not is_texty(path):
            skipped.append(str(path)); continue
        try: before = fs.read(path)
        except Exception: skipped.append(str(path)); continue
        if '\ufffd' in before: skipped.append(str(path)); continue
        try: after, n = pat.subn(repl, before)
        except re.error as e: raise ValueError(f'invalid replacement: {e}') from e
        if n: rows.append(FileEdit(str(path), before, after, n))
    return rows, skipped
