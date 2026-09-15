"The registry. `leela_bricks` declares its bricks this way, and `Brick.src` names its own library."

from dataclasses import asdict, dataclass, field

__all__ = ['Port', 'Brick', 'brick', 'BRICKS', 'GROUPS', 'find', 'manifest']

LIB = 'demobricks'

@dataclass
class Port:
    name: str
    kind: str = 'any'
    doc: str = ''
    sample: object = None
    required: bool = True
    def dict(self): return asdict(self)

@dataclass
class Brick:
    name: str
    title: str
    group: str
    doc: str = ''
    ports: list = field(default_factory=list)
    emits: list = field(default_factory=list)
    wire: str = ''
    height: int = 260
    @property
    def src(self): return f'{LIB}:{self.name}'
    def dict(self): return {**asdict(self), 'src': self.src,
                            'ports': [p.dict() for p in self.ports],
                            'emits': [p.dict() for p in self.emits]}

BRICKS, GROUPS = {}, {'viz': 'Plain figures'}

def brick(name, title, group, ports=(), emits=(), wire='', height=260, doc=''):
    BRICKS[name] = Brick(name=name, title=title, group=group, doc=doc, ports=list(ports),
                         emits=list(emits), wire=wire.strip('\n'), height=height)
    return BRICKS[name]

def find(name): return BRICKS.get(name)
def manifest(): return {'bricks': [b.dict() for b in BRICKS.values()], 'groups': GROUPS}

brick('viz.series', 'Series', 'viz', doc='One line per series.',
      ports=[Port('labels', 'list', 'x axis', sample=['a', 'b']),
             Port('series', 'list', 'the lines', sample=[{'name': 's', 'values': [1, 2]}])],
      emits=[Port('point', 'dict', 'the point clicked')], height=240,
      wire='labels = ["a", "b"]\nseries = [{"name": "s", "values": [1, 2]}]')
