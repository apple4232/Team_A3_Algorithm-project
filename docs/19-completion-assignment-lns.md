# 19. Fourth-Round Study: Savings Batching, Completion Assignment and Limited LNS

> **Current interpretation:** exploration ended; see the [complete record](20-expansion-study-record.md). These comparisons reuse evaluation seed IDs and are not a fresh final independent test. Variable splitting was inactive and therefore unevaluated. LNS outcome invariance has unresolved causes. Computation budgets were not met. The imported report bears a November 22, 2026 label, later than the November 21 archive integration; do not use that label as proof of execution date.

Source branch: `multi-picker-evidence`. Data: `results/multi4-dev/` (20 runs), `results/multi4-eval/` (360: 240 fixed and 120 measured). Reported environment: Windows 10, Python 3.12.2.

Question: **Can the existing cap24 candidate C3 be improved further?**

## 1. Implementation using planning-time information

- **Savings batching** (`assignment.savings_bundles`): begin with same-location groups. Merge by `estimate(A)+estimate(B)-estimate(A union B)` using NN travel and conveyor termination, with staging as the stated virtual start. Examine k-nearest-centre candidates (k=8), descending savings, lexicographic ties and request caps.
- **Completion scheduling** (`assignment.completion_schedule`): inspect batches by descending estimated duration. Select the worker minimizing availability plus travel/handling/conveyor/unloading time. Handling includes 10/30 seconds and quantities. Predicted positions start at staging and update to the preceding NN route's nearest conveyor endpoint. The simulator respects `assigned_picker`.
- **Variable splitting** (`ensure_task_count`): split the largest batch when task count is below worker count. This is a minimum-task-count policy, not general adaptive-duration batching.
- **Limited LNS** (`lns.lns_improve`): remove q requests from a predicted bottleneck batch, alternating centre-distance and seeded-random selection, then repair and accept predicted overall completion improvement. Validate ownership/caps before commit; keep a valid plan at interruption. Iteration and wall-time limits are separate.
- **Cost controls:** cached estimates keyed by start and request set, stage timing in `plan.phases`, and the original 15-second target. The original report described incremental insertion; archive review found whole `expected_makespan` calls inside insertion evaluation, so that stronger efficiency description is unverified.

The full suite passed **88 tests**, eight more than the prior stage. New checks cover savings partition/merging/determinism, completion availability and ownership, minimum-task splitting, LNS partition/interruption/predicted non-worsening, and fixed-mode replay. These checks do not resolve all LNS-to-execution propagation risks.

## 2. Development screen

Seeds 202-208, ten pickers, 480 requests, fixed mode:

| Stage | Change versus C3 | Interpretation |
|---|---|---|
| S2 savings + balanced | **-19.71%** | Rejected; compact groups accompanied by load spread around 630 seconds. |
| S3 savings + completion | -11.95% | Rejected; spread reduced to about 448 seconds but insufficient recovery. |
| S3b chunk + completion | **+0.42%** | Promising for further comparison. |
| S4b plus variable splitting and LNS | +0.42% | No additional observed outcome; splitting inactive and LNS effect unresolved. |

S3b (cap24/chunk/completion/n2r) and S4b were frozen for the next comparison. Savings remained a documented negative development result.

## 3. Follow-up on reused evaluation groups

Ten seeds 203-221 across six conditions; primary measure is aggregate completion improvement. Compare S3b with C3 (cap24/balanced/n2r).

| Condition | Fixed mode | Measured mode | Worse cases: fixed / measured |
|---|---|---|---|
| p10/R480 | **+0.84% [0.30,1.33]**, 13.6 seconds saved | +2.91%, 47.4 seconds | 0/10 / 1/10 |
| Large 76 by 80 m/R960 | **+0.57% [0.02,1.10]**, 19.6 seconds | +1.72%, 59.4 seconds | 0/10 / 1/10 |
| p20/R960 | +0.23% [-0.39,0.82], 3.6 seconds | +2.03%, 32.6 seconds | 0/10 / 1/10 |
| Hotspot, p10 | +0.26% [-0.23,0.89] | +0.96% | Not listed |
| Wrapped share 70%, duplicates, p10 | +0.64% [-0.18,1.42] | +1.92% | Not listed |
| **p20/R480, one task per picker** | **-4.87% [-6.27,-3.46]** | -3.36% | 10/10 / 10/10 |

Fixed S4b results match S3b. Inactive splitting does not establish its ineffectiveness. LNS requires tracking changed groups, named owners, exceptions and final issued tasks before judging its algorithmic value. Planning-versus-execution mismatch is a hypothesis; archive review additionally identified order/assignment consistency risks. LNS is not recommended as part of the final candidate.

Against L1/cap12 instead of C3, the report gives p10/R480 about +5.35% and the large-layout condition about +11.75%. These have a different baseline from the table and must not be substituted for the incremental C3 comparison.

Completion assignment's reported additional initial computation is about 0.02-0.3 seconds in fixed-mode runs. Measured large-layout initial planning reaches **79.4 seconds**, exceeding 15 seconds. A similar baseline cost does not waive noncompliance or establish budget feasibility.

## 4. Qualified conclusion

> For the default synthetic warehouse, 480 requests and ten pickers, replacing the cap24 candidate's balancing with availability/previous-unload-aware completion scheduling reduced fixed-mode completion by 13.6 seconds, aggregate 0.84% [0.30,1.33]. Measured improvement was 2.91%; keep timing modes separate. Large-layout fixed improvement was 0.57% [0.02,1.10], while twenty pickers/960 requests gave an interval including zero. Twenty pickers/480 requests worsened 4.87% in fixed mode. These are conditional exploratory gains, not a default operational recommendation. Savings had adverse development outcomes, splitting was inactive, and LNS ineffectiveness was not established.

## 5. Reproduction

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest discover -s tests
python -m simulation.experiments4 results dev-stages
python -m simulation.experiments4 results eval-all eval-measured
```

Those experiment commands run simulations. For a read-only saved-data summary, use `python -m simulation.archive_summary results/expansion-archive-summary-rerun.json`. Preserve archived outputs when resuming.

## 6. Limitations

- Causes of p20/R480 deterioration are hypotheses; load spread, chained starts and computation change together. A tasks-per-worker >=2 selector is unvalidated.
- LNS may have group/order/owner propagation problems; regret-2 and other repair variants were not tested. Unchanged outcomes do not establish no useful LNS exists.
- Savings sensitivity to k=8 and the virtual staging start was not studied.
- Sequential measured planning can exceed the budget; introducing parallel planning would change the computation-resource model.
- Evaluation seed reuse, missing repeated same-input timing, synthetic geometry and excluded basket capacity limit generalization.
