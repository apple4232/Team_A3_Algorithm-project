# Project Expansion: Final Status and Closure

Recorded November 21, 2026. Branch: `project-expansion`.

## Decision

The user ended the current expansion exploration and requested that PR #7 be closed without merging. Preserve the branch, code, plans, experiments and negative results as an exploratory prototype. The original single-picker project remains the primary deliverable.

현재 상태: **확장 탐색 종료·코드와 연구 기록 보존**. 일부 합성 조건의 개선을 관측했지만 일반 적용 가능성·계산 예산·최종 독립 검증을 함께 확보하지 못했다. 새 성능 실험을 계속하지 않고 결과와 한계를 정리한다. PR #7은 병합 없이 닫는다.

Start with the [complete development and closure record](20-expansion-study-record.md). It supersedes overbroad statements in earlier stage reports.

## What is preserved

- U-shaped conveyor, repeated tasks, pickup service/waiting and sequential planning simulation.
- One/ten/twenty pickers; 10/30-second handling, 40/60 mix, five-second unloading and previous-unload starts.
- Spatial chunks, balance, round-robin reference, moves/swaps and congestion v1/v2/auto.
- NN, 2-opt, reinsertion, alternating search and optional segment DP.
- One-step unloading lookahead, savings bundling, availability/location-aware completion scheduling, minimum-task splitting and experimental LNS.
- Original planning-resource bug and its fix, flag propagation fixes, stronger tests and analysis corrections.
- Full commit history through `c5e8df3` plus archive documentation.

These features are not all recommended or fully validated. The LNS integration has disclosed group/order/owner consistency risks. The variable split policy was inactive in evaluated conditions. No silent behavioral fix was made while archiving.

## Evidence and current checks

The full suite **passed 88 tests** during archive integration. This includes 37 baseline and 51 extension tests. The original `picking/` package remains unchanged.

Saved experiment records total **2,280**:

- Round 1: 786, generated before the planner-serialization fix; historical only.
- Round 2: 474, post-fix repeated-task and congestion comparisons.
- Round 3: 220 development and 420 evaluation-set comparisons.
- Round 4: 20 development and 360 fixed/measured comparisons.

Record counts do not mean that many independent workloads. Saved-data archive reaggregation was executed; no full performance experiment or new parameter search was run in this packaging task. [Machine-readable counts, file checksums and comparisons](../results/expansion-archive-summary.json) are included. Checksums normalize CRLF to LF for portability.

## Qualified observations

- Round 3: cap24/balanced/NN→2-opt→reinsertion versus cap12/spatial/NN reduced completion by about 3.84% (64.7 seconds) in the ten-picker/480-request condition. Cap expansion explains most of the common-baseline ladder difference; 2-opt alone does not explain this gain.
- The larger-layout/960-request comparison reports about 10.94%, but geometry, density and request volume differ from the small-layout comparison. Size alone is not a proven cause.
- Round 4: completion scheduling versus the cap24 candidate improves the ten-picker/480-request comparison by about 0.845% (13.6 seconds) in fixed mode, and 2.912% (47.4 seconds) in measured mode. Keep modes separate.
- Twenty pickers/480 requests worsens: approximately -2.28% in the cap comparison and -4.865% fixed / -3.363% measured in the completion comparison.
- Savings, congestion and lookahead do not establish a stable preferred policy in tested conditions. Inactive splitting and unresolved LNS propagation do not establish algorithmic ineffectiveness.

## Why this is not a final scheduling recommendation

Planning costs exceed the predeclared 15-second threshold in some conditions; a measured large-layout case reaches about 79.4 seconds. A common baseline cost does not waive that failure.

Successive rounds reuse evaluation seed IDs 203–221 (odd numbers); fresh project-wide independent evaluation and repeated same-input timing were not completed. Basket capacity is absent; cap24 is 24 requests, not 24 item units. Geometry/side labels are synthetic and aisle collisions do not impose delay.

Conditional improvements are useful observations, but cannot be generalized to real facilities or all worker/task configurations.

## Deferred work, only if the extension is resumed

- [ ] Validate and repair LNS group/order/owner propagation and exception visibility before interpreting its results.
- [ ] Calibrate physical workload limits and warehouse geometry or state the abstract assumptions explicitly.
- [ ] Freeze policies and computation budget, then use fresh evaluation groups.
- [ ] Repeat method timings and distinguish exposed delay from summed worker waiting.
- [ ] Trace predictions to issued work and actual completion in congestion/reassignment experiments.
- [ ] Isolate warehouse-scale, demand, handling-time and batching effects.

These are future conditions, not an active commitment to continue experimentation.

## Documents and reproduction

- [Full history, algorithms, defects, findings and closure](20-expansion-study-record.md)
- [Target plan](17-expansion-plan.md)
- [Initial model and follow-up](15-multi-picker-simulation.md)
- [Batching evidence and corrected criteria](18-evidence-experiments.md)
- [Completion/savings/LNS evidence and caveats](19-completion-assignment-lns.md)
- [Source](../simulation/) and [tests](../tests/test_simulation.py)

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest discover -s tests
python -m simulation.archive_summary results/expansion-archive-summary-rerun.json
python -I simulation/analysis2.py results/multi2
python -I simulation/analysis3.py results/multi3-eval
```

The archive-summary command reads saved data only. Choose a new output file to preserve the packaged summary. Full experiment commands remain in documents 18 and 19 for a future resumption; they are not required to read this archive.
