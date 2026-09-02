"Which of your packages is installed, where from, and which one just raised. pullup's survey."

from pullup.stack import blame as _blame, checkout_for, frames, installed  # noqa: F401
from pullup.stack import survey as _survey

__all__ = ['FAMILY', 'survey', 'blame', 'frames', 'checkout_for', 'installed']

#: The packages Leela is composed of, which are the ones a failure is worth attributing to.
FAMILY = ['gheasy', 'dockeasy', 'vpseasy', 'cfeasy', 'leela', 'dhrishti', 'nbdev', 'fastship',
          'kavacha', 'kunda', 'pullup']

def survey(names=(), checkouts=()):
    "One row each: installed, version, the resolved copy, and whether a checkout is shadowed."
    return _survey(list(names) or FAMILY, checkouts)

def blame(text, names=(), checkouts=()):
    "Which package raised (the deepest family frame) and where to open it, preferring a checkout."
    return _blame(text, checkouts, list(names) or FAMILY)
