"Top-level `const`, `let`, `var`, `function` and `class` names of a JS source, found by a small tokenizer: no parser is installed."
import re

_ID = re.compile(r'[A-Za-z_$][\w$]*')
_NUM = re.compile(r'\d[\w.]*')
_PUNCT = ('>>>=', '...', '===', '!==', '**=', '<<=', '>>=', '>>>', '&&=', '||=', '??=', '=>', '==', '!=', '<=', '>=', '&&', '||', '??', '?.', '++', '--', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<', '>>', '**')
_NOREGEX = {')', ']', '}', 'id', 'num', 'str', 'tpl'}
_KW_REGEX = {'return', 'typeof', 'case', 'in', 'of', 'instanceof', 'new', 'delete', 'void', 'throw', 'else', 'do', 'yield', 'await'}
_OPEN, _CLOSE = {'(': ')', '[': ']', '{': '}'}, {')', ']', '}'}

def tokens(s):
    "(kind, text, line, nl) for each token of `s`; `nl` is True when a line break precedes it."
    i, n, line, nl, out, stk = 0, len(s), 1, False, [], []
    def add(k, t, ln): out.append((k, t, ln, nl))
    def tpl(i, ln):
        "Read template text from `i` to the closing backtick or the next `${`; return the new index, and whether `${` opened."
        nonlocal line
        while i < n:
            c = s[i]
            if c == '\\': i += 2; continue
            if c == '\n': line += 1
            if c == '`': return i + 1, False
            if c == '$' and s[i+1:i+2] == '{': return i + 2, True
            i += 1
        return i, False
    while i < n:
        c = s[i]
        if c == '\n': line += 1; nl = True; i += 1; continue
        if c in ' \t\r\f\v ﻿': i += 1; continue
        if s.startswith('//', i):
            j = s.find('\n', i); i = n if j < 0 else j; continue
        if s.startswith('/*', i):
            j = s.find('*/', i + 2); j = n if j < 0 else j + 2
            if '\n' in s[i:j]: nl = True
            line += s.count('\n', i, j); i = j; continue
        ln = line
        if c in '"\'':
            j = i + 1
            while j < n and s[j] != c and s[j] != '\n': j += 2 if s[j] == '\\' else 1
            add('str', s[i:j+1], ln); i = j + 1
        elif c == '`':
            i, op = tpl(i + 1, ln); add('tpl', '`', ln)
            if op: stk.append('T'); add('p', '${', ln)
        elif c == '}' and stk and stk[-1] == 'T':
            stk.pop(); add('p', '}', ln); i, op = tpl(i + 1, ln); add('tpl', '`', line)
            if op: stk.append('T'); add('p', '${', line)
        elif _ID.match(s, i):
            m = _ID.match(s, i); add('id', m.group(), ln); i = m.end()
        elif c.isdigit() or (c == '.' and s[i+1:i+2].isdigit()):
            m = _NUM.match(s, i) or re.compile(r'\.\d[\w]*').match(s, i); add('num', m.group(), ln); i = m.end()
        elif c == '/' and _regex_ok(out):
            j, cls = i + 1, False
            while j < n and s[j] != '\n':
                if s[j] == '\\': j += 2; continue
                if s[j] == '[': cls = True
                elif s[j] == ']': cls = False
                elif s[j] == '/' and not cls: break
                j += 1
            m = _ID.match(s, j + 1); j = m.end() if m else j + 1
            add('re', s[i:j], ln); i = j
        else:
            p = next((p for p in _PUNCT if s.startswith(p, i)), c)
            if p in _OPEN: stk.append(p)
            elif p in _CLOSE and stk: stk.pop()
            add('p', p, ln); i += len(p)
        nl = False
    return out

def _regex_ok(out):
    if not out: return True
    k, t = out[-1][:2]
    if k == 'id': return t in _KW_REGEX
    return not (k in _NOREGEX or (k == 'p' and t in _CLOSE))

_STMT_END = {None, ';', '}', 'export', 'default', 'async'}
_NOCONT = {'in', 'of', 'instanceof'}

def _pattern(t, i, found):
    "Binding names of the pattern starting at `t[i]`; return the index after it."
    k, x = t[i][:2]
    if k == 'id': found.append((x, t[i][2])); return i + 1
    if x in '[{' and k == 'p':
        close = ']' if x == '[' else '}'; i += 1
        while i < len(t) and t[i][1] != close:
            if t[i][1] == ',': i += 1; continue
            if t[i][1] == '...': i += 1
            if x == '{' and t[i][0] in ('id', 'str', 'num') and i + 1 < len(t) and t[i+1][1] == ':': i += 2
            elif x == '{' and t[i][1] == '[': i = _skip(t, i) ; i += 1; continue
            if t[i][1] in '[{' and t[i][0] == 'p' or t[i][0] == 'id': i = _pattern(t, i, found)
            else: i += 1
            if i < len(t) and t[i][1] == '=': i = _expr_end(t, i + 1, {',', close})
        return i + 1
    return i + 1

def _skip(t, i):
    "Index of the closer matching the opener at `t[i]`."
    d = 0
    while i < len(t):
        if t[i][0] == 'p':
            if t[i][1] in _OPEN or t[i][1] == '${': d += 1
            elif t[i][1] in _CLOSE: d -= 1
            if d == 0: return i
        i += 1
    return i

def _ender(tok):
    "True when `tok` can end an expression, so a line break after it may end the statement."
    k, x = tok[:2]
    return (k in ('num', 'str', 'tpl', 're') or (k == 'id' and x not in _KW_REGEX | {'typeof'}) or (k == 'p' and x in _CLOSE))

def _expr_end(t, i, stops):
    "Index of the first token at depth 0 of an expression that is in `stops` or ends the statement."
    d = 0
    while i < len(t):
        k, x, _, nl = t[i]
        if k == 'p' and (x in _OPEN or x == '${'): d += 1
        elif k == 'p' and x in _CLOSE:
            if d == 0: return i
            d -= 1
        elif d == 0 and k == 'p' and x in stops | {';'}: return i
        elif d == 0 and nl and i and _ender(t[i-1]) and k in ('id', 'num', 'str') and x not in _NOCONT: return i
        i += 1
    return i

def declared(s):
    "`[(name, line)]` for every name `s` declares at its top level."
    t, out, i, d = tokens(s), [], 0, 0
    while i < len(t):
        k, x, ln, nl = t[i]
        if k == 'p':
            d += (x in _OPEN or x == '${') - (x in _CLOSE)
            i += 1; continue
        prev = t[i-1] if i else None
        if d or k != 'id' or (prev and prev[1] == '.' and prev[0] == 'p'): i += 1; continue
        if x in ('const', 'let', 'var') and i + 1 < len(t) and (t[i+1][0] == 'id' or t[i+1][1] in '[{'):
            i += 1
            while i < len(t):
                i = _pattern(t, i, out)
                if i < len(t) and t[i][1] == '=': i = _expr_end(t, i + 1, {','})
                if i < len(t) and t[i][1] == ',': i += 1; continue
                break
        elif x in ('function', 'class'):
            i += 1
            if x == 'function' and i < len(t) and t[i][1] == '*': i += 1
            ok = prev is None or prev[1] in _STMT_END or (nl and prev[0] in ('id', 'num', 'str', 'tpl', 're') or prev[1] in (')', ']'))
            if ok and i < len(t) and t[i][0] == 'id' and not (x == 'class' and t[i][1] == 'extends'): out.append((t[i][1], t[i][2]))
        else: i += 1
    return out
