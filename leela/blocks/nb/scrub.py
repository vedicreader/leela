"Which code cells may re-run on every tick of a scrubbed number: an allowlist of effects, checked on the syntax tree."
import ast, builtins, math, cmath, statistics, itertools

def _w(mod, names): return {f'{mod}.{n}' for n in names.split()}
def _all(mod, m): return {f'{mod}.{n}' for n in dir(m) if not n.startswith('_')}
#: Every dotted name a scrubbed cell may use from an imported module. A name not here is refused, so a re-export such as `np.os` or `collections.sys` never gets in.
ALLOW = (_all('math', math) | _all('cmath', cmath) | {f'statistics.{n}' for n in statistics.__all__} |
  {f'itertools.{n}' for n in dir(itertools) if not n.startswith('_') and n not in ('count', 'cycle', 'repeat')} |
  _w('random', 'random randint uniform gauss normalvariate choice choices sample randrange seed triangular betavariate expovariate Random') |
  _w('operator', 'add sub mul truediv floordiv mod pow neg abs eq ne lt le gt ge and_ or_ xor not_ itemgetter') |
  _w('functools', 'reduce partial') | _w('collections', 'Counter deque defaultdict namedtuple OrderedDict') |
  _w('fractions', 'Fraction') | _w('decimal', 'Decimal') | _w('time', 'time perf_counter monotonic sleep') |
  _w('datetime', 'datetime date timedelta timezone datetime.now datetime.today datetime.fromisoformat date.today date.fromisoformat') |
  _w('numpy', 'pi e inf nan newaxis array asarray zeros ones empty full arange linspace logspace eye identity diag sin cos tan arcsin arccos arctan arctan2 sinh cosh tanh '
     'exp expm1 log log1p log10 log2 sqrt cbrt square abs absolute sign floor ceil round around rint sum mean median std var min max amin amax argmin argmax cumsum cumprod prod '
     'dot matmul outer inner cross transpose reshape ravel concatenate stack vstack hstack split where sort argsort unique diff gradient polyfit polyval roots interp meshgrid '
     'clip maximum minimum add subtract multiply divide power mod isnan isinf isfinite allclose isclose any all count_nonzero trace tile repeat zeros_like ones_like full_like '
     'convolve correlate histogram percentile quantile average cov corrcoef deg2rad rad2deg radians degrees hypot float64 int64 ndarray') |
  _w('numpy.random', 'rand randn randint random normal uniform choice permutation default_rng seed standard_normal poisson binomial exponential') |
  _w('numpy.linalg', 'inv det solve eig eigh eigvals norm svd matrix_power pinv lstsq qr cholesky matrix_rank') |
  _w('numpy.fft', 'fft ifft rfft irfft fftfreq rfftfreq fftshift') |
  _w('matplotlib.pyplot', 'plot scatter bar barh hist hist2d axvline axhline axvspan axhspan title xlabel ylabel legend figure subplots subplot show xlim ylim grid text annotate '
     'fill_between errorbar step stairs pie imshow contour contourf colorbar tight_layout suptitle xticks yticks semilogx semilogy loglog polar boxplot violinplot stem axis') |
  _w('pandas', 'DataFrame Series concat date_range to_datetime cut isna notna Timestamp'))
ROOTS = {a.split('.')[0] for a in ALLOW}
PURE_BUILTINS = frozenset('abs all any bool bin bytes callable chr complex dict divmod enumerate filter float format frozenset hash hex int isinstance iter len list map max min oct ord pow print '
  'range repr reversed round set slice sorted str sum tuple zip display Exception ValueError TypeError KeyError IndexError ZeroDivisionError ArithmeticError AssertionError RuntimeError OverflowError StopIteration'.split())
