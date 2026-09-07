**Goal.** Increase procurement productivity by 10% in FY26.  
measure: purchase orders per buyer FTE per month | baseline: 41 (FY25 actual) | target: 45 | by: 2026-09-30

**Contributes.** most of the 10 points; the cap is the rest

Adds `triage`, the rule that lets an indirect PO under EUR 2,000 from a contracted supplier skip
the approval chain. Backtested against the Q3 extract. The per-supplier cap is not in this change.

The cap is not implemented. It is the only thing between this and a pilot.

### Tasks
- [x] Backtest the rule against Q3. (me)

### Why
<details>
<summary>What would have gone wrong if `triage` had run in Q3? `caught` says 79%. Check it against the audit.</summary>

79% of the tail clears the rule, which is 27% of all POs. Against the Q3 extract that is 14 POs
the audit flagged for split ordering, all from one supplier. Cap the rule per supplier per month
and those 14 stay in the chain.
</details>

### Attached
- `file:procure/core.py`
- `pkg:pandas`
- `doc:drive/audit-q3.pdf`

### Files
- `procure/core.py`
- `tests/test_triage.py`
