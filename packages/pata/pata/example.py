"A worked document, used by the tests and by `pata.paint` to draw the prototype."

from __future__ import annotations
from .doc import Doc, Block
from .layout import arrange

__all__ = ['procurement']

def _b(doc, kind, id, frame='', mode='auto', **props):
    return doc.add(Block(kind=kind, props=props, id=id, frame=frame, mode=mode))

def procurement():
    "One goal worked end to end: framing, evidence, a baseline, a prototype, a decision."
    d = Doc(meta={'title': 'Procurement productivity +10%', 'default_exp': 'procure.core'})
    _b(d, 'frame', 'f-frame', title='Frame the goal')
    _b(d, 'goal', 'goal', frame='f-frame',
       source='Increase procurement productivity by 10% in FY26',
       measure='purchase orders handled per buyer FTE per month',
       baseline='41 POs / FTE / month (FY25 actual)', target='45 POs / FTE / month',
       by='2026-09-30')
    _b(d, 'text', 't-scope', frame='f-frame',
       source=('Indirect spend only. 62 buyers across 4 regions. Direct materials sit with the '
               'category teams and are out of scope for this document.'))
    _b(d, 'task', 'k-1', frame='f-frame', status='doing', owner='Priya',
       source='Agree the measure with Finance')
    _b(d, 'task', 'k-2', frame='f-frame', status='todo', owner='me',
       source='Baseline the current cycle time')
    _b(d, 'task', 'k-3', frame='f-frame', status='todo', owner='me',
       source='Ship the triage rule to one region')

    _b(d, 'frame', 'f-know', title='What we already know')
    _b(d, 'source', 's-hackett', frame='f-know',
       title='Hackett Group: procurement benchmark 2025', url='https://example.org/hackett-2025',
       text=('Top-quartile organisations process 2.3x the POs per buyer of the median. The gap is '
             'almost entirely low-value tail spend that never needed a buyer.'))
    _b(d, 'source', 's-audit', frame='f-know',
       title='Internal audit, Q3 FY25', path='drive/audit-q3.pdf',
       text=('34% of purchase orders raised in Q3 were under EUR 2,000. Median approval chain for '
             'those was 3 people and 6.2 days.'))
    _b(d, 'source', 's-interview', frame='f-know', mode='keep',
       title='Buyer interviews (7)', text=('Every buyer named the same two: re-keying supplier data '
             'from email, and chasing approvals that nobody disputes.'))
    _b(d, 'prompt', 'p-synth', frame='f-know',
       source='Where does the 10% most plausibly come from? Use only the three sources here.',
       context={'scope': 'frame', 'pins': ['goal'], 'budget': 12000},
       reply=('Tail spend is the only pool big enough. 34% of POs are under EUR 2,000 and carry a '
              'three-person approval chain that the audit found nobody ever rejects. Auto-approving '
              'that band would take roughly a third of PO volume off the buyers without touching '
              'the categories where negotiation earns money. That is worth about 12% of buyer time '
              'on the interview evidence, which clears the 10% target with room.'))
    _b(d, 'task', 'k-4', frame='f-know', status='done', owner='me',
       source='Pull the Q3 PO extract')

    _b(d, 'frame', 'f-base', title='Baseline the tail')
    _b(d, 'data', 'd-pos', frame='f-base', name='pos',
       source='pos', preview='DataFrame 84,213 x 11 - po_id, value_eur, buyer, region, raised_at, approved_at, approvers')
    _b(d, 'code', 'c-band', frame='f-base', mode='keep',
       source=('#|export\ndef bands(pos, cut=2000):\n'
               '    "Split a PO extract into the tail below `cut` and the rest."\n'
               '    tail = pos[pos.value_eur < cut]\n'
               '    return tail, pos.drop(tail.index)'),
       lang='python', execution_count=3, execution_ms=41.2,
       outputs=[{'output_type': 'stream', 'text': ''}])
    _b(d, 'code', 'c-share', frame='f-base',
       source='tail, rest = bands(pos)\nlen(tail) / len(pos), tail.approvers.median()',
       lang='python', execution_count=4, execution_ms=118.0,
       outputs=[{'output_type': 'execute_result', 'data': {'text/plain': '(0.341, 3.0)'}}])
    _b(d, 'code', 'c-cycle', frame='f-base',
       source="tail.groupby('region').cycle_days.mean()",
       lang='python', execution_count=5, execution_ms=96.5,
       outputs=[{'output_type': 'error', 'ename': 'AttributeError',
                 'evalue': "'DataFrame' object has no attribute 'cycle_days'"}])
    _b(d, 'prompt', 'p-fix', frame='f-base',
       source='Fix the cell above. Leave the result as `cycle`.',
       context={'scope': 'upstream', 'pins': ['d-pos'], 'budget': 8000},
       reply=('`cycle_days` is not a column. `raised_at` and `approved_at` are, so I derived it and '
              'bound the regional means as `cycle`.'))

    _b(d, 'frame', 'f-proto', title='Prototype the triage rule')
    _b(d, 'code', 'c-rule', frame='f-proto',
       source=('#|export\ndef triage(po, cut=2000, trusted=frozenset()):\n'
               '    "Whether a PO can skip the approval chain."\n'
               '    return po.value_eur < cut and po.supplier in trusted and po.contract_id is not None'),
       lang='python', execution_count=7, execution_ms=12.0, outputs=[])
    _b(d, 'code', 'c-backtest', frame='f-proto',
       source='auto = tail.apply(triage, axis=1, trusted=preferred)\nauto.mean()',
       lang='python', execution_count=8, execution_ms=402.0,
       outputs=[{'output_type': 'execute_result', 'data': {'text/plain': '0.79'}}])
    _b(d, 'prompt', 'p-risk', frame='f-proto',
       source='What would have gone wrong if this rule had run in Q3? Check it against the audit.',
       context={'scope': 'upstream', 'pins': ['s-audit', 'goal'], 'budget': 10000},
       reply=('79% of the tail clears the rule, which is 27% of all POs. Against the Q3 extract that '
              'is 14 POs the audit flagged for split ordering, all from one supplier. Cap the rule '
              'per supplier per month and those 14 stay in the chain.'))
    _b(d, 'text', 't-note', frame='f-proto',
       source='Cap is not implemented yet. It is the only thing between this and a pilot.')

    _b(d, 'frame', 'f-ship', title='Decide')
    _b(d, 'prompt', 'p-rec', frame='f-ship',
       source='Draft the recommendation for the steering committee. One page, no hedging.',
       context={'scope': 'doc', 'pins': ['goal', 'p-synth', 'p-risk'], 'mutes': ['t-note'],
                'budget': 30000},
       reply=('Auto-approve indirect POs under EUR 2,000 from contracted suppliers, capped per '
              'supplier per month. It removes 27% of PO volume from the approval chain, which the '
              'interview evidence puts at about 12% of buyer time. Pilot one region for a quarter '
              'against the same measure Finance agreed.'))
    _b(d, 'task', 'k-5', frame='f-ship', status='blocked', owner='Priya',
       source='Steering committee slot - waiting on the Finance sign-off in task 1')
    _b(d, 'text', 't-open', frame='f-ship',
       source='Open: does the cap belong in the rule or in the ERP workflow?')

    for src, dst, rel in [('s-hackett', 'p-synth', 'feeds'), ('s-audit', 'p-synth', 'feeds'),
                          ('s-interview', 'p-synth', 'feeds'), ('goal', 'p-synth', 'feeds'),
                          ('d-pos', 'c-band', 'feeds'), ('c-band', 'c-share', 'feeds'),
                          ('c-share', 'c-cycle', 'feeds'), ('c-cycle', 'p-fix', 'feeds'),
                          ('p-synth', 'c-rule', 'feeds'), ('c-band', 'c-rule', 'feeds'),
                          ('c-rule', 'c-backtest', 'feeds'), ('c-backtest', 'p-risk', 'feeds'),
                          ('s-audit', 'p-risk', 'supports'), ('p-risk', 'p-rec', 'feeds'),
                          ('p-synth', 'p-rec', 'feeds'), ('t-note', 'k-5', 'blocks')]:
        d.add(Block('edge', {'src': src, 'dst': dst, 'rel': rel}, id=f'e-{src}-{dst}'))
    return arrange(d)