#: Methods that leave their object as it was, or only draw. A method not named here is refused, whatever it is called on.
PURE_M = frozenset(('sum mean std var min max median prod cumsum cumprod argmax argmin argsort reshape copy astype tolist ravel flatten transpose dot round clip any all nonzero squeeze '
  'swapaxes diagonal trace conj item count index find rfind startswith endswith lower upper strip lstrip rstrip split rsplit join replace format zfill center ljust rjust title capitalize '
  'isdigit isalpha keys values items get isoformat strftime total_seconds head tail describe groupby merge dropna fillna reset_index set_index sort_index sort_values unique value_counts '
  'corr cov rolling expanding shift diff pct_change plot hist scatter bar barh set_title set_xlabel set_ylabel set_xlim set_ylim set_aspect set_xticks set_yticks legend grid text annotate '
  'axvline axhline fill_between errorbar imshow step stem pie axis suptitle tight_layout set_size_inches bit_length conjugate').split())
#: Methods that advance a generator or an iterator: only an object this cell made may take them.
RNG_M = frozenset('random normal uniform integers choice standard_normal permutation poisson binomial exponential randint gauss sample'.split())
#: Methods that change their object. Only an object this cell made may take them.
MUT_M = frozenset('append extend insert pop remove clear update add discard setdefault popitem sort reverse fill resize appendleft popleft extendleft rotate'.split()) | RNG_M
ATTRS = frozenset('shape dtype T real imag size ndim loc iloc at iat columns index values name str dt flat nbytes itemsize year month day hour minute second microsecond numerator denominator'.split())
BAD_KW = frozenset('out inplace file filename fname path mode dir root buf path_or_buf fp stream'.split())
SIZED = frozenset('range ones zeros empty full arange linspace logspace tile repeat eye identity rand randn randint random normal uniform choice integers standard_normal reshape sleep'.split())
CAP, WORK = 10000, 10**6
NODES = frozenset(getattr(ast, n) for n in ('Module Expr Assign AugAssign AnnAssign For While If Break Continue Pass Return FunctionDef Try ExceptHandler Raise Assert Delete Import ImportFrom alias '
  'arguments arg BoolOp BinOp UnaryOp Lambda IfExp Dict Set ListComp SetComp DictComp GeneratorExp comprehension Compare Call keyword JoinedStr FormattedValue Constant Attribute Subscript '
  'Starred Name List Tuple Slice NamedExpr Load Store Del And Or Add Sub Mult MatMult Div Mod Pow LShift RShift BitOr BitXor BitAnd FloorDiv Invert Not UAdd USub Eq NotEq Lt LtE Gt GtE '
  'Is IsNot In NotIn').split())
LONG = 20000

class No(Exception): pass

def okpath(p): return p in ALLOW
def modpath(p): return any(a.startswith(p + '.') for a in ALLOW)

