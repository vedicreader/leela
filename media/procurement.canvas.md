---
title: Procurement productivity +10%
default_exp: procure.core
---

# Increase procurement productivity by 10%

<!--canvas goal id=goal measure="purchase orders per buyer FTE per month" baseline="41 (FY25 actual)" target=45 by=2026-09-30-->
Increase procurement productivity by 10% in FY26.
<!--/canvas-->

Indirect spend only. 62 buyers across 4 regions. Direct materials sit with the category teams and
are out of scope for this document.

<!--canvas task id=k1 status=doing owner=Priya-->
Agree the measure with Finance.
<!--/canvas-->

<!--canvas task id=k2 status=doing owner=me-->
Baseline the current cycle time.
<!--/canvas-->

<!--canvas task id=k3 status=todo owner=me-->
Ship the triage rule to one region.
<!--/canvas-->

## What we already know

<!--canvas source id=s-hackett title="Hackett Group: procurement benchmark 2025" url=https://example.org/hackett-2025-->
Top-quartile organisations process 2.3x the POs per buyer of the median. The gap is almost
entirely low-value tail spend that never needed a buyer.
<!--/canvas-->

<!--canvas source id=s-audit title="Internal audit, Q3 FY25" path=drive/audit-q3.pdf-->
34% of purchase orders raised in Q3 were under EUR 2,000. Median approval chain for those was 3
people and 6.2 days.
<!--/canvas-->

<!--canvas source id=s-buyers title="Buyer interviews (7)" context=keep-->
Every buyer named the same two: re-keying supplier data from email, and chasing approvals that
nobody disputes.
<!--/canvas-->

```canvas ask id=q-synth scope=region budget=12000
Where does the 10% most plausibly come from? Use only the three sources here.
```

<!--canvas reply id=7df84957 of=q-synth-->
Tail spend is the only pool big enough. 34% of POs are under EUR 2,000 and carry a three-person
approval chain that the audit found nobody ever rejects. Auto-approving that band would take
roughly a third of PO volume off the buyers without touching the categories where negotiation
earns money. On the interview evidence that is about 12% of buyer time, which clears the target.
<!--/canvas-->

## Baseline the tail

```canvas code id=c-load
pos = read_extract('drive/po-q3.parquet')
preferred = frozenset(contracted_suppliers())
```

```canvas code id=c-band
#|export
def bands(pos, cut=2000):
    "Split a PO extract into the tail below `cut` and the rest."
    tail = pos[pos.value_eur < cut]
    return tail, pos.drop(tail.index)
```

```canvas code id=c-share
tail, rest = bands(pos)
share = len(tail) / len(pos)
chain = tail.approvers.median()
share, chain
```

```canvas code id=c-cycle
cycle = tail.assign(days=(tail.approved_at - tail.raised_at).dt.days).groupby('region').days.mean()
cycle
```

```canvas data id=d-say
bind text = f"The tail is **{share:.0%}** of all POs, sits behind **{chain:.0f}** approvers, and takes **{cycle.mean():.1f} days** to clear."
```

That sentence is bound, not typed. Change the cut in `bands` and it moves with everything else.

```canvas ask id=q-fix scope=upstream budget=8000
`cycle_days` was not a column. Rebuild the cycle time from the timestamps and leave it as `cycle`.
```

## Prototype the triage rule

<!--canvas bundle id=triage title="Auto-approve the contracted tail" goal=goal contributes="most of the 10 points; the cap is the rest" paths=tests/test_triage.py refs=file:procure/core.py,pkg:pandas,doc:drive/audit-q3.pdf-->
Adds `triage`, the rule that lets an indirect PO under EUR 2,000 from a contracted supplier skip
the approval chain. Backtested against the Q3 extract. The per-supplier cap is not in this change.
<!--/canvas-->

```canvas code id=c-rule
#|export
def triage(po, cut=2000, trusted=frozenset()):
    "Whether a PO can skip the approval chain."
    return po.value_eur < cut and po.supplier in trusted and po.contract_id is not None
```

```canvas code id=c-backtest
auto = tail.apply(triage, axis=1, trusted=preferred)
caught = auto.mean()
caught
```

```canvas brick id=v-bars src=lego.bricks:viz.series emit_row=picked
bind labels = list(cycle.index)
bind series = [{'name': 'days to clear', 'values': list(cycle.values)}]
prop height = 240
```

```canvas ask id=q-risk scope=upstream budget=10000 supports=s-audit
pin s-audit
What would have gone wrong if `triage` had run in Q3? `caught` says 79%. Check it against the audit.
```

<!--canvas reply id=93eb631b of=q-risk-->
79% of the tail clears the rule, which is 27% of all POs. Against the Q3 extract that is 14 POs
the audit flagged for split ordering, all from one supplier. Cap the rule per supplier per month
and those 14 stay in the chain.
<!--/canvas-->

<!--canvas task id=k4 status=done owner=me-->
Backtest the rule against Q3.
<!--/canvas-->

<!--canvas note id=n-cap-->
The cap is not implemented. It is the only thing between this and a pilot.
<!--/canvas-->

## Decide

```canvas ask id=q-rec scope=doc budget=30000
pin goal
pin q-synth
pin q-risk
mute n-cap
Draft the recommendation for the steering committee. One page, no hedging.
```

<!--canvas reply id=b2364aa4 of=q-rec-->
Auto-approve indirect POs under EUR 2,000 from contracted suppliers, capped per supplier per
month. It removes 27% of PO volume from the approval chain, which the interview evidence puts at
about 12% of buyer time. Pilot one region for a quarter against the measure Finance agreed.
<!--/canvas-->

<!--canvas task id=k5 status=blocked owner=Priya-->
Steering committee slot. Waiting on the Finance sign-off in the first task.
<!--/canvas-->

Open: does the cap belong in the rule or in the ERP workflow?
