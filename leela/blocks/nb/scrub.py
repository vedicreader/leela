"Which code cells may run again on every tick of a number being scrubbed: a conservative AST check."
import ast

#: Modules a scrubbed cell may import: maths, plots and tables, which compute and draw but do not touch disk or net.
SAFE = frozenset('numpy math cmath random statistics itertools functools collections operator fractions decimal time datetime matplotlib pandas'.split())
BAD_CALLS = frozenset('input exec eval compile __import__ breakpoint exit quit globals locals vars setattr delattr help'.split())
BAD_DUNDER = frozenset('__class__ __subclasses__ __globals__ __builtins__ __import__ __dict__ __code__ __mro__ __bases__ __getattribute__'.split())
#: Methods that write a file or change a thing outside the cell by name, whatever object they are called on.
WRITES = frozenset('write writelines write_text write_bytes dump tofile savefig save savez savez_compressed savetxt to_csv to_excel to_parquet to_pickle to_json to_sql to_feather to_hdf to_stata to_clipboard to_latex to_markdown'.split())
MUTATORS = frozenset('append extend insert pop remove clear update add discard sort reverse setdefault popitem fill resize put shuffle'.split())
SLEEP_MAX = 1

class _Check(ast.NodeVisitor):
    def __init__(self): self.bound, self.why = set(), ''
    def no(self, why):
        if not self.why: self.why = why
    def root(self, n):
        while isinstance(n, (ast.Attribute, ast.Subscript)): n = n.value
        return n.id if isinstance(n, ast.Name) else None
    def outside(self, n, what):
        if (r := self.root(n)) and r not in self.bound: self.no(f'{what} `{r}`, which this cell did not make')
    def visit_Import(self, n):
        for a in n.names: self.mod(a.name)
        self.bound.update((a.asname or a.name).split('.')[0] for a in n.names)
    def visit_ImportFrom(self, n):
        self.mod(n.module if not n.level else None)
        self.bound.update(a.asname or a.name for a in n.names)
    def mod(self, name):
        if not name or name.split('.')[0] not in SAFE: self.no(f'it imports {name or "a relative module"}, which is not on the safe list')
    def visit_Global(self, n): self.no('it changes a global name')
    visit_Nonlocal = visit_Global
    def visit_Name(self, n):
        if isinstance(n.ctx, ast.Store): self.bound.add(n.id)
        if n.id in ('__builtins__', '__import__'): self.no(f'it uses {n.id}')
    def visit_Assign(self, n):
        self.visit(n.value)
        for t in n.targets: self.target(t)
    def visit_AnnAssign(self, n):
        if n.value: self.visit(n.value)
        self.target(n.target)
    def visit_AugAssign(self, n):
        self.visit(n.value)
        self.outside(n.target, 'it changes')
        self.target(n.target)
    def target(self, t):
        if isinstance(t, ast.Name): self.bound.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List, ast.Starred)): [self.target(x) for x in getattr(t, 'elts', [getattr(t, 'value', None)]) if x]
        else: self.outside(t, 'it changes'); self.generic_visit(t)
    def visit_FunctionDef(self, n):
        self.bound.add(n.name)
        a = n.args
        self.bound.update(x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg] if x)
        self.generic_visit(n)
    visit_AsyncFunctionDef = visit_FunctionDef
    def visit_ClassDef(self, n): self.bound.add(n.name); self.generic_visit(n)
    def visit_Attribute(self, n):
        if n.attr in BAD_DUNDER: self.no(f'it reaches into {n.attr}')
        self.generic_visit(n)
    def visit_Call(self, n):
        f = n.func
        if isinstance(f, ast.Name):
            if f.id in BAD_CALLS: self.no(f'it calls {f.id}')
            elif f.id == 'open' and self.writes_file(n): self.no('it opens a file to write')
        elif isinstance(f, ast.Attribute):
            if f.attr in WRITES: self.no(f'it calls .{f.attr}, which writes a file')
            elif f.attr == 'sleep' and not self.short(n): self.no(f'it sleeps more than {SLEEP_MAX} second')
            elif f.attr in MUTATORS and self.root(f.value) and self.root(f.value) not in self.bound: self.outside(f.value, f'it calls .{f.attr} on')
        self.generic_visit(n)
    def short(self, n):
        a = n.args[0] if n.args else None
        return isinstance(a, ast.Constant) and isinstance(a.value, (int, float)) and a.value <= SLEEP_MAX
    def writes_file(self, n):
        mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == 'mode'), None)
        if mode is None: return False
        return not (isinstance(mode, ast.Constant) and isinstance(mode.value, str) and not set(mode.value) & set('wax+'))
    def visit_comprehension(self, n): self.target(n.target); self.generic_visit(n)
    def visit_For(self, n): self.visit(n.iter); self.target(n.target); [self.visit(x) for x in (*n.body, *n.orelse)]
    def visit_With(self, n):
        for i in n.items:
            self.visit(i.context_expr)
            if i.optional_vars: self.target(i.optional_vars)
        [self.visit(x) for x in n.body]
    def visit_ExceptHandler(self, n):
        if n.name: self.bound.add(n.name)
        self.generic_visit(n)

def scrub_why(source):
    "'' when `source` may re-run on each tick of a scrub, else one line saying why not."
    try: tree = ast.parse(source)
    except (SyntaxError, ValueError): return 'it is not valid Python as it stands (a magic or shell line also counts)'
    c = _Check(); c.visit(tree)
    return c.why

def scrub_ok(source): return not scrub_why(source)