def fold(n, memo=None):
    "The number a constant expression comes to, or None."
    if isinstance(n, ast.Constant): return n.value if type(n.value) in (int, float) else None
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        v = fold(n.operand); return None if v is None else -v if isinstance(n.op, ast.USub) else v
    if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Pow, ast.FloorDiv, ast.Div, ast.Mod)):
        a, b = fold(n.left), fold(n.right)
        if a is None or b is None: return None
        try:
            if isinstance(n.op, ast.Pow): return float('inf') if abs(b) > 64 or abs(a) > 1e6 else a ** b
            return {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.FloorDiv: lambda: a // b, ast.Div: lambda: a / b, ast.Mod: lambda: a % b}[type(n.op)]()
        except (ArithmeticError, ValueError, TypeError): return None
    return None

def huge(tree):
    "Whether some constant expression in `tree` is over the cap."
    return any((v := fold(n)) is not None and (v != v or abs(v) > CAP) for n in ast.walk(tree))

class Check(ast.NodeVisitor):
    def __init__(self):
        self.imports, self.glob, self.funcs, self.outside, self.scopes, self.mult = {}, {}, set(), set(), [], 1
    def no(self, why): raise No(why)
    def visit(self, n):
        if type(n) not in NODES: self.no(f'it uses {type(n).__name__}, which scrubbing does not re-run')
        return super().visit(n)
    def look(self, name):
        for s in reversed(self.scopes):
            if name in s: return ('local', s[name])
        if name in self.glob: return ('local', self.glob[name])
        if name in self.imports: return ('import', self.imports[name])
        return ('builtin', None) if name in PURE_BUILTINS else ('outside', None)
    def tainted(self, e):
        "Whether `e` may be, or reach into, a value another cell made."
        inner = {n.id for n in ast.walk(e) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)} | {a.arg for n in ast.walk(e) if isinstance(n, ast.Lambda) for a in n.args.args}
        for n in ast.walk(e):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in inner:
                k, t = self.look(n.id)
                if k == 'outside' or (k == 'local' and t): return True
        return False
    def bind(self, name, taint=False, fn=False):
        if name.startswith('__'): self.no(f'it uses {name}')
        if name in self.outside and (not self.scopes or name not in self.scopes[-1]): self.no(f'it changes `{name}`, which another cell made')
        if name in self.imports: self.no(f'it replaces the import `{name}`')
        (self.scopes[-1] if self.scopes else self.glob)[name] = taint
        (self.funcs.add if fn else self.funcs.discard)(name)
    def root(self, n):
        while isinstance(n, (ast.Attribute, ast.Subscript)): n = n.value
        return n
    def target(self, t, taint=False, fn=False):
        if isinstance(t, ast.Name): self.bind(t.id, taint, fn)
        elif isinstance(t, (ast.Tuple, ast.List)): [self.target(x, taint) for x in t.elts]
        elif isinstance(t, ast.Starred): self.target(t.value, taint)
        elif isinstance(t, (ast.Attribute, ast.Subscript)):
            r = self.root(t)
            if not isinstance(r, ast.Name) or self.look(r.id) != ('local', False): self.no(f'it changes something that {"`" + r.id + "` " if isinstance(r, ast.Name) else ""}another cell may own')
            self.generic_visit(t)
        else: self.no('it assigns to something it cannot follow')
    def visit_Name(self, n):
        if n.id.startswith('__'): self.no(f'it uses {n.id}')
        k, _ = self.look(n.id)
        if k == 'import' and not okpath(self.imports[n.id]): self.no(f'it uses the module `{n.id}` as a value')
        if k == 'outside' and hasattr(builtins, n.id): self.no(f'it uses {n.id}')
        if k == 'outside': self.outside.add(n.id)
    def chain(self, n):
        "The dotted path of an attribute chain on an imported name, or None when it starts elsewhere."
        parts = []
        while isinstance(n, ast.Attribute): parts.append(n.attr); n = n.value
        if not isinstance(n, ast.Name) or self.look(n.id)[0] != 'import': return None
        p = self.imports[n.id]
        for a in reversed(parts):
            p += '.' + a
            if not (okpath(p) or modpath(p)): self.no(f'it uses {p}, which is not on the safe list')
        return p
    def visit_Attribute(self, n):
        if n.attr.startswith('_'): self.no(f'it reaches into {n.attr}')
        if (p := self.chain(n)) is not None:
            if not okpath(p): self.no(f'it uses the module {p} as a value')
            return
        if n.attr not in PURE_M | MUT_M | ATTRS: self.no(f'it uses .{n.attr}, which is not on the safe list')
        if n.attr in MUT_M and self.tainted(n.value): self.no(f'it calls .{n.attr} on a value another cell made')
        self.visit(n.value)
    def visit_Call(self, n):
        f = n.func
        if any(isinstance(a, ast.Starred) for a in n.args) or any(k.arg is None for k in n.keywords): self.no('it calls with * or ** arguments')
        if (bad := next((k.arg for k in n.keywords if k.arg in BAD_KW), None)): self.no(f'it passes {bad}=, which can write')
        if isinstance(f, ast.Name):
            k, v = self.look(f.id)
            if k == 'builtin': pass
            elif k == 'local' and f.id in self.funcs: pass
            elif k == 'import':
                if not okpath(v): self.no(f'it calls {v}, which is not on the safe list')
            else: self.no(f'it calls `{f.id}`, which is not on the safe list')
            name = v if k == 'import' else f.id
        elif isinstance(f, ast.Attribute):
            self.visit(f); name = self.chain(f) or f.attr
        else: self.no('it calls something it cannot name')
        last = name.split('.')[-1]
        if name.endswith('time.sleep') and not (len(n.args) == 1 and (v := fold(n.args[0])) is not None and 0 <= v * self.mult <= 1): self.no('it sleeps more than 1 second')
        if last in SIZED and any(huge(a) for a in [*n.args, *[k.value for k in n.keywords]]): self.no(f'it asks {last} for more than {CAP}')
        for a in [*n.args, *[k.value for k in n.keywords]]: self.visit(a)
    def visit_BinOp(self, n):
        seq = (ast.List, ast.Tuple, ast.ListComp)
        if isinstance(n.op, ast.Mult) and (isinstance(n.left, seq + (ast.Constant,)) or isinstance(n.right, seq + (ast.Constant,))):
            if any(isinstance(x, seq) or (isinstance(x, ast.Constant) and isinstance(x.value, (str, bytes))) for x in (n.left, n.right)) and huge(n): self.no(f'it repeats a sequence more than {CAP} times')
        if isinstance(n.op, ast.Pow) and (v := fold(n.right)) is not None and v > 1000: self.no('it raises to a huge power')
        self.generic_visit(n)
    def loop(self, it):
        "Multiplies the work by the size of `it` when it is a range of constants."
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == 'range' and it.args:
            vs = [fold(a) for a in it.args]
            if vs and all(v is not None for v in vs): self.mult *= max(1, max(abs(v) for v in vs))
            else: self.mult *= 100
        else: self.mult *= 100
        if self.mult > WORK: self.no('its loops nest too deep to re-run live')
    def visit_Assign(self, n):
        self.visit(n.value)
        for t in n.targets: self.target(t, self.tainted(n.value), isinstance(n.value, ast.Lambda))
    def visit_AnnAssign(self, n):
        self.visit(n.annotation)
        if n.value: self.visit(n.value)
        self.target(n.target, bool(n.value) and self.tainted(n.value))
    def visit_AugAssign(self, n):
        self.visit(n.value)
        t = n.target
        if isinstance(t, ast.Name):
            if self.look(t.id) != ('local', False): self.no(f'it changes `{t.id}`, which this cell did not make')
        else: self.target(t)
        if isinstance(n.op, ast.Pow) and (v := fold(n.value)) is not None and v > 1000: self.no('it raises to a huge power')
    def visit_Delete(self, n):
        for t in n.targets:
            if isinstance(t, ast.Name):
                if self.look(t.id) != ('local', False): self.no(f'it deletes `{t.id}`, which this cell did not make')
            else: self.target(t)
    def visit_NamedExpr(self, n): self.visit(n.value); self.target(n.target, self.tainted(n.value))
    def maybe(self, f, *a):
        "Runs `f`; a module-level name first bound inside it may be unbound on another path, so it may be a name another cell made: it counts as tainted."
        before = set(self.glob)
        try: return f(*a)
        finally:
            if not self.scopes: [self.glob.__setitem__(k, True) for k in set(self.glob) - before]
    def visit_If(self, n): self.maybe(self.generic_visit, n)
    def visit_For(self, n): self.maybe(self.for_, n)
    def for_(self, n):
        self.visit(n.iter); keep = self.mult; self.loop(n.iter)
        self.target(n.target, self.tainted(n.iter))
        [self.visit(x) for x in (*n.body, *n.orelse)]; self.mult = keep
    def visit_While(self, n): self.maybe(self.while_, n)
    def while_(self, n):
        if isinstance(n.test, ast.Constant) and n.test.value and not any(isinstance(x, ast.Break) for b in n.body for x in ast.walk(b)): self.no('it loops forever')
        self.visit(n.test); keep = self.mult; self.mult *= 100
        if self.mult > WORK: self.no('its loops nest too deep to re-run live')
        [self.visit(x) for x in (*n.body, *n.orelse)]; self.mult = keep
    def visit_Try(self, n): self.maybe(lambda: [self.visit(x) for x in (*n.body, *n.handlers, *n.orelse, *n.finalbody)])
    def visit_ExceptHandler(self, n):
        if n.type: self.visit(n.type)
        d = self.scopes[-1] if self.scopes else self.glob
        had = n.name in d if n.name else False; old = d.get(n.name)
        if n.name: self.bind(n.name)
        [self.visit(x) for x in n.body]
        if n.name:
            if had: d[n.name] = True
            else: d.pop(n.name, None)
    def visit_Import(self, n):
        for a in n.names:
            if not (okpath(a.name) or modpath(a.name)): self.no(f'it imports {a.name}, which is not on the safe list')
            name = a.asname or a.name.split('.')[0]
            self.bind(name); self.imports[name] = a.name if a.asname else a.name.split('.')[0]; self.glob.pop(name, None)
    def visit_ImportFrom(self, n):
        if n.level or not n.module: self.no('it imports a relative module')
        for a in n.names:
            p = f'{n.module}.{a.name}'
            if a.name == '*' or not (okpath(p) or modpath(p)): self.no(f'it imports {p}, which is not on the safe list')
            self.bind(a.asname or a.name); self.imports[a.asname or a.name] = p; self.glob.pop(a.asname or a.name, None)
    def scope(self, names, body):
        self.scopes.append(names); keep = self.mult
        try: [self.visit(x) for x in body]
        finally: self.scopes.pop(); self.mult = keep
    def visit_FunctionDef(self, n):
        if n.decorator_list: self.no('it uses a decorator')
        a = n.args
        for d in [*a.defaults, *[d for d in a.kw_defaults if d]]: self.visit(d)
        for x in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]:
            if x and x.annotation: self.visit(x.annotation)
        if n.returns: self.visit(n.returns)
        self.bind(n.name, fn=True)
        names = {x.arg: True for x in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg] if x}
        names |= {m.id: False for b in n.body for m in ast.walk(b) if isinstance(m, ast.Name) and isinstance(m.ctx, ast.Store) and m.id not in names}
        names |= {m.name: False for b in n.body for m in ast.walk(b) if isinstance(m, ast.FunctionDef)}
        self.scope(names, n.body)
    def visit_Lambda(self, n):
        a = n.args
        for d in [*a.defaults, *[d for d in a.kw_defaults if d]]: self.visit(d)
        self.scope({x.arg: True for x in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg] if x}, [n.body])
    def comp(self, n, elts):
        keep, names = self.mult, {}
        self.scopes.append(names)
        try:
            for g in n.generators:
                self.visit(g.iter); self.loop(g.iter)
                t = self.tainted(g.iter)
                for m in ast.walk(g.target):
                    if isinstance(m, ast.Name): names[m.id] = t
                [self.visit(c) for c in g.ifs]
            [self.visit(e) for e in elts]
        finally: self.scopes.pop(); self.mult = keep
    def visit_ListComp(self, n): self.comp(n, [n.elt])
    visit_SetComp = visit_GeneratorExp = visit_ListComp
    def visit_DictComp(self, n): self.comp(n, [n.key, n.value])

def scrub_why(source):
    "'' when `source` may re-run on each tick of a scrub, else one line saying why not. Never raises."
    try:
        source = source if isinstance(source, str) else str(source or '')
        if len(source) > LONG: return 'the cell is too long to re-run live'
        c = Check(); c.visit(ast.parse(source)); return ''
    except No as e: return str(e)
    except RecursionError: return 'it is nested too deeply to check'
    except MemoryError: return 'it is too big to check'
    except (SyntaxError, ValueError): return 'it is not valid Python as it stands (a magic or shell line also counts)'
    except Exception: return 'it could not be checked'

def scrub_ok(source): return not scrub_why(source)
