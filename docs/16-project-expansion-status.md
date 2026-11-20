# Project Expansion: Progress and Follow-up

Updated November 20, 2026. Branch: `project-expansion`; review: PR #7.

## Current status

The extension now includes a follow-up implementation, strengthened tests and 474 saved follow-up experiment records. Selected earlier gaps have been addressed; the extension is still an experimental simulator, not a production scheduler or a completed validation study.

현재 상태: 순차 계획 자원 결함 수정, 이중 개선율 분석, 20인 연속 작업 및 혼잡 v2 실험을 반영했다. 전체 테스트 74개와 저장 자료 재분석을 확인했다. 혼잡 안정화·민감도·창고 규모 실험 등은 남아 있다.

Read the [tracked plan](17-expansion-plan.md) for target behavior and the [design and results](15-multi-picker-simulation.md) for model details. Acceptance criteria in the plan are not a blanket completion claim.

## History and provenance

- Base: `code-verification` at `ff03681`.
- Initial implementation/report/evidence: `782cce6`, `dea2f1b`, `213a076`.
- Branch publication and tracked plan: `914c9a8`, `4b43d61`.
- Imported follow-up `371df7048141f3550260bae96eb2d1227a8f36cd` becomes `81a0a68` on this branch.
- Imported follow-up `61d49bafcd2a9a8d61acae15d7b7912fbabc9ba4` becomes `028bf35`; the design-report conflict was resolved while preserving the branch's caveats.

The original `picking/` implementation remains unchanged. Performance records were produced by the supplying implementation run; this integration reran tests and analysis, not the complete performance matrix.

## Implemented scope

The separate `simulation/` package supports a graph warehouse, U-shaped conveyor access, continuous tasks starting at previous unload points, spatial/balanced assignment, unissued-request moves/swaps, NN/2-opt/reinsertion combinations, alternating improvement and optional segment DP.

Collection is 10 or 30 seconds per item with a 40/60 mix; unloading is 5 seconds. Pickup zones have FIFO capacity constraints. Fixed-delay and measured-delay computation modes model planning overlap.

Follow-up changes include:

- Sequential planner resource occupancy throughout an operation, preventing overlapping planning operations.
- Persisted task/picker records and adoption/abort information.
- Aggregate completion-time improvement and mean per-run improvement, with separate paired seed-group bootstrap calculations.
- Congestion v2: staggered LPT-based forecasts and lexicographic candidate evaluation. It remains optional, with congestion awareness off by default.
- Additional exact timing, event-order, small-route and interruption checks.

The default warehouse is still 36 by 40 m; shelf-side labels are synthetic and conveyor access is discretized. Aisle collisions do not delay walking. Evaluation-count limits are not strict wall-clock deadlines.

## Integration checks actually performed

- `python -m unittest discover -s tests`: **74 passed** (37 original and 37 extension tests).
- Parsed five `results/multi2/*.jsonl` files: fixed-total 126, per-picker 84, continuous20 84, fixed20 84, congestion 96; **474 records**.
- Executed `python -I simulation/analysis2.py results/multi2` on the saved data. [Analysis output](../results/multi2/analysis-summary.txt) is included.
- Recomputed the historical JSONL records separately. [Historical analysis](../results/multi/analysis2-historical.txt) is descriptive only.
- Corrected analysis labels so follow-up per-picker records are not called first-round defective records; chained-start totals and per-run means are explicitly distinguished.
- Reclassified positive-only waiting/distance aggregates as descriptive information, not causal proof.

Full performance experiments were not rerun during integration. Current tests verify specific properties, not every possible schedule or every plan acceptance.

## Results and their scope

For the 20-picker NN baseline, the saved records show one task per picker at 240 requests, two at 480, and four at 960. Non-staging subsequent starts are respectively 0, 20 and 60 per run in those conditions.

At 480 requests, evaluation aggregate completion improvement is about **0.23%** for fixed-delay `nn-2opt-reinsert` (95% interval 0.05–0.55), **0.27%** for its measured-delay counterpart (0.09–0.48), and **0.30%** for measured alternating search (0.13–0.52). Measured `nn-2opt-reinsert` saves approximately 2.3 seconds per run, with 7 improved and 3 worse runs.

At 240 requests the fixed-delay completion improvement is zero, but this does not prove no route can improve. At 960 requests the fixed-delay estimate is about 0.06%, with an interval including zero. Repeated tasks therefore do not guarantee an improvement. Do not assert NN optimality from unchanged heuristic output or infer that task chaining alone causes the effect.

Congestion v2 evaluation results versus congestion-off have mean per-run completion changes of **+0.12% at ten pickers and -2.97% at twenty**. Mean waiting falls by about 54/61 seconds; mean distance changes by **-4/+7 m**, respectively. Prediction MAE improves, but distance does not decrease in every condition and completion remains unstable. Congestion v2 is an experimental candidate, not a recommended default.

The 209.9-second planning-wait figure for the measured 20-picker/960-request condition is a sum across pickers averaged across runs. It is not an additional 209.9 seconds to add to episode makespan. Forecast mismatch and bottleneck explanations require further controlled analysis.

## Historical data warning

`results/multi/` preserves the initial 786 records, including a 24-record stress JSON array. They were generated before the planner-serialization fix. Neither absolute timing nor relative method ranking is automatically reliable: a common defect can affect competing methods differently through dispatch, assignment and congestion.

Keep those records as historical exploratory evidence. Use `results/multi2/` for current post-fix numerical claims. The historical reanalysis reads 762 JSONL records; the separate 24-record stress array is not included in that analysis.

## Addressed in the supplied follow-up

- [x] Sequential planning-resource defect fixed and regression checked.
- [x] Saved records for 20-picker repeated tasks and three demand-comparison designs added.
- [x] Two improvement formulas and formula-specific bootstrap intervals implemented.
- [x] Absolute savings, deterioration, computation and waiting metrics reported.
- [x] Congestion v1/v2 comparisons and adoption logs added.
- [x] Eleven stronger timing/event/interruption tests added; full suite passes.

These describe implemented checks and evidence; they do not certify the entire research plan as complete.

## Remaining work

- [ ] Pair each adopted candidate's forecast with its actual downstream outcome; aggregate adoption counts do not establish causality.
- [ ] Stabilize congestion-aware scheduling and verify improvements on independent data before considering default adoption.
- [ ] Repeat method timing measurements on identical workloads; randomized ordering in the existing suite is not repeated timing validation.
- [ ] Test walking/handling-time sensitivity and larger/different warehouse geometries.
- [ ] Review synthetic shelf-side geometry and conveyor approximation beyond current cases.
- [ ] Verify coverage of all interruption phases, path-level validity and non-issued-work invariants beyond the existing injected checkpoints.
- [ ] Review the old exact 990 m claim separately; second-round evidence is not direct recovery of missing first-round task records.
- [ ] Keep causal claims about chained starts, balance and planning delay as hypotheses unless controlled comparisons support them.

## Reproduction

From the repository root, using Python 3.12 and the standard library:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest discover -s tests
python -I simulation/analysis2.py results/multi2
python -I simulation/analysis2.py results/multi
```

Full rerun, if later needed (not performed during this integration):

```powershell
python -m simulation.experiments2 results/multi2-rerun
```

Choose a new directory. Measured results depend on the machine. Never overwrite the inherited evidence.

## Evidence index

- [Simulation source](../simulation/)
- [Tests](../tests/test_simulation.py)
- [Follow-up experiment runner](../simulation/experiments2.py)
- [Dual-formula analysis](../simulation/analysis2.py)
- [Follow-up records](../results/multi2/)
- [Historical records](../results/multi/)
- [Plan](17-expansion-plan.md)

PR #7 remains a draft; this update does not merge the extension.
